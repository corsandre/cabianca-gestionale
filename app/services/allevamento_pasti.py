"""
Registrazione uso pasti (mangime/siero/acqua) con gestione dei valori stimati.

Il dato reale viene di norma rilevato al primo pasto (mattina). I pasti
successivi, se non compilati manualmente, ereditano i valori del primo pasto
e vengono marcati come "stimato" finché non arriva un inserimento manuale.

Tipo mangime e % sostanza secca del siero non si chiedono all'utente: si
prendono dall'ultima consegna registrata per ciascun ingrediente. La %
sostituzione in ricetta si ricava di conseguenza dai quantitativi di
mangime/siero inseriti per quel pasto/linea, non è un dato manuale.
"""
from app import db
from app.models import UsoPasto, ConsegnaMangime, ConsegnaSiero

PASTI_SUCCESSIVI = [2, 3]


def ultimo_tipo_mangime(ciclo_id):
    c = ConsegnaMangime.query.filter_by(ciclo_id=ciclo_id).order_by(
        ConsegnaMangime.data.desc(), ConsegnaMangime.id.desc()
    ).first()
    return c.tipo_mangime if c else None


def ultima_perc_sostanza_secca_siero(ciclo_id):
    c = ConsegnaSiero.query.filter(
        ConsegnaSiero.ciclo_id == ciclo_id, ConsegnaSiero.perc_sostanza_secca.isnot(None)
    ).order_by(ConsegnaSiero.data.desc(), ConsegnaSiero.id.desc()).first()
    return c.perc_sostanza_secca if c else None


def calcola_perc_siero(mangime_qli, siero_qli, perc_ss_siero):
    """% sostituzione s.s. in ricetta = sostanza secca apportata dal siero
    rispetto al totale (mangime, trattato come ~100% s.s. non avendo un dato
    di umidità del mangime, + sostanza secca del siero)."""
    if perc_ss_siero is None:
        return None
    if mangime_qli is None and siero_qli is None:
        return None
    mangime = mangime_qli or 0
    ss_siero = (siero_qli or 0) * (perc_ss_siero / 100)
    denom = mangime + ss_siero
    if denom <= 0:
        return None
    return round(ss_siero / denom * 100, 1)


def registra_pasto(ciclo_id, data, pasto, linea, mangime_qli=None, siero_qli=None, acqua_litri=None):
    """Salva un inserimento manuale per (data, pasto, linea) e, se pasto è il
    primo della giornata, aggiorna i pasti successivi ancora "stimati"."""
    tipo_mangime = ultimo_tipo_mangime(ciclo_id)
    perc_ss_siero = ultima_perc_sostanza_secca_siero(ciclo_id)
    perc_siero = calcola_perc_siero(mangime_qli, siero_qli, perc_ss_siero)

    riga = UsoPasto.query.filter_by(ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea).first()
    if riga:
        riga.mangime_qli = mangime_qli
        riga.siero_qli = siero_qli
        riga.acqua_litri = acqua_litri
        riga.tipo_mangime = tipo_mangime
        riga.perc_siero = perc_siero
        riga.stimato = False
    else:
        riga = UsoPasto(
            ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea,
            mangime_qli=mangime_qli, siero_qli=siero_qli, acqua_litri=acqua_litri,
            tipo_mangime=tipo_mangime, perc_siero=perc_siero, stimato=False,
        )
        db.session.add(riga)

    if pasto == 1:
        _rifornisci_stime(ciclo_id, data, linea, riga)

    return riga


def _rifornisci_stime(ciclo_id, data, linea, pasto1):
    """Copia i valori del pasto 1 sui pasti successivi non ancora inseriti
    manualmente (nuovi o già marcati come stimati)."""
    for pasto in PASTI_SUCCESSIVI:
        successivo = UsoPasto.query.filter_by(
            ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea
        ).first()
        if successivo and not successivo.stimato:
            continue  # inserimento manuale: non sovrascrivere
        if not successivo:
            successivo = UsoPasto(ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea)
            db.session.add(successivo)
        successivo.mangime_qli = pasto1.mangime_qli
        successivo.siero_qli = pasto1.siero_qli
        successivo.acqua_litri = pasto1.acqua_litri
        successivo.tipo_mangime = pasto1.tipo_mangime
        successivo.perc_siero = pasto1.perc_siero
        successivo.stimato = True
