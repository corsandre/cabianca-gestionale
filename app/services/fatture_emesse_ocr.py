"""Lettura OCR delle copie PDF delle fatture emesse.

Le copie arrivano dalla Coldiretti (programma GAMMA): il PDF non contiene testo vero
(i caratteri sono disegni), quindi ogni pagina viene trasformata in immagine
(pdftoppm) e letta con tesseract in italiano. Dal testo si ricavano i campi del modulo:
numero e data documento, cliente, totali, eventuale fattura stornata dalla nota di credito.

Funzioni pure (nessun accesso al database) per poterle provare da sole.
"""

import os
import re
import subprocess
import tempfile
from datetime import date, datetime

MAX_PAGINE = 3          # i PDF più lunghi sono registri o elenchi, non fatture
DPI = 200

_INDIRIZZO = re.compile(r"(VIA|V\.LE|VIALE|PIAZZA|P\.ZA|P\.ZZA|STRADA|LOC\.?|LOCALITA'?|C\.SO|CORSO|FRAZ\.?|CASCINA|\d{5})\b")
_CF = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b")
_INTESTAZIONE = ("FATTORIA CA' BIANCA SOCIETA' AGRICOLA SO", "CIETA' SEMPLICE")


def numero_pagine(pdf: bytes) -> int:
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(pdf)
        f.flush()
        r = subprocess.run(["pdfinfo", f.name], capture_output=True, text=True, timeout=30)
    m = re.search(r"Pages:\s+(\d+)", r.stdout)
    return int(m.group(1)) if m else 0


def testo_pagine(pdf: bytes) -> list[str]:
    """OCR di ogni pagina del PDF. Ritorna un testo per pagina."""
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "f.pdf")
        with open(src, "wb") as f:
            f.write(pdf)
        subprocess.run(["pdftoppm", "-r", str(DPI), "-gray", "-png", src, os.path.join(tmp, "p")],
                       capture_output=True, timeout=120)
        pagine = sorted(n for n in os.listdir(tmp) if n.startswith("p") and n.endswith(".png"))
        testi = []
        for nome in pagine:
            r = subprocess.run(["tesseract", os.path.join(tmp, nome), "-", "--psm", "6", "-l", "ita"],
                               capture_output=True, text=True, timeout=120, env=env)
            testi.append(r.stdout)
        return testi


