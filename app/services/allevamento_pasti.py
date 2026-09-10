"""
Registrazione uso pasti (mangime/siero/acqua) con gestione dei valori stimati.

Il dato reale viene di norma rilevato al primo pasto (mattina). I pasti
successivi, se non compilati manualmente, ereditano i valori del primo pasto
e vengono marcati come "stimato" finché non arriva un inserimento manuale.
"""
from app import db
from app.models import UsoPasto

PASTI_SUCCESSIVI = [2, 3]


def registra_pasto(ciclo_id, data, pasto, linea, mangime_qli=None, siero_qli=None,
                    acqua_litri=None, tipo_mangime=None, perc_siero=None):
    """Salva un inserimento manuale per (data, pasto, linea) e, se pasto è il
    primo della giornata, aggiorna i pasti successivi ancora "stimati"."""
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
