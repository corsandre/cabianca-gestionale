"""
Fatture del siero: lettura delle righe dal testo della fattura.

Solo analisi del testo, senza database e senza Flask (provata in tests/test_siero_fatture.py).
Il testo è quello di `pdftotext -layout` sulla copia PDF della fattura elettronica.

Le fatture di Nosari (TD24, una al mese) hanno, per ogni carico, due righe:

    DDT 8509 del 01-05-2026
    S.ZOOTEC. PAGLIOLI    S.ZOOTEC. PAGLIOLI      19,00     9,25    TN     10,00     175,75

cioè numero e data della bolla, poi tonnellate, prezzo, unità, IVA e importo. In fondo c'è
una riga «INDICIZZAZIONE GASOLIO» (unità NR) che vale per tutto il mese: qui è un «extra».
"""
import re

_DDT = re.compile(r"DDT\s+(\S+)\s+del\s+(\d\d)-(\d\d)-(\d{4})")
# descrizione, quantità, prezzo unitario, unità di misura, % IVA, importo
_RIGA = re.compile(r"^(.*?)\s{2,}([\d.]+,\d+)\s+([\d.]+,\d+)\s+([A-Z]{1,3})\s+([\d.]+,\d+)\s+([\d.]+,\d+)\s*$")
UNITA_CARICO = "TN"      # i carichi sono in tonnellate


def _numero(testo):
    return float(testo.replace(".", "").replace(",", "."))


def righe_da_testo(testo):
    """Ritorna (carichi, extra):
    carichi = [{"ddt", "data" (aaaa-mm-gg), "tonnellate", "prezzo", "importo"}], nell'ordine della fattura;
    extra   = [{"descrizione", "importo"}] per le righe che non sono un carico (indicizzazione gasolio)."""
    carichi, extra = [], []
    ddt = None
    for linea in testo.splitlines():
        m = _DDT.search(linea)
        if m:
            ddt = (m.group(1), f"{m.group(4)}-{m.group(3)}-{m.group(2)}")
            continue
        m = _RIGA.match(linea)
        if not m:
            continue
        descrizione = " ".join(m.group(1).split())
        if m.group(4) == UNITA_CARICO and ddt:
            carichi.append({"ddt": ddt[0], "data": ddt[1], "tonnellate": _numero(m.group(2)),
                            "prezzo": _numero(m.group(3)), "importo": _numero(m.group(6))})
            ddt = None
        else:
            extra.append({"descrizione": descrizione, "importo": _numero(m.group(6))})
    return carichi, extra


def importi_completi(carichi, extra, imponibile, totale):
    """Importo di ogni carico con la sua parte di extra e di IVA, in modo che la somma dia il totale
    della fattura: gli extra (gasolio) si ripartiscono in proporzione alle tonnellate, poi tutto si
    riporta dall'imponibile al totale con IVA. Ritorna la lista degli importi, uno per carico."""
    t_tot = sum(c["tonnellate"] for c in carichi)
    e_tot = sum(e["importo"] for e in extra)
    if not carichi or not t_tot:
        return []
    netti = [c["importo"] + e_tot * c["tonnellate"] / t_tot for c in carichi]
    base = imponibile or sum(netti)
    fattore = (totale / base) if totale and base else 1.0
    return [round(n * fattore, 2) for n in netti]