def _importo(s):
    s = (s or "").replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _data(s):
    for fmt in ("%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            pass
    return None


def e_fattura(testo: str) -> bool:
    return "NUMERO DOCUMENTO" in testo and "SPETT" in testo and "TOTALE DOCUMENTO" in testo


def emessa_da_ca_bianca(testo: str) -> bool:
    """Nelle stesse email arrivano anche fatture di altre aziende seguite dalla Coldiretti
    (es. Paglioli Maria): l'intestazione in alto a sinistra deve essere Fattoria Ca' Bianca."""
    righe = [r for r in testo.splitlines() if r.strip()][:4]
    return any(r.startswith(_INTESTAZIONE[0]) for r in righe)


def leggi_fattura(testo: str) -> dict | None:
    """Ricava i campi da una pagina di fattura. None se la pagina non è una fattura."""
    if not e_fattura(testo):
        return None
    righe = [r for r in testo.splitlines() if r.strip()]
    f = {"numero": None, "data": None, "cliente": "", "cliente_partita_iva": "",
         "cliente_codice_fiscale": "", "imponibile": None, "iva": None, "totale": None,
         "descrizione": "", "tipo": "fattura", "storna_numero": None, "storna_data": None}

    for i, r in enumerate(righe):
        succ = righe[i + 1] if i + 1 < len(righe) else ""
        if "NUMERO DOCUMENTO" in r and f["numero"] is None:
            m = re.search(r"(\d+(?:/\d+)?)\s+(\d{2}/\d{2}/\d{4})\s+\S+\s*$", succ)
            if m:
                f["numero"], f["data"] = m.group(1), _data(m.group(2))
            m = re.search(r"\b(\d{11})\b", succ)
            if m:
                f["cliente_partita_iva"] = m.group(1)
        elif "TOTALE A PAGARE" in r and f["totale"] is None:
            m = re.search(r"^\s*([\d\.\, ]+?)\s+TOT\s+([\d\.\, ]+?)\s+EUR\s+([\d\.\, ]+?)\s+EUR\s+([\d\.\, ]+\d)", succ)
            if m:
                f["imponibile"], f["iva"] = _importo(m.group(1)), _importo(m.group(2))
                f["totale"] = _importo(m.group(4))
            else:
                euro = re.findall(r"EUR\s+([\d\.\, ]+\d)", succ)
                if euro:
                    f["totale"] = _importo(euro[-1])
        elif "TIPO DOCUMENTO" in r and not f["descrizione"]:
            for r2 in righe[i + 1:i + 3]:
                m = re.match(r"\s*[\(\|]?\d{3,4}\s+(.+?)(?:\s+(?:PZ|NR|KG|INR|HA|N\.)\s|\s{2,}|$)", r2)
                if m:
                    f["descrizione"] = m.group(1).strip()[:300]
                    break

    # Cliente: colonna destra delle righe d'intestazione (a sinistra c'è Ca Bianca)
    nome = []
    for r in righe[1:4]:
        for pre in _INTESTAZIONE:
            if r.startswith(pre):
                resto = r[len(pre):].strip()
                if not resto:
                    continue
                if _INDIRIZZO.match(resto):
                    break
                nome.append(resto)
    f["cliente"] = " ".join(nome)[:200]

    cf = [c for c in _CF.findall(testo)]
    if cf:
        f["cliente_codice_fiscale"] = cf[0]

    piatto = " ".join(righe)
    if "NOTA DI CREDITO" in piatto.upper():
        f["tipo"] = "nota_credito"
        m = re.search(r"(?:FT\.?|FATTURA)(?:\s*NR\.?)?[^/]{0,60}?\b(\d+(?:/\d+)?)\s+DEL\s+(\d\d[./]\d\d[./]\d{4})",
                      piatto, re.IGNORECASE)
        if m:
            f["storna_numero"] = m.group(1)
            f["storna_data"] = _data(m.group(2).replace(".", "/"))
    return f


def problemi(f: dict) -> list[str]:
    """Controlli di coerenza sui campi letti: se ce n'è uno, la fattura va verificata a mano."""
    out = []
    if not f.get("numero"):
        out.append("numero non letto")
    d = f.get("data")
    if not d:
        out.append("data non letta")
    elif not (2020 <= d.year <= date.today().year + 1):
        out.append("data non plausibile")
    if not f.get("totale"):
        out.append("totale non letto")
    elif f.get("imponibile") is not None and f.get("iva") is not None:
        if abs(f["imponibile"] + f["iva"] - f["totale"]) > 0.05:
            out.append("imponibile + IVA diverso dal totale (IVA da controllare)")
    if not f.get("cliente"):
        out.append("cliente non letto")
    if f.get("tipo") == "nota_credito" and not f.get("storna_numero"):
        out.append("nota di credito senza fattura stornata")
    return out


def sezionale(numero: str) -> tuple[str, int | None]:
    """'43/01' -> ('01', 43); '8' -> ('', 8)."""
    m = re.match(r"(\d+)(?:/(\d+))?$", numero or "")
    if not m:
        return "", None
    return m.group(2) or "", int(m.group(1))


def leggi_pdf(pdf: bytes) -> tuple[list[dict], str]:
    """Tutte le fatture contenute nel PDF (di solito una) e il testo OCR completo."""
    n = numero_pagine(pdf)
    if n == 0 or n > MAX_PAGINE:
        return [], ""
    testi = testo_pagine(pdf)
    fatture = {}
    for t in testi:
        f = leggi_fattura(t)
        if not f or not f["numero"] or not emessa_da_ca_bianca(t):
            continue
        f["ocr_testo"] = t
        chiave = (f["numero"], f["data"])
        if chiave in fatture:
            # fattura su più pagine: i totali sono sull'ultima
            prima = fatture[chiave]
            for k, v in f.items():
                if v and not prima.get(k):
                    prima[k] = v
            prima["ocr_testo"] += "\n" + t
        else:
            fatture[chiave] = f
    return list(fatture.values()), "\n=====\n".join(testi)
