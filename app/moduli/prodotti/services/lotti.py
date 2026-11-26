"""Calcoli del lotto: codice, scadenza, quantità scalate dalla ricetta. Senza Flask, testato in
tests/test_prodotti_lotti.py.

Codice lotto deciso con Andrea il 24/11/2026: "L" + data di produzione GGMMAA + "-" + sigla del
prodotto, es. L241126-ZUC (tortelli di zucca prodotti il 24/11/2026). Se nello stesso giorno lo
stesso prodotto ha già un lotto, si aggiunge un numero: L241126-ZUC-2, -3, ...
Il gestionale lo propone; chi crea il lotto può cambiarlo.
"""
import re
from datetime import date, timedelta


def pulisci_sigla(sigla):
    """Solo lettere e cifre maiuscole (max 8): la sigla finisce nel codice stampato in etichetta."""
    return re.sub(r"[^A-Z0-9]", "", (sigla or "").upper())[:8]


def proponi_sigla(nome):
    """Sigla di 3 lettere dal nome, saltando le parole vuote ("di", "e", "al"...): iniziale della prima
    parola significativa + prime due lettere della seconda, oppure le prime 3 lettere se è una sola.
    Es. "Confettura di fichi" → CFI, "Passata" → PAS, "Tortelli di zucca" → TZU.
    È solo una proposta modificabile."""
    vuote = {"di", "del", "della", "delle", "dei", "e", "al", "alla", "allo", "con", "in", "da", "a", "il", "la"}
    parole = [p for p in re.findall(r"[A-Za-zÀ-ÿ]+", nome or "") if p.lower() not in vuote]
    if not parole:
        return ""
    if len(parole) == 1:
        return pulisci_sigla(parole[0][:3])
    return pulisci_sigla(parole[0][0] + parole[1][:2])


def codice_lotto(data_produzione, sigla, esistenti=()):
    """L + GGMMAA + -SIGLA, con -2, -3... se il codice è già usato (`esistenti`: codici già nel libro)."""
    base = f"L{data_produzione:%d%m%y}-{pulisci_sigla(sigla)}"
    usati = {c.upper() for c in esistenti}
    if base.upper() not in usati:
        return base
    n = 2
    while f"{base}-{n}".upper() in usati:
        n += 1
    return f"{base}-{n}"


def data_scadenza(data_produzione, durata_giorni):
    """Scadenza proposta (None se la durata non è impostata)."""
    if not durata_giorni:
        return None
    return data_produzione + timedelta(days=int(durata_giorni))


def fattore_scala(resa_pezzi, pezzi):
    """Per quanto moltiplicare le quantità della ricetta per fare `pezzi` pezzi (1 se mancano i dati)."""
    try:
        if resa_pezzi and pezzi and float(resa_pezzi) > 0:
            return float(pezzi) / float(resa_pezzi)
    except (TypeError, ValueError):
        pass
    return 1.0


def fattore_ricetta(resa_kg, resa_pezzi, kg, pezzi):
    """Fattore per un lotto con più contenitori: dai kg totali se la ricetta ha la resa in kg (e i contenitori
    hanno un peso), altrimenti dai pezzi totali sulla resa in pezzi; 1 se mancano i dati."""
    try:
        if resa_kg and kg and float(resa_kg) > 0:
            return float(kg) / float(resa_kg)
    except (TypeError, ValueError):
        pass
    return fattore_scala(resa_pezzi, pezzi)


def arrotonda_quantita(q):
    """Quantità leggibile: interi sopra 100, una decimale sotto (500.0 → 500, 12.345 → 12.3)."""
    if q is None:
        return None
    q = float(q)
    return round(q) if abs(q) >= 100 else round(q, 1)


def da_iso(testo):
    """'2026-11-24' → date (None se vuoto o non valido)."""
    try:
        return date.fromisoformat((testo or "")[:10])
    except ValueError:
        return None
