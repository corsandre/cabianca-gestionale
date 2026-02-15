"""Motore di riconciliazione bancaria.

Abbina movimenti CBI a fatture e transazioni esistenti in 3 fasi:
1. Regole utente con auto_create
2. Match fatture SDI (da_pagare)
3. Match transazioni manuali
"""

import logging
from datetime import timedelta
from difflib import SequenceMatcher

from app import db
from app.models import BankTransaction, Transaction, Contact
from app.services.rules_engine import apply_rules

logger = logging.getLogger(__name__)

# Soglia di confidenza per abbinamento automatico (0-100)
AUTO_MATCH_THRESHOLD = 80


def reconcile_batch(bank_transactions):
    """Riconcilia un batch di movimenti bancari.

    Args:
        bank_transactions: Lista di BankTransaction gia salvati nel DB

    Returns:
        dict con statistiche: {"matched": N, "pending": N, "auto_created": N}
    """
    stats = {"matched": 0, "pending": 0, "auto_created": 0}

    for bt in bank_transactions:
        if bt.status != "non_riconciliato":
            continue

        # Fase 1: Regole utente
        rule_data = {
            "description": bt.causale_description or "",
            "counterpart": bt.counterpart_name or "",
            "causale_abi": bt.causale_abi or "",
            "amount": bt.amount,
            "direction": bt.direction,
            "remittance_info": bt.remittance_info or "",
        }
        actions = apply_rules(rule_data, "banca")

        if actions and actions.get("auto_create"):
            _create_transaction_from_bank(bt, actions)
            bt.status = "riconciliato"
            bt.matched_by = "regola"
            bt.matched_rule_id = actions.get("rule_id")
            stats["auto_created"] += 1
            stats["matched"] += 1
            continue

        # Fase 2: Match fatture SDI
        match = _find_best_match(bt, source="sdi")
        if match and match["score"] >= AUTO_MATCH_THRESHOLD:
            _link_transaction(bt, match["transaction"], "auto")
            stats["matched"] += 1
            continue

        # Fase 3: Match transazioni manuali e banca
        match = _find_best_match(bt, source="manuale")
        if not match or match["score"] < AUTO_MATCH_THRESHOLD:
            match = _find_best_match(bt, source="banca")
        if match and match["score"] >= AUTO_MATCH_THRESHOLD:
            _link_transaction(bt, match["transaction"], "auto")
            stats["matched"] += 1
            continue

        stats["pending"] += 1

    db.session.flush()
    return stats


def get_match_proposals(bank_transaction):
    """Genera proposte di abbinamento per un singolo movimento.

    Returns:
        Lista di dict: [{"transaction": Transaction, "score": int, "reasons": [str]}]
    """
    proposals = []

    # Cerca tra fatture SDI da pagare
    candidates = _get_candidates(bank_transaction, "sdi")
    for tx in candidates:
        score, reasons = _compute_score(bank_transaction, tx)
        if score > 20:
            proposals.append({"transaction": tx, "score": score, "reasons": reasons})

    # Cerca tra transazioni manuali e banca
    for src in ("manuale", "banca"):
        candidates = _get_candidates(bank_transaction, src)
        for tx in candidates:
            score, reasons = _compute_score(bank_transaction, tx)
            if score > 20:
                proposals.append({"transaction": tx, "score": score, "reasons": reasons})

    proposals.sort(key=lambda x: x["score"], reverse=True)
    return proposals[:5]


def _find_best_match(bt, source):
    """Trova il miglior match per un movimento bancario."""
    candidates = _get_candidates(bt, source)
    best = None
    best_score = 0

    for tx in candidates:
        score, reasons = _compute_score(bt, tx)
        if score > best_score:
            best_score = score
            best = {"transaction": tx, "score": score, "reasons": reasons}

    return best


def _get_candidates(bt, source):
    """Recupera transazioni candidate per il matching."""
    # Finestra temporale: +-30 giorni dalla data operazione
    date_from = bt.operation_date - timedelta(days=30)
    date_to = bt.operation_date + timedelta(days=30)

    # Tipo: credito = entrata, debito = uscita
    tx_type = "entrata" if bt.direction == "C" else "uscita"

    query = Transaction.query.filter(
        Transaction.source == source,
        Transaction.type == tx_type,
        Transaction.date.between(date_from, date_to),
    )

    if source == "sdi":
        query = query.filter(
            Transaction.payment_status.in_(["da_pagare", "parziale"])
        )

    # Escludi transazioni gia riconciliate con altri movimenti bancari
    already_matched = db.select(BankTransaction.matched_transaction_id).where(
        BankTransaction.matched_transaction_id.isnot(None),
        BankTransaction.id != bt.id,
    ).scalar_subquery()

    query = query.filter(~Transaction.id.in_(already_matched))

    return query.all()


