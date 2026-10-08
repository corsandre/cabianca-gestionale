"""Quadratura tra estratto conto (CBI) e movimenti bancari importati nel gestionale.

- verifica_saldo(): saldo della banca = saldo di apertura + tutti i movimenti importati?
  La differenza "non spiegata" indica movimenti mancanti o in più nell'import; quella
  dei sospesi è solo lavoro di riconciliazione ancora da fare.
- salva_file_cbi(): conserva ogni file CBI caricato in data/cbi/ (per poterlo rileggere).
- migra_impronte(): ricalcola una volta le impronte anti-doppione dei movimenti già
  importati con il codice univoco della banca (vedi cbi_parser.impronta).
"""

import logging
import os
from datetime import datetime

from flask import current_app
from sqlalchemy import func

from app import db
from app.models import BankBalance, BankTransaction, Setting

logger = logging.getLogger(__name__)

CARTELLA_CBI = "cbi"
CHIAVE_MIGRAZIONE = "cbi_impronte_v2"


def _netto(filtro=None):
    q = db.session.query(
        func.coalesce(func.sum(db.case((BankTransaction.direction == "C", BankTransaction.amount),
                                       else_=-BankTransaction.amount)), 0))
    if filtro is not None:
        q = q.filter(filtro)
    return round(float(q.scalar() or 0), 2)


def verifica_saldo() -> dict | None:
    """Confronto tra ultimo saldo CBI e movimenti importati.

    saldo_banca = apertura + movimenti importati + non_spiegata
    saldo_contabile (apertura + movimenti riconciliati/ignorati) = saldo_banca - sospesi - non_spiegata
    """
    apertura = BankBalance.query.filter_by(balance_type="apertura").order_by(BankBalance.date).first()
    ultimo = BankBalance.query.filter_by(balance_type="chiusura").order_by(BankBalance.date.desc()).first()
    if not apertura or not ultimo:
        return None
    dal = BankTransaction.operation_date >= apertura.date
    movimenti = _netto(dal)
    sospesi = _netto(db.and_(dal, BankTransaction.status == "non_riconciliato"))
    non_spiegata = round(ultimo.balance - apertura.balance - movimenti, 2)
    piu_recenti = BankTransaction.query.filter(BankTransaction.operation_date > ultimo.date).count()
    return {
        "apertura": apertura.balance, "apertura_data": apertura.date,
        "saldo_banca": ultimo.balance, "saldo_banca_data": ultimo.date,
        "movimenti": movimenti,
        "saldo_movimenti": round(apertura.balance + movimenti, 2),
        "sospesi": sospesi,
        "saldo_contabile": round(apertura.balance + movimenti - sospesi, 2),
        "non_spiegata": non_spiegata,
        "quadra": abs(non_spiegata) < 0.01,
        "movimenti_dopo_saldo": piu_recenti,
    }


def salva_file_cbi(content: bytes, nome_originale: str, batch_id: str) -> str:
    """Conserva il file CBI caricato in data/cbi/. Ritorna il percorso relativo."""
    # data/ del progetto (volume Docker /app/data), accanto al database
    cartella = os.path.join(os.path.dirname(current_app.root_path), "data", CARTELLA_CBI)
    os.makedirs(cartella, exist_ok=True)
    base = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in (nome_originale or "estratto"))[:80]
    nome = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{batch_id}_{base}"
    with open(os.path.join(cartella, nome), "wb") as f:
        f.write(content)
    return os.path.join(CARTELLA_CBI, nome)


def migra_impronte() -> int:
    """Ricalcola una volta le impronte dei movimenti già importati.

    L'impronta vecchia (data, importo, riferimento, causale, controparte) era uguale per due
    operazioni vere identiche nello stesso giorno, e la seconda veniva scartata come doppione.
    Si ricalcola dal record 62 originale salvato in raw_data. Se due movimenti avessero la
    stessa impronta nuova (non dovrebbe succedere) la migrazione non tocca niente.
    """
    if Setting.query.get(CHIAVE_MIGRAZIONE):
        return 0
    from app.services.cbi_parser import impronta

    nuove = {}
    for bt in BankTransaction.query.order_by(BankTransaction.id).all():
        riga = (bt.raw_data or "").splitlines()[0] if bt.raw_data else ""
        if not riga.startswith("62"):
            nuove[bt.id] = bt.dedup_hash                          # niente record originale: resta com'è
            continue
        nuove[bt.id] = impronta(riga, bt.operation_date, bt.direction, bt.amount, bt.causale_abi,
                                bt.reference_code or "", bt.counterpart_name or "")
    if len(set(nuove.values())) != len(nuove):
        logger.error("Migrazione impronte: impronte nuove non univoche, nessuna modifica.")
        return 0
    cambiate = 0
    for bt in BankTransaction.query.all():
        if bt.dedup_hash != nuove[bt.id]:
            bt.dedup_hash = nuove[bt.id]
            cambiate += 1
    db.session.add(Setting(key=CHIAVE_MIGRAZIONE, value=datetime.now().isoformat(timespec="seconds")))
    db.session.commit()
    logger.info(f"Migrazione impronte movimenti bancari: {cambiate} aggiornate.")
    return cambiate
