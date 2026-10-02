"""Lettura dello schermo di EM2000 (Gui2000, "SITUAZIONE IMPIANTO ALIMENTAZIONE", 800x600).

Lo schermo usa font bitmap: ogni carattere è disegnato sempre con gli stessi pixel. Invece di un OCR
che "indovina", si separa il testo dallo sfondo, si dividono i caratteri sulle colonne vuote e si
confronta ogni carattere con un campionario esatto (campionario.json, costruito da schermate note
con scripts/em2000_addestra.py). Un carattere mai visto diventa "?" e la lettura è scartata: meglio
nessun dato che un dato sbagliato.

Nelle righe di stato il grassetto fa toccare alcune lettere ("ZZ", "LA"): lì si riconosce la frase
intera (l'impianto usa un elenco fisso di frasi). Una frase mai vista = fase SCONOSCIUTA.
"""
import collections
import json
import os
import struct
from datetime import time

from PIL import Image

from ..base import (LetturaSchermo, ATTESA_ORARIO, ATTESA_INIZIO, PREPARAZIONE, STABILIZZAZIONE,
                    MISCELAZIONE, RIEMPIMENTO, DISTRIBUZIONE, LAVAGGIO, ATTESA_SVUOTAMENTO,
                    SVUOTAMENTO, SCONOSCIUTA)

CAMPIONARIO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "campionario.json")

# zone dello schermo (x0, y0, x1, y1), per la risoluzione 800x600 di EM2000
ZONE = {
    "ora_pc": (14, 35, 146, 70),
    "pasto_attuale": (205, 52, 257, 74),
    "prossimo_pasto": (205, 99, 257, 121),
    "linea": (16, 110, 183, 125),
    "stato1": (285, 32, 572, 50),
    "stato2": (285, 56, 572, 74),
}
# tabella della ricetta: righe da 25 pixel; il numero di righe cambia (es. una riga "SOS COCLEA 3" in
# più quando un silos finisce durante il dosaggio), quindi le righe si riconoscono dal nome
COLONNE = {"nr": (285, 315), "nome": (317, 428), "teorico": (431, 501), "reale": (504, 556)}
TABELLA_Y, TABELLA_PASSO, TABELLA_RIGHE = 256, 25, 10


def riga_tabella(i):
    """(y0, y1) della riga i della tabella (0 = prima riga sotto l'intestazione)."""
    y = TABELLA_Y + TABELLA_PASSO * i
    return y + 2, y + 21

FASI = {
    "ATTESA": ATTESA_ORARIO,
    "ATTESA INIZIO CICLO": ATTESA_INIZIO,
    "PREPARAZIONE RICETTA": PREPARAZIONE,
    "STABILIZZAZIONE": STABILIZZAZIONE,
    "MISCELAZIONE": MISCELAZIONE,
    "RIEMPIMENTO TUBO": RIEMPIMENTO,
    "DOSAGGIO ACQUA LAVAGGIO": LAVAGGIO,
    "STABILIZZAZIONE ACQUA LAVAGGIO": LAVAGGIO,
    "ATTESA SVUOTAMENTO": ATTESA_SVUOTAMENTO,
    "ATTESA VASCA VUOTA": ATTESA_SVUOTAMENTO,
    "SVUOTAMENTO": SVUOTAMENTO,
    "SVUOTA BILANCIA": SVUOTAMENTO,
}
# frasi seguite dal numero del box che sta ricevendo la razione o l'acqua di lavaggio
PREFISSI_BOX = {"DISTRIBUZIONE BOX NR.": DISTRIBUZIONE, "LAVAGGIO BOX NR.": LAVAGGIO}


def decodifica_xwd(dati):
    """Immagine PIL da una fotografia dello schermo in formato XWD (output di `xwd -root`)."""
    h = struct.unpack(">25I", dati[:100])
    header_size, larghezza, altezza = h[0], h[4], h[5]
    byte_order, bpp, bpl, ncolori = h[7], h[11], h[12], h[19]
    if bpp != 32:
        raise ValueError(f"profondità colore non gestita: {bpp} bit")
    inizio = header_size + ncolori * 12
    raw = dati[inizio:inizio + bpl * altezza]
    return Image.frombuffer("RGB", (larghezza, altezza), raw, "raw",
                            "BGRX" if byte_order == 0 else "XRGB", bpl, 1)


