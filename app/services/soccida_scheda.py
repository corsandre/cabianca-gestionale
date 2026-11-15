"""
Soccida: preparazione della scheda.

Prende i dati raccolti (soccida_dati) e i risultati del calcolo (soccida) e li
trasforma in quello che il template mostra: testi, grafici, elenco dei dati da
aggiornare. Qui non ci sono regole del contratto né letture «di sostanza» dal
database: solo presentazione. Il template app/templates/allevamento/soccida.html
non fa conti.

La scheda si ricalcola sul server a ogni prova dello scenario: il motore è uno
solo (soccida.py), non c'è una copia in JavaScript.
"""
from dataclasses import replace
from datetime import date, timedelta

from app.models import ConsegnaSiero
from app.services import soccida as S
from app.services import soccida_dati as D

# simulazioni: quella principale e quelle, più leggere, dei grafici di confronto
N_PRINCIPALE = 4000
N_CONFRONTO = 600
# istogramma del margine: da −20.000 a +25.000 € a passi di 2.500
ISTO_MIN, ISTO_MAX, ISTO_PASSO = -20000, 25000, 2500
PESI_CONFRONTO = (-4, -2, 0, 2, 4, 6, 8)          # kg rispetto allo scenario
GIORNI_GRIGLIA = (-10, -5, 0, 5, 10)              # giorni rispetto alle date dello scenario
FINESTRA_MINIMA = 7                               # giorni minimi tra primo e ultimo carico nella griglia
MESI = ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
        "ottobre", "novembre", "dicembre")


# ── Formati ─────────────────────────────────────────────────────────────────

def n0(v):
    return f"{round(v):,}".replace(",", ".")


def n1(v, decimali=1):
    return f"{v:,.{decimali}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def eur(v):
    return f"{n0(v)} €"


def seur(v):
    return f"{'+' if v >= 0 else '−'}{n0(abs(v))} €"


def pct(p):
    return f"{round(p * 100)}%"


def gm(d):
    return d.strftime("%d/%m")


def gma(d):
    return d.strftime("%d/%m/%Y")


# ── Scenario di prova dai parametri della pagina ────────────────────────────

CAMPI_PROVA = ("primo", "ultimo", "conf", "peso", "resa", "premi", "morti", "giac")


def scenario_di_prova(standard, sit, args):
    """Scenario e situazione modificati dai valori provati nella scheda (parametri dell'indirizzo).
    Ritorna (scenario, situazione, in_prova)."""
    def numero(nome, attuale):
        try:
            return float(str(args[nome]).replace(",", ".")) if args.get(nome) not in (None, "") else attuale
        except ValueError:
            return attuale

    def giorno(nome, attuale):
        try:
            return date.fromisoformat(args[nome]) if args.get(nome) else attuale
        except ValueError:
            return attuale

    primo, ultimo = giorno("primo", standard.primo_carico), giorno("ultimo", standard.ultimo_carico)
    if ultimo < primo:
        ultimo = primo
    sce = replace(
        standard, primo_carico=primo, ultimo_carico=ultimo,
        date_confermate=(args.get("conf") == "1") if "conf" in args or "primo" in args else standard.date_confermate,
        peso_extra_kg=numero("peso", standard.peso_extra_kg), resa_perc=numero("resa", standard.resa_perc),
        premi_perc=numero("premi", standard.premi_perc), morti_giorno=numero("morti", standard.morti_giorno),
    )
    sit2 = replace(sit, giacenza_iniziale_kg=numero("giac", sit.giacenza_iniziale_kg))
    return sce, sit2, (sce != standard or sit2 != sit)


# ── Pezzi della scheda ──────────────────────────────────────────────────────

def _posizione(v):
    return max(0.0, min(100.0, (v - ISTO_MIN) / (ISTO_MAX - ISTO_MIN) * 100))