def _compute_score(bt, tx):
    """Calcola il punteggio di matching tra movimento bancario e transazione.

    Punteggio massimo: 100
    - Importo esatto (+-2%): +50
    - Nome controparte simile: +30
    - Data vicina (+-7gg): +20
    """
    score = 0
    reasons = []

    # Match importo (tolleranza +-2%)
    if tx.amount > 0:
        diff_pct = abs(bt.amount - tx.amount) / tx.amount
        if diff_pct <= 0.02:
            score += 50
            if diff_pct == 0:
                reasons.append("Importo identico")
            else:
                reasons.append(f"Importo simile ({diff_pct:.1%})")
        elif diff_pct <= 0.10:
            score += 20
            reasons.append(f"Importo vicino ({diff_pct:.1%})")

    # Match nome controparte
    if bt.counterpart_name and tx.contact:
        similarity = _name_similarity(bt.counterpart_name, tx.contact.name)
        if similarity > 0.7:
            score += 30
            reasons.append(f"Nome controparte simile ({similarity:.0%})")
        elif similarity > 0.4:
            score += 15
            reasons.append(f"Nome controparte parziale ({similarity:.0%})")

    # Match data
    if tx.date:
        days_diff = abs((bt.operation_date - tx.date).days)
        if days_diff <= 7:
            score += 20
            reasons.append(f"Data vicina ({days_diff}gg)")
        elif days_diff <= 15:
            score += 10
            reasons.append(f"Data compatibile ({days_diff}gg)")

    return score, reasons


def _name_similarity(name1, name2):
    """Calcola la similarita tra due nomi (0.0 - 1.0)."""
    if not name1 or not name2:
        return 0.0
    n1 = name1.upper().strip()
    n2 = name2.upper().strip()
    # Match diretto
    if n1 in n2 or n2 in n1:
        return 0.9
    return SequenceMatcher(None, n1, n2).ratio()


def _link_transaction(bt, tx, matched_by):
    """Collega un movimento bancario a una transazione esistente."""
    bt.status = "riconciliato"
    bt.matched_transaction_id = tx.id
    bt.matched_by = matched_by

    # Aggiorna stato pagamento fattura
    if tx.source == "sdi" and tx.payment_status in ("da_pagare", "parziale"):
        tx.payment_status = "pagato"
        tx.payment_date = bt.operation_date


def _create_transaction_from_bank(bt, actions):
    """Crea una transazione in prima nota da un movimento bancario."""
    tx = Transaction(
        type="entrata" if bt.direction == "C" else "uscita",
        source="banca",
        official=True,
        amount=bt.amount,
        date=bt.operation_date,
        description=actions.get("description") or _build_description(bt),
        category_id=actions.get("category_id"),
        contact_id=actions.get("contact_id"),
        revenue_stream_id=actions.get("revenue_stream_id"),
        payment_status="pagato",
        payment_method="bonifico",
        payment_date=bt.operation_date,
    )
    db.session.add(tx)
    db.session.flush()

    bt.matched_transaction_id = tx.id


def create_transaction_from_bank_manual(bt, category_id=None, contact_id=None,
                                         revenue_stream_id=None, description=None):
    """Crea una transazione manuale da un movimento bancario (azione utente)."""
    tx = Transaction(
        type="entrata" if bt.direction == "C" else "uscita",
        source="banca",
        official=True,
        amount=bt.amount,
        date=bt.operation_date,
        description=description or _build_description(bt),
        category_id=category_id,
        contact_id=contact_id,
        revenue_stream_id=revenue_stream_id,
        payment_status="pagato",
        payment_method="bonifico",
        payment_date=bt.operation_date,
    )
    db.session.add(tx)
    db.session.flush()

    bt.status = "riconciliato"
    bt.matched_transaction_id = tx.id
    bt.matched_by = "manuale"

    return tx


def get_available_transactions(bt):
    """Recupera transazioni disponibili per abbinamento manuale (vista iniziale).

    Mostra le piu' probabili (+-30gg, non pagate) come punto di partenza.
    La ricerca AJAX permette poi di cercare senza limiti.

    Returns:
        dict con:
        - "sdi": lista transazioni SDI disponibili
        - "altre": lista transazioni manuali/banca disponibili
    """
    date_from = bt.operation_date - timedelta(days=60)
    date_to = bt.operation_date + timedelta(days=30)
    tx_type = "entrata" if bt.direction == "C" else "uscita"

    # Transazioni gia abbinate ad altri movimenti bancari
    already_matched = db.select(BankTransaction.matched_transaction_id).where(
        BankTransaction.matched_transaction_id.isnot(None),
        BankTransaction.id != bt.id,
    ).scalar_subquery()

    base_query = Transaction.query.filter(
        Transaction.type == tx_type,
        Transaction.date.between(date_from, date_to),
        ~Transaction.id.in_(already_matched),
    )

    # SDI: non pagate come default iniziale
    sdi = base_query.filter(
        Transaction.source == "sdi",
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).order_by(Transaction.date.desc()).limit(20).all()

    # Manuali + banca: non pagate come default iniziale
    altre = base_query.filter(
        Transaction.source.in_(["manuale", "banca"]),
        Transaction.payment_status != "pagato",
    ).order_by(Transaction.date.desc()).limit(20).all()

    return {"sdi": sdi, "altre": altre}


def _build_description(bt):
    """Costruisce una descrizione leggibile per la transazione."""
    parts = []
    if bt.counterpart_name:
        parts.append(bt.counterpart_name)
    if bt.causale_description:
        parts.append(bt.causale_description)
    if bt.remittance_info:
        parts.append(bt.remittance_info[:100])
    return " - ".join(parts) if parts else f"Movimento bancario {bt.operation_date}"
