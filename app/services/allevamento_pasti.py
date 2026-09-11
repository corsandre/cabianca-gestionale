"""
Registrazione uso pasti (mangime/siero/acqua) con gestione dei valori stimati.

Il primo pasto della giornata inserito manualmente (non necessariamente il
Pasto 1: può essere qualunque) fa da riferimento per gli altri pasti dello
stesso giorno/linea non ancora compilati, che vengono marcati come "stimato"
finché non arriva un inserimento manuale specifico per loro.

Tipo mangime e % sostanza secca del siero non si chiedono all'utente: si
prendono dall'ultima consegna registrata per ciascun ingrediente. La %
sostituzione in ricetta si ricava di conseguenza dai quantitativi di
mangime/siero inseriti per quel pasto/linea, non è un dato manuale.
"""
from app import db
from app.models import UsoPasto, ConsegnaMangime, ConsegnaSiero

TUTTI_I_PASTI = [1, 2, 3]


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


def registra_pasto(ciclo_id, data, pasto, linea, mangime_qli=None, siero_qli=None, acqua_qli=None):
    """Salva un inserimento manuale per (data, pasto, linea) e, se pasto è il
    primo della giornata, aggiorna i pasti successivi ancora "stimati"."""
    tipo_mangime = ultimo_tipo_mangime(ciclo_id)
    perc_ss_siero = ultima_perc_sostanza_secca_siero(ciclo_id)
    perc_siero = calcola_perc_siero(mangime_qli, siero_qli, perc_ss_siero)

    riga = UsoPasto.query.filter_by(ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea).first()
    if riga:
        riga.mangime_qli = mangime_qli
        riga.siero_qli = siero_qli
        riga.acqua_qli = acqua_qli
        riga.tipo_mangime = tipo_mangime
        riga.perc_siero = perc_siero
        riga.perc_ss_siero_rif = perc_ss_siero
        riga.stimato = False
    else:
        riga = UsoPasto(
            ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea,
            mangime_qli=mangime_qli, siero_qli=siero_qli, acqua_qli=acqua_qli,
            tipo_mangime=tipo_mangime, perc_siero=perc_siero, perc_ss_siero_rif=perc_ss_siero,
            stimato=False,
        )
        db.session.add(riga)

    _rifornisci_stime(ciclo_id, data, linea, pasto, riga)

    return riga


def _rifornisci_stime(ciclo_id, data, linea, pasto_inserito, riferimento):
    """Copia i valori appena inseriti manualmente sugli altri pasti dello
    stesso giorno/linea non ancora compilati manualmente (nuovi o già
    marcati come stimati), sia prima che dopo quello inserito."""
    for pasto in TUTTI_I_PASTI:
        if pasto == pasto_inserito:
            continue
        altro = UsoPasto.query.filter_by(
            ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea
        ).first()
        if altro and not altro.stimato:
            continue  # inserimento manuale: non sovrascrivere
        if not altro:
            altro = UsoPasto(ciclo_id=ciclo_id, data=data, pasto=pasto, linea=linea)
            db.session.add(altro)
        altro.mangime_qli = riferimento.mangime_qli
        altro.siero_qli = riferimento.siero_qli
        altro.acqua_qli = riferimento.acqua_qli
        altro.tipo_mangime = riferimento.tipo_mangime
        altro.perc_siero = riferimento.perc_siero
        altro.perc_ss_siero_rif = riferimento.perc_ss_siero_rif
        altro.stimato = True
