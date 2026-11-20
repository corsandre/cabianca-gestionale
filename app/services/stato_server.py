"""
Stato del server per Impostazioni (riquadro «Server»): disco, memoria e da cosa sono occupati.

Due fonti:
- quello che il gestionale vede da solo dal container: spazio del disco della VPS (il volume `data` sta sul
  disco vero), memoria e carico della VPS (/proc), e le sue cartelle (foto delle bolle, fatture, database,
  backup) misurate qui;
- data/stato_server.json, scritto ogni 15 minuti sulla VPS da scripts/stato_server.py: Docker (immagini, cache
  di build), memoria di ogni container, ordini e Postiz, log di sistema. Se manca o è vecchio si mostra solo la
  prima parte, con un avviso.

Le funzioni di calcolo (segmenti, crescita, livello, avvisi) lavorano su dizionari semplici e non toccano Flask,
così si provano in tests/test_stato_server.py.
"""
import json
import os
import shutil
import time
from datetime import date, datetime

GIORNI_CRESCITA = 30
VECCHIO_DOPO_S = 3600            # dati dello script più vecchi di così: avviso «non aggiornati»
SOGLIA_ATTENZIONE, SOGLIA_CRITICA, SOGLIA_TELEGRAM = 75, 90, 85   # % del disco
CACHE_DA_PULIRE = 5 * 1024 ** 3  # cache di build recuperabile oltre la quale si consiglia la pulizia
MEMORIA_BASSA = 10               # % di memoria disponibile sotto la quale si avvisa

# cartelle del gestionale: (chiave, nome, colore)
VOCI_GESTIONALE = [
    ("bolle", "Foto delle bolle", "#c2185b"),
    ("fatture_ricevute", "Fatture ricevute", "#009d5a"),
    ("fatture_emesse", "Fatture emesse", "#297a38"),
    ("movimenti", "Allegati dei movimenti", "#c6a96f"),
    ("altri_upload", "Altri allegati", "#d4b98a"),
    ("database", "Database", "#1565c0"),
    ("copie_db", "Copie del database prima dei rilasci", "#5c8ad6"),
    ("backup", "Backup giornalieri", "#90b4ee"),
    ("impianto", "Fotografie dell'impianto", "#7e57c2"),
]
CARTELLA_UPLOAD = {"allevamento_consegne": "bolle", "fatture_emesse": "fatture_emesse", "movimenti": "movimenti"}
COLORI_ALTRO = {"docker_immagini": "#fcc900", "docker_cache": "#f57c00", "docker_altro": "#ffb74d",
                "ordini": "#00838f", "social": "#4db6ac", "log": "#9e9e9e", "sistema": "#bdbdbd", "libero": "#e9ecef"}


# ── misura delle cartelle del gestionale ─────────────────────────────────────────────────────────

def _somma(percorsi, da_quando):
    """(byte, file, byte dei file modificati dopo da_quando) di una lista di file e cartelle."""
    byte = n = recenti = 0
    for p in percorsi:
        if os.path.isdir(p):
            for radice, _, nomi in os.walk(p):
                for nome in nomi:
                    b, r = _file(os.path.join(radice, nome), da_quando)
                    byte, n, recenti = byte + b, n + 1, recenti + r
        elif os.path.isfile(p):
            b, r = _file(p, da_quando)
            byte, n, recenti = byte + b, n + 1, recenti + r
    return byte, n, recenti


def _file(p, da_quando):
    try:
        st = os.stat(p)
    except OSError:
        return 0, 0
    return st.st_size, (st.st_size if st.st_mtime >= da_quando else 0)


