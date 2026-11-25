"""Catalogo iniziale del modulo Prodotti dalle etichette storiche (Illustrator/PDF). Senza Flask.

Due passi, da lanciare a mano:

1. ESTRAI (in locale, dove ci sono le etichette):
       python3 scripts/importa_etichette.py estrai ~/Desktop/etichette/"Etichette prodotti" docs/import/catalogo-etichette.json
   Per ogni cartella prende l'etichetta più recente (PDF, altrimenti .ai che è un PDF), ne legge il testo
   con pdftotext e ricava nome, peso, ingredienti, conservazione, tracce. Scrive una BOZZA JSON da
   ricontrollare e correggere a mano (campo "salta": true per escludere un prodotto).

2. CARICA (dove c'è il database del modulo, anche in produzione dopo il rilascio):
       python3 scripts/importa_etichette.py carica docs/import/catalogo-etichette.json data/prodotti.db
       (in Docker: docker compose exec web python scripts/importa_etichette.py carica ... /app/data/prodotti.db)
   Crea i prodotti con «da ricontrollare» acceso e le materie prime trovate negli elenchi ingredienti
   (con gli allergeni riconosciuti dalle parole in MAIUSCOLO). Non crea ricette: le etichette non hanno
   le quantità. Si può rilanciare: salta i prodotti (stesso nome e peso) e le materie prime già presenti.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime

PESO = re.compile(r"(\d+(?:[.,]\d+)?)\s*(g|gr|ml|kg|l)\b", re.I)
DATA_NEL_NOME = re.compile(r"(\d{2})[-.]?(\d{2})[-.]?(20\d{2}|\d{2})")
FINE_SEZIONE = (r"Conservazione|Conservare|Prodotto da|Consumare|Da consumarsi|Lotto|Può contenere|Modalità|"
                r"Budello|Indirizzo|Lavorato da|www\.|Peso netto|Pref\. entro|Prodotto e confezionato")

# parola in MAIUSCOLO sull'etichetta → allergene (codici di app/moduli/prodotti/services/allergeni.py)
PAROLE_ALLERGENI = {
    "GRANO": "glutine", "FARRO": "glutine", "ORZO": "glutine", "SEGALE": "glutine", "AVENA": "glutine",
    "KAMUT": "glutine", "GLUTINE": "glutine", "UOVA": "uova", "UOVO": "uova", "LATTE": "latte",
    "BURRO": "latte", "FORMAGGIO": "latte", "SENAPE": "senape", "SEDANO": "sedano", "SOIA": "soia",
    "SESAMO": "sesamo", "PISTACCHI": "frutta_guscio", "PISTACCHIO": "frutta_guscio", "NOCI": "frutta_guscio",
    "NOCCIOLE": "frutta_guscio", "MANDORLE": "frutta_guscio", "ARACHIDI": "arachidi", "SOLFITI": "solfiti",
    "LUPINI": "lupini", "PESCE": "pesce", "CROSTACEI": "crostacei", "MOLLUSCHI": "molluschi",
}
# Le etichette vecchie spesso non scrivevano gli allergeni in maiuscolo: queste parole (minuscole) fanno
# PROPORRE l'allergene sulla materia prima, che resta comunque «da ricontrollare».
PAROLE_SUGGERITE = {
    "grano": "glutine", "farina": "glutine", "semola": "glutine", "saragolla": "glutine", "khorasan": "glutine",
    "frumento": "glutine", "farro": "glutine", "orzo": "glutine", "pane": "glutine", "pangrattato": "glutine",
    "uova": "uova", "uovo": "uova", "amaretti": "uova", "latte": "latte", "grana": "latte", "parmigiano": "latte",
    "gorgonzola": "latte", "ricotta": "latte", "formaggio": "latte", "burro": "latte", "panna": "latte",
    "mascarpone": "latte", "senape": "senape", "sedano": "sedano", "noci": "frutta_guscio",
    "nocciole": "frutta_guscio", "mandorle": "frutta_guscio", "pistacchi": "frutta_guscio", "soia": "soia",
    "sesamo": "sesamo", "vino": "solfiti",
}
# parole da scrivere in MAIUSCOLO nel nome in etichetta (così vanno in grassetto)
PAROLE_DA_EVIDENZIARE = ("grano", "uova", "uovo", "latte", "senape", "sedano", "noci", "nocciole", "mandorle",
                         "pistacchi", "soia", "sesamo")


# ---------------------------------------------------------------- estrai

def testo_pdf(percorso):
    r = subprocess.run(["pdftotext", "-q", percorso, "-"], capture_output=True, timeout=60)
    return r.stdout.decode("utf-8", errors="replace")


def piu_recente(cartella):
    """Etichetta più recente: data scritta nel nome del file se c'è, altrimenti data di modifica. PDF > .ai."""
    candidati = []
    for f in os.listdir(cartella):
        est = os.path.splitext(f)[1].lower()
        if est not in (".pdf", ".ai"):
            continue
        m = DATA_NEL_NOME.search(f)
        quando = None
        if m:
            g, mese, a = m.groups()
            a = int(a) + (2000 if len(a) == 2 else 0)
            try:
                quando = datetime(a, int(mese), int(g))
            except ValueError:
                quando = None
        quando = quando or datetime.fromtimestamp(os.path.getmtime(os.path.join(cartella, f)))
        candidati.append((quando, est == ".pdf", f))
    if not candidati:
        return None, None
    candidati.sort(reverse=True)
    return os.path.join(cartella, candidati[0][2]), candidati[0][0]