# ── glifi ──────────────────────────────────────────────────────────────────
def _maschera(cella):
    """Pixel di testo = colore lontano dallo sfondo (il colore più frequente della cella).
    Esclude il bordo di 1 pixel: sulla riga selezionata c'è il tratteggio del focus."""
    px = list(cella.getdata())
    sfondo = collections.Counter(px).most_common(1)[0][0]
    w, h = cella.size
    m = [[sum(abs(a - b) for a, b in zip(px[y * w + x], sfondo)) > 160 for x in range(w)] for y in range(h)]
    return [riga[1:-1] for riga in m[1:-1]]


def glifi(cella):
    """[(colonne vuote prima, glifo)]: glifo = tuple di colonne, senza righe vuote sopra/sotto."""
    m = _maschera(cella)
    if not m or not m[0]:
        return []
    h, w = len(m), len(m[0])
    out, cur, gap = [], [], 0
    for x in range(w):
        col = tuple(m[y][x] for y in range(h))
        if not any(col):
            if cur:
                out.append((gap, cur)); cur = []; gap = 0
            gap += 1
        else:
            cur.append(col)
    if cur:
        out.append((gap, cur))
    norm = []
    for gap, g in out:
        righe = [any(col[y] for col in g) for y in range(h)]
        y0, y1 = righe.index(True), h - righe[::-1].index(True)
        norm.append((gap, tuple(tuple(col[y0:y1]) for col in g)))
    return norm


def chiave(glifo):
    return "|".join("".join("1" if p else "0" for p in col) for col in glifo)


class Campionario:
    """Caratteri e frasi noti. Si carica da campionario.json; l'addestramento lo aggiorna."""

    def __init__(self, percorso=CAMPIONARIO):
        self.percorso = percorso
        d = json.load(open(percorso)) if os.path.exists(percorso) else {}
        self.caratteri = d.get("caratteri", {})
        self.frasi = d.get("frasi", {})

    def salva(self):
        json.dump({"caratteri": self.caratteri, "frasi": self.frasi}, open(self.percorso, "w"), sort_keys=True)

    def impara_testo(self, cella, testo):
        """Associa i glifi ai caratteri di un testo noto (spazi esclusi). False se non allineati."""
        gs = glifi(cella)
        car = [c for c in testo if c != " "]
        if len(gs) != len(car):
            return False
        for (_, g), c in zip(gs, car):
            self.caratteri[chiave(g)] = c
        return True

    def impara_frase(self, cella, frase):
        self.frasi["/".join(chiave(g) for _, g in glifi(cella))] = frase

    def testo(self, cella, spazi=True):
        out = ""
        for gap, g in glifi(cella):
            if spazi and out and gap >= 4:   # tra caratteri 1-3 colonne vuote, uno spazio ne ha 4 o più
                out += " "
            out += self.caratteri.get(chiave(g), "?")
        return out

    def frase(self, cella):
        """Frase di stato: corrispondenza esatta, oppure prefisso noto (es. DISTRIBUZIONE BOX NR. 14)."""
        chiavi = [chiave(g) for _, g in glifi(cella)]
        if not chiavi:
            return ""
        esatta = self.frasi.get("/".join(chiavi))
        if esatta:
            return esatta
        for k, frase in self.frasi.items():
            pref = k.split("/")
            if frase in PREFISSI_BOX and chiavi[:len(pref)] == pref:
                resto = "".join(self.caratteri.get(c, "?") for c in chiavi[len(pref):])
                return f"{frase} {resto}".strip()
        return None


# ── interpretazione ─────────────────────────────────────────────────────────
def _quintali(testo):
    """'4,35 Qli' → 4.35; '86 Kg' → 0.86; None se illeggibile."""
    parti = (testo or "").split()
    if not parti or "?" in parti[0]:
        return None
    try:
        v = float(parti[0].replace(",", "."))
    except ValueError:
        return None
    unita = parti[1].lower() if len(parti) > 1 else ""
    if unita.startswith("k"):
        return v / 100
    return v if unita.startswith("q") else None


def _orario(testo):
    t = (testo or "").replace(" ", "").replace(".", ":")
    try:
        p = [int(x) for x in t.split(":")]
        return time(*p[:3])
    except (ValueError, TypeError):
        return None