def cartelle_gestionale(uploads, data, backups):
    """{chiave: {"byte", "file", "ultimi_30"}} per le voci di VOCI_GESTIONALE."""
    da_quando = time.time() - GIORNI_CRESCITA * 86400
    gruppi = {k: [] for k, _, _ in VOCI_GESTIONALE}
    for nome in (os.listdir(uploads) if os.path.isdir(uploads) else []):
        p = os.path.join(uploads, nome)
        if os.path.isdir(p):
            gruppi[CARTELLA_UPLOAD.get(nome, "altri_upload")].append(p)
        else:      # le fatture SDI ricevute stanno nella radice di uploads (XML e la loro copia PDF)
            gruppi["fatture_ricevute" if nome.lower().endswith((".xml", ".pdf", ".p7m")) else "altri_upload"].append(p)
    for nome in (os.listdir(data) if os.path.isdir(data) else []):
        p = os.path.join(data, nome)
        if nome == "gestionale.db" or nome.startswith("gestionale.db-"):      # anche -wal/-shm di SQLite
            gruppi["database"].append(p)
        elif nome.startswith("gestionale.db.") or (nome.endswith(".db") and nome.startswith("_")):
            gruppi["copie_db"].append(p)
        elif nome == "impianto":
            gruppi["impianto"].append(p)
        elif not nome.startswith(("stato_server", ".stato_server")):
            gruppi["copie_db" if nome.endswith(".db") else "altri_upload"].append(p)
    gruppi["backup"].append(backups)
    out = {}
    for k, percorsi in gruppi.items():
        byte, n, recenti = _somma(percorsi, da_quando)
        out[k] = {"byte": byte, "file": n, "ultimi_30": recenti}
    return out