def fino_al_punto(testo):
    """Taglia al primo punto fuori dalle parentesi seguito da una maiuscola o dalla fine:
    'fichi e zucchero. Marmellata di fichi' → 'fichi e zucchero.' (sulle etichette vecchie il nome segue)."""
    livello = 0
    for i, ch in enumerate(testo):
        livello += ch == "("
        livello -= ch == ")" and livello > 0
        if ch == "." and livello == 0 and (i + 1 == len(testo) or re.match(r"\s+[A-ZÀ-Ý]", testo[i + 1:])):
            return testo[:i + 1]
    return testo


def senza_accenti(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")


def taglia_nome_prodotto(testo, nome_prodotto):
    """Sulle etichette vecchie dopo gli ingredienti segue il nome del prodotto, a volte senza punto:
    'meloni, zucchero e limone Marmellata di melone' → 'meloni, zucchero e limone'."""
    prima = senza_accenti((nome_prodotto or "").split()[0]) if nome_prodotto else ""
    if len(prima) < 4:
        return testo
    m = re.search(r"\s" + re.escape(prima[:1].upper() + prima[1:].lower()), senza_accenti(testo))
    return testo[:m.start()].rstrip(" ,") if m and m.start() > 0 else testo


def sezione(testo, inizio, taglia=False):
    """Testo dopo `inizio` fino alla sezione successiva (prima occorrenza: le etichette sono ripetute sul foglio)."""
    m = re.search(inizio + r"\s*:?\s*(.+?)(?=\b(?:" + FINE_SEZIONE + r")\b|$)", testo, re.S | re.I)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip(" :")
    if taglia:
        t = fino_al_punto(t)
    return t.rstrip(" .") + "." if t else ""


def pulisci_ingredienti(testo, nome_prodotto):
    testo = taglia_nome_prodotto(testo, nome_prodotto)
    testo = re.sub(r"\s*(\.\s*)?contiene glutine\.?", "", testo, flags=re.I)       # frase, non ingrediente
    testo = re.sub(r"\s+\d+\s*(ml|g)\b\.?$", "", testo)                           # "… 100 ml" in coda
    return testo.rstrip(" .,") + "." if testo.strip() else ""


def proponi_sigla(nome):
    """Come app/moduli/prodotti/services/lotti.proponi_sigla: Marmellata di fichi → MFI, Cacciatorino → CAC."""
    vuote = {"di", "del", "della", "delle", "dei", "e", "al", "alla", "allo", "con", "in", "da", "a", "il", "la"}
    parole = [p for p in re.findall(r"[A-Za-zÀ-ÿ]+", nome or "") if p.lower() not in vuote]
    if not parole:
        return "PRD"
    sigla = parole[0][:3] if len(parole) == 1 else parole[0][0] + parole[1][:2]
    return re.sub(r"[^A-Z0-9]", "", senza_accenti(sigla).upper())[:8] or "PRD"


def estrai(cartella_etichette, file_bozza):
    bozza = []
    for nome_cartella in sorted(os.listdir(cartella_etichette)):
        cartella = os.path.join(cartella_etichette, nome_cartella)
        if not os.path.isdir(cartella) or nome_cartella.upper().startswith(("ETICHETTE RICICLAGGIO", "NEW FOLDER")):
            continue
        file_et, quando = piu_recente(cartella)
        testo = testo_pdf(file_et) if file_et else ""
        m = PESO.search(nome_cartella) or PESO.search(testo)
        peso, unita = (float(m.group(1).replace(",", ".")), m.group(2).lower().replace("gr", "g")) if m else (None, "g")
        nome = re.sub(r"\s+", " ", PESO.sub("", nome_cartella)).strip(" -")
        nome = re.sub(r"\s*-?\s*Copy$", "", nome, flags=re.I)
        voce = {
            "cartella": nome_cartella, "file": os.path.basename(file_et) if file_et else None,
            "data_etichetta": quando.strftime("%Y-%m-%d") if quando else None,
            "nome": nome[:1].upper() + nome[1:], "peso_netto": peso, "unita": "ml" if unita in ("ml", "l") else "g",
            "ingredienti": pulisci_ingredienti(sezione(testo, r"Ingredienti", taglia=True), nome),
            "conservazione": sezione(testo, r"Conservazione") or sezione(testo, r"(?=Conservare)"),
            "modalita_uso": sezione(testo, r"Modalità d'uso"),
            "tracce": sezione(testo, r"Può contenere tracce di"),
            "lavorato_da": sezione(testo, r"Lavorato da"),
            "salta": file_et is None,
        }
        bozza.append(voce)
        print(f"{'—' if voce['salta'] else '✓'} {voce['nome']:<45} {voce['peso_netto'] or '':>6} "
              f"{(voce['ingredienti'] or '(ingredienti non trovati)')[:60]}")
    os.makedirs(os.path.dirname(os.path.abspath(file_bozza)), exist_ok=True)
    with open(file_bozza, "w", encoding="utf-8") as f:
        json.dump({"creata": datetime.now().isoformat(timespec="seconds"), "fonte": cartella_etichette,
                   "nota": "Bozza da ricontrollare. Correggere i campi o mettere \"salta\": true.",
                   "prodotti": bozza}, f, ensure_ascii=False, indent=1)
    print(f"\n{len(bozza)} cartelle → {file_bozza}")


# ---------------------------------------------------------------- carica

def separa_ingredienti(testo):
    """'a, b (c, d), e.' → [('a', ''), ('b', 'c, d'), ('e', '')] rispettando le parentesi."""
    testo = re.sub(r"^\s*Ingredienti\s*:\s*", "", testo or "", flags=re.I).strip().rstrip(".")
    parti, livello, corrente = [], 0, ""
    for ch in testo:
        if ch == "(":
            livello += 1
        elif ch == ")":
            livello = max(0, livello - 1)
        if ch in ",;." and livello == 0:
            parti.append(corrente)
            corrente = ""
        else:
            corrente += ch
    parti.append(corrente)
    out = []
    for p in parti:
        p = re.sub(r"\s+", " ", p).strip(" .")
        # "fichi freschi e zucchero" → due ingredienti
        for q in re.split(r"\s+e\s+(?![^()]*\))", p) if "(" not in p and len(p.split()) <= 6 else [p]:
            m = re.match(r"^(.*?)\s*\((.*)\)\s*$", q)
            nome, composta = (m.group(1), m.group(2)) if m else (q, "")
            if nome:
                out.append((nome.strip(), composta.strip()))
    return out


def allergeni_di(*testi):
    """Allergeni dalle parole in MAIUSCOLO (certi) e da quelle di PAROLE_SUGGERITE (proposti)."""
    trovati = set()
    for t in testi:
        for parola in re.findall(r"\b[A-ZÀ-Ý]{3,}\b", t or ""):
            if parola in PAROLE_ALLERGENI:
                trovati.add(PAROLE_ALLERGENI[parola])
        for parola in re.findall(r"[a-zà-ÿ]+", (t or "").lower()):
            if parola in PAROLE_SUGGERITE:
                trovati.add(PAROLE_SUGGERITE[parola])
    return sorted(trovati)


def evidenzia(nome):
    """'farina di grano tenero' → 'farina di GRANO tenero' (le parole allergene in maiuscolo)."""
    return re.sub(r"\b(" + "|".join(PAROLE_DA_EVIDENZIARE) + r")\b", lambda m: m.group(1).upper(), nome, flags=re.I)


def carica(file_bozza, percorso_db):
    with open(file_bozza, encoding="utf-8") as f:
        bozza = json.load(f)
    con = sqlite3.connect(percorso_db)
    con.execute("PRAGMA busy_timeout=10000")
    if not con.execute("SELECT name FROM sqlite_master WHERE name='prodotti'").fetchone():
        sys.exit("Il database non ha le tabelle del modulo Prodotti: avviare prima il gestionale (migrazioni).")
    produttore = (con.execute("SELECT valore FROM impostazioni WHERE chiave='produttore'").fetchone() or [None])[0]
    nuovi_p = nuove_m = 0
    for v in bozza["prodotti"]:
        if v.get("salta"):
            continue
        esiste = con.execute("SELECT id FROM prodotti WHERE lower(nome)=lower(?) AND coalesce(peso_netto,0)=coalesce(?,0)",
                             (v["nome"], v.get("peso_netto"))).fetchone()
        if not esiste:
            sigla = v.get("sigla") or proponi_sigla(v["nome"])
            # sigle uniche: due prodotti con la stessa sigla avrebbero codici lotto che si confondono
            base, n = sigla, 2
            while con.execute("SELECT 1 FROM prodotti WHERE sigla=?", (sigla,)).fetchone():
                sigla, n = f"{base}{n}", n + 1
            note = "Importato dalle etichette storiche"
            if v.get("data_etichetta"):
                note += f" (ultima etichetta del {v['data_etichetta']}, file {v.get('file')})"
            if v.get("ingredienti"):
                note += f". Ingredienti sull'etichetta vecchia: {v['ingredienti']}"
            con.execute(
                "INSERT INTO prodotti (nome, sigla, peso_netto, unita, conservazione, modalita_uso, tracce, lavorato_da, "
                "prodotto_da, da_verificare, note) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (v["nome"], sigla, v.get("peso_netto"), v.get("unita") or "g", v.get("conservazione") or None,
                 v.get("modalita_uso") or None, v.get("tracce") or None, v.get("lavorato_da") or None,
                 produttore, note))
            nuovi_p += 1
        for nome, composta in separa_ingredienti(v.get("ingredienti")):
            nome = re.sub(r"\s*:\s*", " ", nome).strip()                     # "Conservante: E252" = "Conservante E252"
            if not re.search(r"[a-zà-ÿ]", nome, re.I):
                continue
            interno = nome[:1].upper() + nome[1:]
            if con.execute("SELECT 1 FROM materie_prime WHERE lower(nome)=lower(?)", (interno,)).fetchone():
                continue
            allerg = allergeni_di(nome, composta)
            etichetta = nome.lower() if nome == nome.upper() else nome[:1].lower() + nome[1:]
            con.execute("INSERT INTO materie_prime (nome, nome_etichetta, allergeni, composta, note) VALUES (?,?,?,?,?)",
                        (interno, evidenzia(etichetta), json.dumps(allerg), evidenzia(composta) or None,
                         "Importata dalle etichette storiche: controllare allergeni (proposti) e fornitore"))
            nuove_m += 1
    con.commit()
    con.close()
    print(f"Caricati {nuovi_p} prodotti e {nuove_m} materie prime (tutti «da ricontrollare»).")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "estrai":
        estrai(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "carica":
        carica(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        sys.exit(2)
