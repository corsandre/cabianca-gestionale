"""Elenco degli ingredienti per l'etichetta, generato dalla ricetta. Senza Flask, testato in
tests/test_prodotti_ingredienti.py.

Regole (Reg. UE 1169/2011):
- ingredienti in ordine di peso DECRESCENTE al momento dell'uso (art. 18);
- gli allergeni evidenziati in modo che si distinguano dal resto (art. 21): qui in MAIUSCOLO e grassetto,
  come nelle etichette attuali dei tortelli ("farina di **GRANO** tenero tipo 00").

Convenzione del testo salvato nel lotto (`lotti.ingredienti_testo`): il grassetto è segnato con
**doppi asterischi**. Lo trasforma in HTML `testo_html()` (anteprima ed etichetta). Il testo resta
modificabile a mano per ogni lotto.

Come si decide che cosa mettere in grassetto, per ogni ingrediente con allergeni:
- se nel nome in etichetta ci sono parole già scritte in MAIUSCOLO (es. "farina di GRANO tenero"),
  si evidenziano quelle: chi compila la materia prima sceglie la parola giusta;
- altrimenti si mette in maiuscolo e grassetto tutto il nome (es. "uova" → "**UOVA**").
Nel testo tra parentesi degli ingredienti composti (es. mostarda: "frutta, zucchero, essenza di SENAPE")
si evidenziano sempre le parole in maiuscolo; in quel caso il nome ("mostarda") resta normale, come
nelle etichette attuali.
"""
import html
import re

# Parola tutta maiuscola di almeno 2 lettere (anche accentate): GRANO, UOVA, SENAPE, LATTE
_MAIUSCOLA = re.compile(r"\b([A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ']+)\b")
# Sigle scritte in maiuscolo che NON sono allergeni (Grana Padano DOP, olio EVO, latte UHT...)
SIGLE_NON_ALLERGENI = {"DOP", "IGP", "IGT", "DOC", "DOCG", "STG", "EVO", "UHT", "CE", "UE", "BIO", "PAT", "IT"}


def _ha_maiuscole(testo):
    """C'è almeno una parola in MAIUSCOLO da evidenziare (sigle escluse)?"""
    return any(m.group(1) not in SIGLE_NON_ALLERGENI for m in _MAIUSCOLA.finditer(testo or ""))


def _evidenzia_maiuscole(testo):
    """Mette in **grassetto** le parole in MAIUSCOLO, tranne le sigle di SIGLE_NON_ALLERGENI."""
    return _MAIUSCOLA.sub(
        lambda m: m.group(1) if m.group(1) in SIGLE_NON_ALLERGENI else f"**{m.group(1)}**", testo)


# Conversione per confrontare i pesi: kg e l contano come 1000 g/ml. Pezzi (pz) e unità sconosciute
# restano come sono: chi le usa le mette nell'ordine voluto con il testo modificabile.
_FATTORI = {"g": 1, "ml": 1, "kg": 1000, "l": 1000, "cl": 10, "mg": 0.001}


def in_grammi(quantita, unita):
    try:
        q = float(quantita or 0)
    except (TypeError, ValueError):
        return 0.0
    return q * _FATTORI.get((unita or "g").strip().lower(), 1)


def voce_etichetta(nome_etichetta, allergeni=None, composta=None):
    """Un ingrediente come compare nell'elenco, con il grassetto sugli allergeni."""
    nome = (nome_etichetta or "").strip()
    composta_evidenziata = bool(composta and _ha_maiuscole(composta))
    if _ha_maiuscole(nome):
        nome = _evidenzia_maiuscole(nome)
    elif allergeni and not composta_evidenziata:
        # nessuna parola scelta né nel nome né tra i sotto-ingredienti: si evidenzia tutto il nome
        nome = f"**{nome.upper()}**"
    if composta and composta.strip():
        nome += f" ({_evidenzia_maiuscole(composta.strip())})"
    return nome


def testo_ingredienti(righe, prefisso="Ingredienti: "):
    """Testo dell'elenco ingredienti da una ricetta.

    `righe`: lista di dict con nome_etichetta, quantita, unita, allergeni (lista), composta.
    Lo stesso ingrediente presente più volte viene sommato. Restituisce "" se non ci sono righe.
    """
    totali, dati, primo = {}, {}, {}
    for i, r in enumerate(righe):
        chiave = (r.get("nome_etichetta") or "").strip().lower()
        if not chiave:
            continue
        totali[chiave] = totali.get(chiave, 0) + in_grammi(r.get("quantita"), r.get("unita"))
        dati.setdefault(chiave, r)
        primo.setdefault(chiave, i)
    if not totali:
        return ""
    # peso decrescente; a parità di peso resta l'ordine della ricetta
    ordinate = sorted(totali, key=lambda k: (-totali[k], primo[k]))
    voci = [voce_etichetta(dati[k].get("nome_etichetta"), dati[k].get("allergeni"), dati[k].get("composta"))
            for k in ordinate]
    return prefisso + ", ".join(voci) + "."


def allergeni_presenti(righe):
    """Insieme dei codici di allergeni delle righe della ricetta, nell'ordine ufficiale."""
    from .allergeni import pulisci
    tutti = []
    for r in righe:
        tutti.extend(r.get("allergeni") or [])
    return pulisci(tutti)


def percentuali(righe):
    """{nome_etichetta: percentuale sul totale} (per la scheda ricetta e per le indicazioni QUID)."""
    totali = {}
    for r in righe:
        n = (r.get("nome_etichetta") or "").strip()
        totali[n] = totali.get(n, 0) + in_grammi(r.get("quantita"), r.get("unita"))
    somma = sum(totali.values())
    return {n: (round(q * 100 / somma, 1) if somma else 0) for n, q in totali.items()}


def testo_html(testo):
    """Testo con **grassetto** → HTML sicuro (il resto viene sempre "escapato")."""
    sicuro = html.escape(testo or "")
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", sicuro)