def leggi_script(data):
    """Dati di scripts/stato_server.py e la loro storia ({} e [] se mancano o non si leggono)."""
    def carica(nome, vuoto):
        try:
            with open(os.path.join(data, nome)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return vuoto
    return carica("stato_server.json", {}), carica("stato_server_storia.json", [])


def _da_proc():
    """Memoria, carico e accensione visti dal container (sono quelli della VPS: niente limiti sul container)."""
    mem, carico, acceso = {}, None, None
    try:
        with open("/proc/meminfo") as f:
            info = {r.split(":")[0]: int(r.split(":")[1].split()[0]) * 1024 for r in f}
        mem = {"totale": info["MemTotal"], "disponibile": info["MemAvailable"],
               "swap_totale": info.get("SwapTotal", 0), "swap_usata": info.get("SwapTotal", 0) - info.get("SwapFree", 0)}
        with open("/proc/loadavg") as f:
            carico = [float(x) for x in f.read().split()[:3]]
        with open("/proc/uptime") as f:
            acceso = int(float(f.read().split()[0]))
    except (OSError, ValueError, KeyError):
        pass
    return mem, carico, acceso


# ── calcoli (senza Flask) ────────────────────────────────────────────────────────────────────────

def eta_secondi(script, adesso=None):
    """Secondi dall'ultima lettura dello script, None se non c'è."""
    try:
        quando = datetime.fromisoformat(script["aggiornato"])
    except (KeyError, TypeError, ValueError):
        return None
    return max(0, int(((adesso or datetime.now()) - quando).total_seconds()))


def segmenti_disco(disco, cartelle, script):
    """Voci della barra del disco: [{"chiave", "nome", "byte", "colore"}], in ordine, che sommate fanno il totale.
    Senza i dati dello script, Docker, ordini, Postiz e log finiscono in «Sistema e altro»."""
    seg = [{"chiave": k, "nome": nome, "byte": cartelle.get(k, {}).get("byte", 0), "colore": col}
           for k, nome, col in VOCI_GESTIONALE]
    d = script.get("docker", {}) if script else {}
    servizi = script.get("servizi", {}) if script else {}
    if script:
        seg += [
            {"chiave": "docker_immagini", "nome": "Docker: immagini dei programmi", "byte": d.get("immagini", {}).get("usato", 0)},
            {"chiave": "docker_cache", "nome": "Docker: cache di build", "byte": d.get("cache_build", {}).get("usato", 0)},
            {"chiave": "docker_altro", "nome": "Docker: container e volumi",
             "byte": d.get("container", {}).get("usato", 0) + d.get("volumi", {}).get("usato", 0)},
            {"chiave": "ordini", "nome": "Ordini (street food)", "byte": servizi.get("ordini", 0)},
            {"chiave": "social", "nome": "Postiz (social)", "byte": servizi.get("social", 0)},
            {"chiave": "log", "nome": "Log di sistema", "byte": script.get("log_sistema", 0)},
        ]
        for s in seg[len(VOCI_GESTIONALE):]:
            s["colore"] = COLORI_ALTRO[s["chiave"]]
    noti = sum(s["byte"] for s in seg)
    seg.append({"chiave": "sistema", "nome": "Sistema e altro", "byte": max(0, disco["usato"] - noti), "colore": COLORI_ALTRO["sistema"]})
    seg.append({"chiave": "libero", "nome": "Libero", "byte": disco["libero"], "colore": COLORI_ALTRO["libero"]})
    tot = sum(s["byte"] for s in seg) or 1
    for s in seg:
        s["perc"] = s["byte"] * 100 / tot
    return seg


SERVIZI_CONTAINER = [("cabianca-gestionale", "Gestionale", "#009d5a"), ("cabianca-ordini", "Ordini", "#00838f"),
                     ("cabianca-social", "Postiz (social)", "#4db6ac")]


def segmenti_memoria(mem, script):
    """Voci della barra della memoria: un segmento per servizio (somma dei suoi container), sistema, disponibile."""
    usata = mem["totale"] - mem["disponibile"]
    per_servizio = {}
    for c in (script.get("container", []) if script else []):
        chiave = next((pref for pref, _, _ in SERVIZI_CONTAINER if c["nome"].startswith(pref)), "altri")
        per_servizio[chiave] = per_servizio.get(chiave, 0) + c["memoria"]
    seg = [{"chiave": pref, "nome": nome, "byte": per_servizio[pref], "colore": col}
           for pref, nome, col in SERVIZI_CONTAINER if pref in per_servizio]
    if per_servizio.get("altri"):
        seg.append({"chiave": "altri", "nome": "Altri container", "byte": per_servizio["altri"], "colore": "#ffb74d"})
    seg.append({"chiave": "sistema", "nome": "Sistema e cache", "byte": max(0, usata - sum(s["byte"] for s in seg)), "colore": "#bdbdbd"})
    seg.append({"chiave": "libero", "nome": "Disponibile", "byte": mem["disponibile"], "colore": "#e9ecef"})
    tot = sum(s["byte"] for s in seg) or 1
    for s in seg:
        s["perc"] = s["byte"] * 100 / tot
    return seg


def crescita(storia, cartelle, libero):
    """Quanto cresce il disco al mese e tra quanti mesi sarebbe pieno.
    Con almeno 7 giorni di storia dallo script si usa l'andamento del disco intero; prima, solo i file del
    gestionale degli ultimi 30 giorni (foto, fatture, backup)."""
    gestionale_mese = sum(v.get("ultimi_30", 0) for v in cartelle.values())
    punti = [p for p in storia if p.get("data") and p.get("disco_usato") is not None]
    disco_mese = None
    if len(punti) >= 7:
        primo, ultimo = punti[0], punti[-1]
        giorni = (date.fromisoformat(ultimo["data"]) - date.fromisoformat(primo["data"])).days
        if giorni >= 6:
            disco_mese = (ultimo["disco_usato"] - primo["disco_usato"]) * 30 / giorni
    ritmo = disco_mese if disco_mese is not None else gestionale_mese
    mesi = libero / ritmo if ritmo and ritmo > 0 else None
    return {"gestionale_mese": gestionale_mese, "disco_mese": disco_mese, "mesi_al_pieno": mesi,
            "giorni_storia": len(punti)}


def testo_byte(n):
    """'1,2 GB', '81 MB', '640 kB' (unità da 1024, virgola italiana)."""
    n = n or 0
    for unita, d in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("kB", 1024)):
        if n >= d:
            v = n / d
            return (f"{v:.1f}" if v < 100 else f"{v:.0f}").replace(".", ",") + " " + unita
    return f"{n} B"