def _istogramma(sim):
    n_colonne = (ISTO_MAX - ISTO_MIN) // ISTO_PASSO
    conteggi = [0] * n_colonne
    for m in sim.margini:
        conteggi[max(0, min(n_colonne - 1, int((m - ISTO_MIN) // ISTO_PASSO)))] += 1
    massimo = max(conteggi) or 1
    totale = len(sim.margini) or 1
    colonne = []
    for i, c in enumerate(conteggi):
        da = ISTO_MIN + i * ISTO_PASSO
        colonne.append({
            "altezza": max(1.0, c / massimo * 100), "sotto": da < 0,
            "etichetta": (("+" if da > 0 else "") + str(da // 1000)) if i % 2 == 0 else "",
            "titolo": f"Da {seur(da)} a {seur(da + ISTO_PASSO)}: {n1(c / totale * 100)}% degli scenari",
        })
    return colonne


def _colore_griglia(p):
    return "c1" if p < 0.30 else "c2" if p < 0.45 else "c3" if p < 0.55 else "c4" if p < 0.70 else "c5"


def _per_peso(sit, sce, contratto, premi_noti):
    out = []
    for dp in PESI_CONFRONTO:
        prova = replace(sce, peso_extra_kg=sce.peso_extra_kg + dp)
        p = S.simula(sit, prova, contratto, n=N_CONFRONTO, premi_noti=premi_noti).probabilita
        kg = S.stima(sit, prova, contratto).peso_uscita_kg or 0
        out.append({"pct": pct(p), "altezza": max(2.0, p * 86), "attuale": dp == 0, "etichetta": n0(kg),
                    "peso": round(prova.peso_extra_kg, 1), "titolo": f"Peso medio {n1(kg)} kg: premio al {pct(p)}"})
    return out


def _griglia(sit, sce, contratto, premi_noti):
    colonne = [sce.ultimo_carico + timedelta(days=g) for g in GIORNI_GRIGLIA]
    righe = []
    for gi in GIORNI_GRIGLIA:
        primo = sce.primo_carico + timedelta(days=gi)
        celle = []
        for ultimo in colonne:
            if (ultimo - primo).days < FINESTRA_MINIMA or primo < sit.oggi:
                celle.append({"valida": False})
                continue
            p = S.simula(sit, replace(sce, primo_carico=primo, ultimo_carico=ultimo), contratto,
                         n=N_CONFRONTO, premi_noti=premi_noti).probabilita
            celle.append({"valida": True, "pct": pct(p), "colore": _colore_griglia(p), "primo": primo.isoformat(),
                          "ultimo": ultimo.isoformat(), "attuale": primo == sce.primo_carico and ultimo == sce.ultimo_carico,
                          "titolo": f"Primo carico {gm(primo)}, ultimo {gm(ultimo)}: premio al {pct(p)}"})
        righe.append({"etichetta": f"primo {gm(primo)}", "celle": celle})
    return {"colonne": [f"ultimo {gm(d)}" for d in colonne], "righe": righe}


def _leve(sit, sce, contratto):
    elenco = S.leve(sit, sce, contratto)
    massimo = max((max(abs(a), abs(b)) for _, _, a, _, b in elenco), default=1) or 1
    return [{"nome": nome, "peggio": f"{et_a} {seur(a)}", "meglio": f"{seur(b)} {et_b}",
             "larghezza_peggio": abs(a) / massimo * 62, "larghezza_meglio": abs(b) / massimo * 62,
             # una leva può anche aiutare nel verso «peggio» (es. meno siero): il colore segue il segno
             "peggio_negativo": a < 0, "meglio_positivo": b > 0}
            for nome, et_a, a, et_b, b in elenco]


def _quanto_reale(st):
    """Quote del conto già reali, separate per mangime, siero e carne (percentuali intere)."""
    c = st.conto
    mangime = round(st.mangime_finora_kg / c.mangime_kg * 100) if c.mangime_kg else 0
    fatt = c.siero_eur - st.siero_da_fatturare_eur - st.siero_futuro_eur
    siero_f = round(fatt / c.siero_eur * 100) if c.siero_eur else 0
    siero_r = round(st.siero_da_fatturare_eur / c.siero_eur * 100) if c.siero_eur else 0
    carne_r = round(st.carne.kg_riscontrati / c.carne_kg * 100) if c.carne_kg else 0
    carne_p = round((st.carne.kg_da_riscontrare + st.carne.kg_scarti) / c.carne_kg * 100) if c.carne_kg else 0
    return {"mangime": mangime, "siero_fatturato": siero_f, "siero_registrato": siero_r,
            "siero_stimato": max(0, 100 - siero_f - siero_r), "carne_riscontrata": carne_r, "carne_partita": carne_p,
            "carne_stimata": max(0, 100 - carne_r - carne_p)}


def _righe_conto(st, sit, sce, par, contratto):
    c = st.conto
    fatturato = c.siero_eur - st.siero_da_fatturare_eur - st.siero_futuro_eur
    in_stalla = sit.capi_presenti > 0
    righe = [
        ("Mangime consumato finora", f"{n0(st.mangime_finora_kg)} kg",
         f"Bolle {n0(sit.mangime_bolle_kg)} + giacenza iniziale {n0(sit.giacenza_iniziale_kg)} − silos {n0(sit.giacenza_oggi_kg)}",
         "Reale, giacenze stimate" if in_stalla else "Reale"),
    ]
    if in_stalla:
        righe.append(("Mangime fino a fine ciclo", f"{n0(st.mangime_residuo_kg)} kg",
                      f"{n0(sit.consumo_mangime_giorno_kg)} kg al giorno pieni fino al {gm(sce.primo_carico)}, poi a calare "
                      f"fino al {gm(sce.ultimo_carico)}: {n1(st.giorni_equivalenti)} giorni pieni equivalenti", "Stimato"))
    righe.append(("Mangime totale", f"{n0(c.mangime_kg)} kg", "Consumato più quello ancora da consumare",
                  "Stimato" if in_stalla else "Reale"))
    pezzi = []
    if st.carne.kg_riscontrati:
        pezzi.append(f"{n0(st.carne.kg_riscontrati)} kg riscontrati")
    if st.carne.kg_da_riscontrare:
        pezzi.append(f"{n0(st.carne.kg_da_riscontrare)} kg partiti, resa {n1(st.carne.resa_usata * 100)}%")
    if st.carne.kg_scarti:
        pezzi.append(f"{n0(st.carne.kg_scarti)} kg di scarti al {n0(contratto.quota_scarti_perc)}%")
    if in_stalla:
        pezzi.append(f"{n0(st.capi_macello)} capi × {n1(st.peso_uscita_kg)} kg × {n1(sce.resa_perc)}%")
    righe += [
        ("Carne valida", f"{n0(c.carne_kg)} kg", "; ".join(pezzi), "Stimato" if in_stalla or st.carne.kg_da_riscontrare else "Reale"),
        ("Indice di conversione", n1(c.indice, 3), "Mangime totale diviso carne valida", ""),
        ("Valore da tabella", f"{n1(c.valore_kg, 4)} €/kg",
         f"Interpolato in tabella: {n1(c.percentuale, 2)}% × {n1(contratto.prezzo_partenza, 2)} € × {n1(1 + contratto.premio_tabella_perc / 100, 2)}", "Contratto"),
        ("Resa", eur(c.resa_eur), f"Valore × carne valida, più {n1(c.premi_perc)}% di premi",
         "Premi comunicati" if par.premi_noti else "Premi stimati"),
        ("Siero", eur(c.siero_eur), f"{eur(fatturato)} fatturati con IVA, {eur(st.siero_da_fatturare_eur)} consegnati da fatturare, "
                                     f"{eur(st.siero_futuro_eur)} stimati", ""),
        ("Minimo del ciclo", eur(c.minimo_eur), f"{eur(contratto.minimo_annuo)} / {contratto.giorni_anno} × {n0(c.giorni)} giorni, "
                                                 f"dal {gm(sit.ultimo_giorno_pagato_prec + timedelta(days=1))} al {gm(sce.ultimo_carico)}",
         "Date confermate" if sce.date_confermate else "Dipende dalla data"),
        ("Resa meno siero", eur(c.resa_netta_eur), "Da confrontare con il minimo", ""),
        ("Pagato da Veronesi", eur(c.pagato_eur), "Il più alto tra resa e minimo più siero", ""),
        ("Saldo", eur(c.saldo_eur), f"Pagato meno {eur(c.anticipi_eur)} di anticipi", ""),
    ]
    return [{"voce": v, "valore": val, "come": come, "stato": stato} for v, val, come, stato in righe]


def _dati_da_aggiornare(ciclo, par, sit, sce, st, dettagli, contratto, url):
    """Elenco dei dati che reggono la stima, dal più pesante: stato, valore usato, quanto sposta
    il margine e dove si aggiorna. `url` è una funzione nome → indirizzo della pagina."""
    def peso(var):
        base = st.conto.margine_eur
        return abs(S.stima(sit, sce, contratto, var).conto.margine_eur - base)

    voci = []
    in_stalla = sit.capi_presenti > 0
    if in_stalla:
        voci.append({
            "nome": "Date dei carichi", "stato": "Reale" if sce.date_confermate else "Ipotesi",
            "valore": f"Primo carico {gm(sce.primo_carico)}, ultimo {gm(sce.ultimo_carico)}",
            "fonte": "Confermate da Veronesi" if sce.date_confermate else "Scelte a mano",
            "peso": peso(S.Variazione(ultimo_giorni=7)), "peso_testo": "7 giorni sull'ultimo carico valgono circa {}",
            "azione": "Correggile appena Veronesi dà notizie, poi segnale come confermate.",
            "link": ("Scenario standard", url("impostazioni") + "#scenario")})
        eta_cens = dettagli.get("censimento_eta")
        voci.append({
            "nome": "Peso vivo di uscita", "stato": "Stimato", "valore": f"{n1(st.peso_uscita_kg)} kg di media",
            "fonte": ("Curva di accrescimento, età dal censimento del " + gm(eta_cens.data)) if eta_cens else "Nessun censimento con le età",
            "peso": peso(S.Variazione(peso_kg=2)), "peso_testo": "2 kg valgono circa {}",
            "azione": "Fai un censimento con età e pesi aggiornati, o correggi i kg in più nello scenario.",
            "link": ("Censimento", url("censimento"))})
        voci.append({
            "nome": "Capi presenti", "stato": "Stimato", "valore": f"{n0(sit.capi_presenti)} di Veronesi",
            "fonte": f"Conteggio per box meno {dettagli['cabianca_in_stalla']} suini di Fattoria Ca' Bianca ancora in stalla",
            "peso": peso(S.Variazione(capi=20)), "peso_testo": "20 capi valgono circa {}",
            "azione": "Registra morti e uscite, e rifai il censimento se il conteggio non ti torna.",
            "link": ("Censimento", url("censimento"))})
        if not dettagli["giacenza_comunicata"]:
            voci.append({
                "nome": "Mangime nei silos oggi", "stato": "Stimato", "valore": f"{n1(sit.giacenza_oggi_kg / 1000)} t",
                "fonte": "Giacenza stimata dall'ultima ricalibrazione",
                "peso": peso(S.Variazione(mangime_kg=10000)), "peso_testo": "10 t valgono circa {}",
                "azione": "Controlla i silos e ricalibra la giacenza.", "link": ("Consegne, mangime", url("consegne"))})
    reale = S.resa_media(sit.carichi)
    da_riscontrare = sum(1 for c in sit.carichi if not c.scarto and not c.riscontrato)
    if in_stalla or da_riscontrare:
        voci.append({
            "nome": "Resa al macello", "stato": "Reale" if reale and not in_stalla and not da_riscontrare else ("Stimato" if reale else "Ipotesi"),
            "valore": f"{n1(sce.resa_perc)}%",
            "fonte": "Media dei carichi riscontrati" if reale else "Nessun carico ancora riscontrato",
            "peso": peso(S.Variazione(resa_punti=0.5)), "peso_testo": "Mezzo punto vale circa {}",
            "azione": (f"{da_riscontrare} carichi partiti senza riscontro: aggiungilo all'uscita." if da_riscontrare
                       else "Aggiungi il riscontro del macello alle uscite quando arriva."),
            "link": ("Spostamenti, uscite", url("spostamenti"))})
    if par.giacenza_iniziale_kg is None or in_stalla:
        voci.append({
            "nome": "Giacenza iniziale di mangime", "stato": "Ipotesi" if par.giacenza_iniziale_kg is None else "Reale",
            "valore": f"{n0(sit.giacenza_iniziale_kg)} kg", "fonte": "Mai inserita: conta zero" if par.giacenza_iniziale_kg is None else "Da Impostazioni Soccida",
            "peso": peso(S.Variazione(mangime_kg=1000)), "peso_testo": "Ogni tonnellata vale circa {}",
            "azione": "Inserisci il dato comunicato a Veronesi a inizio ciclo.", "link": ("Impostazioni Soccida", url("impostazioni") + "#ciclo")})
    if st.siero_da_fatturare_eur > 0:
        voci.append({
            "nome": "Siero consegnato, non fatturato", "stato": "Stimato",
            "valore": f"{n1(sit.siero_da_fatturare_t)} t a {n1(sit.siero_prezzo_t, 2)} €/t",
            "fonte": "Quantità dalle Consegne, prezzo dell'ultima fattura con gasolio e IVA",
            "peso": st.siero_da_fatturare_eur * 0.03, "peso_testo": "Circa " + eur(st.siero_da_fatturare_eur) + " in tutto",
            "azione": "Si aggiorna da solo quando arriva la fattura del mese.", "link": None})
    if not par.premi_noti:
        voci.append({
            "nome": "Premi da prontuario", "stato": "Ipotesi", "valore": f"{n1(sce.premi_perc)}%", "fonte": "Stima da Impostazioni Soccida",
            "peso": peso(S.Variazione(premi_punti=1)), "peso_testo": "Un punto vale circa {}",
            "azione": "Inserisci la percentuale quando Veronesi la comunica e segnala come nota.",
            "link": ("Impostazioni Soccida", url("impostazioni") + "#ciclo")})
    voci.sort(key=lambda v: -v["peso"])
    for v in voci:
        v["peso_testo"] = v["peso_testo"].format(eur(round(v["peso"], -2)))
    return voci


def _da_fare(ciclo, par, sit, dettagli):
    """Registrazioni mancanti o che non coincidono: non cambiano la stima, servono per il conto finale."""
    voci = []
    entrati = sum(s.quantita for s in D.entrate(ciclo))
    if not entrati:
        voci.append("Spostamenti: nessuna entrata di suinetti registrata per questo ciclo")
    if not D._piva_siero(par):
        voci.append("Impostazioni Soccida: manca la partita IVA dei fornitori di siero, le fatture non vengono lette")
    if not D.anticipi(ciclo):
        voci.append("Impostazioni Soccida: nessun anticipo registrato")
    senza_bolla = ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).filter(
        (ConsegnaSiero.lotto.is_(None)) | (ConsegnaSiero.lotto == "")).count()
    if senza_bolla:
        voci.append(f"Consegne, siero: {senza_bolla} carichi senza numero di bolla")
    from app.models import ConsegnaMangime
    mang_senza = ConsegnaMangime.query.filter_by(ciclo_id=ciclo.id).filter(
        (ConsegnaMangime.numero_bolla.is_(None)) | (ConsegnaMangime.numero_bolla == "")).count()
    if mang_senza:
        voci.append(f"Consegne, mangime: {mang_senza} carichi senza numero di bolla")
    for s in D.uscite(ciclo):
        if s.categoria_uscita in D.CATEGORIE_VERONESI and not s.peso_medio_kg:
            voci.append(f"Spostamenti: uscita del {gm(s.data)} senza peso medio")
    return voci


def _siero_mensile(ciclo, dettagli):
    """Per ogni mese: carichi e tonnellate dalle bolle, totale della fattura, esito del confronto."""
    mesi = {}
    for c in ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).all():
        m = mesi.setdefault((c.data.year, c.data.month), {"carichi": 0, "t": 0.0, "fattura": None})
        m["carichi"] += 1
        m["t"] += c.quantita_qli / 10
    for f in dettagli["siero"]["fatture"]:
        m = mesi.setdefault((f.invoice_date.year, f.invoice_date.month), {"carichi": 0, "t": 0.0, "fattura": None})
        m["fattura"] = (m["fattura"] or 0) + D._importo(f)
    righe = []
    for (anno, mese), m in sorted(mesi.items()):
        if m["fattura"] is None:
            esito = "In attesa della fattura"
        elif not m["carichi"]:
            esito = "Fattura senza consegne registrate"
        else:
            esito = f"{n1(m['fattura'] / m['t'], 2)} €/t"
        righe.append({"mese": f"{MESI[mese - 1].capitalize()} {anno}", "carichi": m["carichi"] or "–",
                      "t": f"{n1(m['t'])} t" if m["carichi"] else "–",
                      "fattura": eur_cent(m["fattura"]) if m["fattura"] is not None else "–", "esito": esito})
    return righe


def eur_cent(v):
    return f"{n1(v, 2)} €"


def _animali(ciclo, par, contratto):
    righe = []
    ent = D.entrate(ciclo)
    if ent:
        capi = sum(s.quantita for s in ent)
        pesi = [(s.quantita, s.peso_medio_kg) for s in ent if s.peso_medio_kg]
        peso = sum(q * p for q, p in pesi) / sum(q for q, _ in pesi) if pesi else None
        righe.append({"data": f"{gm(ent[0].data)} – {gm(ent[-1].data)}" if len(ent) > 1 else gm(ent[0].data),
                      "tipo": "Entrate suinetti", "capi": n0(capi), "peso": f"{n1(peso)} kg" if peso else "–",
                      "conto": f"{len(ent)} arrivi registrati", "da_fare": False})
    else:
        righe.append({"data": "–", "tipo": "Entrate suinetti", "capi": "–", "peso": "–",
                      "conto": "Da registrare in Spostamenti", "da_fare": True})
    for s in D.uscite(ciclo):
        if s.categoria_uscita not in D.CATEGORIE_VERONESI:
            continue
        car = D.carico_da_spostamento(s)
        if car.scarto:
            kg = S.carne_partita([car], contratto).kg_scarti
            nota = f"{n0(kg)} kg di carne: calo {n1(contratto.calo_scarti_perc, 2)}%, al {n0(contratto.quota_scarti_perc)}%"
        elif car.riscontrato:
            resa = car.capi_riscontrati * car.peso_morto_kg / (car.capi * car.peso_vivo_kg) * 100 if car.peso_vivo_kg else None
            nota = f"Riscontrati {car.capi_riscontrati} a {n1(car.peso_morto_kg, 2)} kg" + (f", resa {n1(resa)}%" if resa else "")
        else:
            nota = "In attesa del riscontro"
        righe.append({"data": gm(s.data), "tipo": "Uscita, scarti" if car.scarto else "Uscita, fine ciclo", "capi": n0(s.quantita),
                      "peso": f"{n1(s.peso_medio_kg)} kg" if s.peso_medio_kg else "–", "conto": nota,
                      "da_fare": not car.scarto and not car.riscontrato, "id": s.id})
    cab = [s for s in D.uscite(ciclo) if s.categoria_uscita in D.CATEGORIE_CABIANCA]
    if cab:
        righe.append({"data": f"{gm(cab[0].data)} – {gm(cab[-1].data)}" if len(cab) > 1 else gm(cab[0].data),
                      "tipo": "Uscite agriturismo", "capi": n0(sum(s.quantita for s in cab)), "peso": "–",
                      "conto": "Escluse: suini di Fattoria Ca' Bianca", "da_fare": False})
    return righe


# ── La scheda ───────────────────────────────────────────────────────────────

def scheda(ciclo, par, args, url, oggi=None):
    """Tutto quello che serve al template della scheda Soccida."""
    oggi = oggi or date.today()
    sit0, dettagli = D.situazione(ciclo, par, oggi)
    contratto = D.contratto(ciclo, par)
    standard = D.scenario(par, sit0.carichi)
    sce, sit, in_prova = scenario_di_prova(standard, sit0, args)
    premi_noti = bool(par.premi_noti)

    try:
        st = S.stima(sit, sce, contratto)
    except ValueError as e:
        return {"errore": str(e), "ciclo": ciclo, "oggi": oggi}
    sim = S.simula(sit, sce, contratto, n=N_PRINCIPALE, premi_noti=premi_noti)
    c = st.conto
    pareggio = S.indice_pareggio(c, contratto)
    in_stalla = sit.capi_presenti > 0

    confronto = None
    if in_prova:
        st_std = S.stima(sit0, standard, contratto)
        sim_std = S.simula(sit0, standard, contratto, n=N_PRINCIPALE, premi_noti=premi_noti)
        punti = round((sim.probabilita - sim_std.probabilita) * 100)
        confronto = f"Rispetto allo standard: {seur(c.margine_eur - st_std.conto.margine_eur)}, {'+' if punti >= 0 else '−'}{abs(punti)} punti di probabilità"

    carichi_testo = ""
    if in_stalla:
        carichi_testo = (f"Circa {st.carichi_previsti} carichi da {sce.capi_carico} capi. Con {sce.carichi_giorno} al giorno servono almeno "
                         f"{st.giorni_minimi_carico} giorni di carico; la finestra è di {st.finestra_giorni} giorni"
                         + (": troppo stretta." if st.finestra_giorni < st.giorni_minimi_carico else "."))

    return {
        "errore": None, "ciclo": ciclo, "oggi": oggi, "giorno_ciclo": (oggi - ciclo.data_inizio).days, "in_stalla": in_stalla,
        "in_prova": in_prova, "confronto": confronto,
        # esito
        "prob": pct(sim.probabilita), "prob_sotto": pct(1 - sim.probabilita), "sopra": c.margine_eur >= 0,
        "margine": eur(abs(c.margine_eur)), "sfavorevole": seur(sim.sfavorevole_eur), "atteso": seur(sim.atteso_eur),
        "favorevole": seur(sim.favorevole_eur),
        "fascia": {"da": _posizione(sim.sfavorevole_eur), "larghezza": _posizione(sim.favorevole_eur) - _posizione(sim.sfavorevole_eur),
                   "atteso": _posizione(sim.atteso_eur), "zero": _posizione(0)},
        "indice": n1(c.indice, 2), "pareggio": n1(pareggio, 2) if pareggio else None,
        "margine_mangime": n1((pareggio * c.carne_kg - c.mangime_kg) / 1000) if pareggio else None,
        "resa_netta": eur(c.resa_netta_eur), "resa": eur(c.resa_eur), "siero": eur(c.siero_eur), "minimo": eur(c.minimo_eur),
        "giorni": n0(c.giorni), "saldo": eur(c.saldo_eur), "pagato": eur(c.pagato_eur), "anticipi": eur(c.anticipi_eur),
        "reale": _quanto_reale(st),
        # scenario
        "sce": sce, "standard": standard, "giacenza_iniziale": round(sit.giacenza_iniziale_kg),
        "peso_uscita": n1(st.peso_uscita_kg) if st.peso_uscita_kg else None, "capi_macello": n0(st.capi_macello),
        "carichi_testo": carichi_testo, "uscita_media": gm(oggi + timedelta(days=round(st.giorni_equivalenti))) if in_stalla else None,
        "resa_reale": S.resa_media(sit.carichi) is not None,
        # grafici
        "istogramma": _istogramma(sim),
        "per_peso": _per_peso(sit, sce, contratto, premi_noti) if in_stalla else [],
        "griglia": _griglia(sit, sce, contratto, premi_noti) if in_stalla else None,
        "leve": _leve(sit, sce, contratto),
        # elenchi
        "dati": _dati_da_aggiornare(ciclo, par, sit, sce, st, dettagli, contratto, url),
        "da_fare": _da_fare(ciclo, par, sit, dettagli),
        "righe": _righe_conto(st, sit, sce, par, contratto),
        "animali": _animali(ciclo, par, contratto),
        "siero_mensile": _siero_mensile(ciclo, dettagli),
        "cucina": {"bolle_q": sum(x.quantita_qli for x in ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).all()),
                   "cucina_q": D.consumo_cucina(ciclo, "siero_qli"),
                   "mangime_bolle_q": sit.mangime_bolle_kg / 100, "mangime_cucina_q": D.consumo_cucina(ciclo, "mangime_qli"),
                   "mangime_silos_q": sit.giacenza_oggi_kg / 100},
    }