def leggi(img, camp=None):
    """LetturaSchermo da un'immagine dello schermo di EM2000."""
    camp = camp or Campionario()
    z = {k: img.crop(v) for k, v in ZONE.items()}
    l = LetturaSchermo(
        ora_pc=_orario(camp.testo(z["ora_pc"], spazi=False)),
        pasto_attuale=_orario(camp.testo(z["pasto_attuale"], spazi=False)),
        prossimo_pasto=_orario(camp.testo(z["prossimo_pasto"], spazi=False)),
    )
    lin = camp.testo(z["linea"])                      # "L1 G1"
    if lin.startswith("L") and lin[1:2].isdigit():
        l.linea = int(lin[1])
    s1, s2 = camp.frase(z["stato1"]), camp.frase(z["stato2"])
    l.stato = " / ".join(x for x in (s1, s2) if x) if (s1 or s2) else None
    if s2 is None or s1 is None:
        l.fase = SCONOSCIUTA
    elif any(s2.startswith(p) for p in PREFISSI_BOX):
        prefisso = next(p for p in PREFISSI_BOX if s2.startswith(p))
        l.fase = PREFISSI_BOX[prefisso]
        num = s2[len(prefisso):].strip()
        l.box_in_distribuzione = int(num) if num.isdigit() else None
    elif s2 == "ATTESA" and s1 != "ATTESA ORARIO":
        l.fase = SCONOSCIUTA
    else:
        l.fase = FASI.get(s2, SCONOSCIUTA)
    _leggi_tabella(img, camp, l)
    return l


def _nome(testo):
    # nel carattere della tabella "I" e "l" sono lo stesso glifo, imparato come "l" (da "Qli")
    return testo.replace("l", "I")


def _leggi_tabella(img, camp, l):
    """Righe della ricetta fino a TOTALI RICETTA: acqua, siero, coclee (farina = somma delle coclee).
    Le righe "SOS" sostituiscono la riga normale sopra di loro finita durante il dosaggio: il loro
    teorico è la parte mancante, quindi il teorico di un componente conta solo le righe normali, il
    reale tutte le righe di quel materiale. Le righe sotto (lavaggio) non interessano. Coerente se la
    somma dei componenti fa il totale (valori in quintali o in kg, che EM2000 usa per i numeri piccoli)."""
    totale = None
    for i in range(TABELLA_RIGHE):
        y0, y1 = riga_tabella(i)
        t = {col: camp.testo(img.crop((x0, y0, x1, y1))) for col, (x0, x1) in COLONNE.items()}
        nome = _nome(t["nome"])
        if not nome:
            continue                                  # riga vuota o di trattini
        te, re = _quintali(t["teorico"]), _quintali(t["reale"])
        if nome == "TOTALI RICETTA":
            totale = (te, re)
            break
        coclea = None
        if nome.startswith("ACQUA"):
            comp = "acqua"
        elif nome == "SIERO":
            comp = "siero"
        elif nome.startswith("COCLEA ") and nome[7:].isdigit():
            comp, coclea = "farina", int(nome[7:])
        else:
            l.righe_sconosciute.append(nome)
            continue
        l.righe.append({"comp": comp, "coclea": coclea, "sos": _nome(t["nr"]) == "SOS", "teorico": te, "reale": re})
    for comp in ("acqua", "siero", "farina"):
        righe = [r for r in l.righe if r["comp"] == comp]
        normali = [r for r in righe if not r["sos"]]
        l.reale[comp] = None if not righe or any(r["reale"] is None for r in righe) else round(sum(r["reale"] for r in righe), 4)
        l.teorico[comp] = None if not normali or any(r["teorico"] is None for r in normali) else round(sum(r["teorico"] for r in normali), 4)
    if totale:
        l.teorico["totale"], l.reale["totale"] = totale
    re = l.reale
    l.tabella_coerente = (
        totale is not None and not l.righe_sconosciute and bool(l.righe)
        and all(r["reale"] is not None for r in l.righe)
        and all(re.get(c) is not None for c in ("acqua", "siero", "farina", "totale"))
        and abs(sum(r["reale"] for r in l.righe) - re["totale"]) <= 0.011
    )