def testo_durata(secondi):
    """'32 giorni', '5 ore', '12 minuti'."""
    if secondi is None:
        return "–"
    if secondi >= 2 * 86400:
        return f"{secondi // 86400} giorni"
    if secondi >= 2 * 3600:
        return f"{secondi // 3600} ore"
    minuti = max(1, secondi // 60)
    return "1 minuto" if minuti == 1 else f"{minuti} minuti"


def livello(perc):
    return "critico" if perc >= SOGLIA_CRITICA else "attenzione" if perc >= SOGLIA_ATTENZIONE else "ok"


def avvisi(disco_perc, mem, script, eta):
    """Frasi da mostrare sopra le barre (e da mandare su Telegram)."""
    out = []
    if disco_perc >= SOGLIA_TELEGRAM:
        out.append(f"Disco quasi pieno: {disco_perc:.0f}% occupato.")
    cache = (script.get("docker", {}).get("cache_build", {}) if script else {}).get("recuperabile", 0)
    if cache >= CACHE_DA_PULIRE:
        out.append(f"La cache di build di Docker tiene {testo_byte(cache)} che si possono liberare "
                   "(sulla VPS: docker builder prune -af). Non tocca i programmi in funzione.")
    if mem and mem["totale"] and mem["disponibile"] * 100 / mem["totale"] < MEMORIA_BASSA:
        out.append(f"Memoria quasi finita: disponibili {testo_byte(mem['disponibile'])}.")
    if mem and mem.get("swap_usata", 0) > 0 and mem["disponibile"] * 100 / mem["totale"] < 2 * MEMORIA_BASSA:
        out.append("Il server sta usando la swap: la memoria non basta.")
    return out


# ── per la pagina e lo scheduler ─────────────────────────────────────────────────────────────────

def _percorsi(app):
    base = os.path.abspath(os.path.join(app.root_path, ".."))
    return app.config["UPLOAD_FOLDER"], os.path.join(base, "data"), os.path.join(base, "backups")


def stato(app):
    """Tutto quello che serve al riquadro «Server» di Impostazioni."""
    uploads, data, backups = _percorsi(app)
    script, storia = leggi_script(data)
    eta = eta_secondi(script)
    script_ok = script if eta is not None and eta <= VECCHIO_DOPO_S else {}
    du = shutil.disk_usage(data)
    disco = script_ok.get("disco") or {"totale": du.total, "usato": du.used, "libero": du.free}
    mem, carico, acceso = _da_proc()
    mem = script_ok.get("memoria") or mem
    cartelle = cartelle_gestionale(uploads, data, backups)
    disco_perc = disco["usato"] * 100 / disco["totale"] if disco["totale"] else 0
    mem_perc = (mem["totale"] - mem["disponibile"]) * 100 / mem["totale"] if mem.get("totale") else 0
    return {
        "disco": disco, "disco_perc": disco_perc, "disco_livello": livello(disco_perc),
        "segmenti_disco": segmenti_disco(disco, cartelle, script_ok),
        "memoria": mem, "memoria_perc": mem_perc, "memoria_livello": livello(mem_perc),
        "segmenti_memoria": segmenti_memoria(mem, script_ok) if mem.get("totale") else [],
        "cartelle": cartelle, "voci_gestionale": VOCI_GESTIONALE,
        "carico": script_ok.get("carico") or carico, "cpu": script_ok.get("cpu") or os.cpu_count(),
        "acceso_da_s": script_ok.get("acceso_da_s") or acceso,
        "container": script_ok.get("container", []), "docker": script_ok.get("docker", {}),
        "crescita": crescita(storia, cartelle, disco["libero"]),
        "avvisi": avvisi(disco_perc, mem, script_ok, eta),
        "script_eta_s": eta, "script_ok": bool(script_ok),
    }


def controllo_giornaliero(app):
    """Ogni mattina: se il disco supera la soglia o la memoria è quasi finita, un messaggio sul canale sistema.
    Il consiglio di pulire la cache di Docker da solo non manda niente (si vede in Impostazioni)."""
    from app.services.telegram_bot import send_telegram_message
    s = stato(app)
    gravi = [a for a in s["avvisi"] if not a.startswith("La cache di build")]
    if not gravi:
        return False
    testo = ["🖥️ <b>Server</b>: " + " ".join(gravi),
             f"Disco {s['disco_perc']:.0f}% ({testo_byte(s['disco']['libero'])} liberi), memoria {s['memoria_perc']:.0f}%.",
             "Dettaglio in Impostazioni › Server."]
    return send_telegram_message("\n".join(testo), canale="sistema")
