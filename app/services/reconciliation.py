"""Motore di riconciliazione bancaria.

Abbina movimenti CBI a fatture e transazioni esistenti in 3 fasi:
1. Regole utente con auto_create
2. Match fatture SDI (da_pagare)
3. Match transazioni manuali
"""

import logging
import re
from datetime import timedelta
from difflib import SequenceMatcher

from app import db
from app.models import BankTransaction, Transaction, Contact, SdiInvoice
from app.services.sdi_importer import NOTE_DI_CREDITO
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
    _cache_appresi["coppie"] = None          # abbinamenti fatti da poco compresi

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

        if actions and actions.get("ignore"):
            bt.status = "ignorato"
            bt.matched_by = "regola"
            bt.matched_rule_id = actions.get("rule_id")
            bt.ignore_reason_id = actions.get("ignore_reason_id")
            stats["matched"] += 1
            continue

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
    """Trova il miglior match per un movimento bancario.

    A parità di punteggio vince la transazione con la data più vicina al movimento
    (es. fatture mensili dello stesso fornitore con lo stesso importo).
    """
    candidates = _get_candidates(bt, source)
    best = None
    best_key = None

    for tx in candidates:
        score, reasons = _compute_score(bt, tx)
        if score <= 0:
            continue
        key = (score, -abs((bt.operation_date - tx.date).days) if tx.date else -9999)
        if best_key is None or key > best_key:
            best_key = key
            best = {"transaction": tx, "score": score, "reasons": reasons}

    return best


def _chiave_nome(nome):
    """Prime due parole significative del nome, per confrontare controparti e fornitori."""
    parole = [w for w in re.sub(r"[^A-Z0-9 ]", " ", (nome or "").upper()).split()
              if len(w) > 2 and w not in ("SPA", "SRL", "SNC", "SAS", "SOC", "SOCIETA", "COOP", "DEL", "DELLA")]
    return " ".join(parole[:2])


def _nomi_appresi():
    """Coppie (controparte in banca, fornitore/cliente) già abbinate in passato.

    Insegnano al motore che, per esempio, 'CPIUC CREMONA' in banca è 'MAXI DI SRL' in fattura,
    o 'TELECOMITALIA SPA' è 'TIM S.p.A.'. Si ricalcolano a ogni richiesta (pochi millisecondi).
    """
    coppie = set()
    righe = db.session.query(BankTransaction.counterpart_name, SdiInvoice.sender_name, Contact.name).join(
        Transaction, Transaction.id == BankTransaction.matched_transaction_id
    ).outerjoin(SdiInvoice, SdiInvoice.id == Transaction.invoice_id
    ).outerjoin(Contact, Contact.id == Transaction.contact_id
    ).filter(BankTransaction.status == "riconciliato").all()
    for cp, fornitore, contatto in righe:
        a = _chiave_nome(cp)
        if not a:
            continue
        for b in (fornitore, contatto):
            if _chiave_nome(b):
                coppie.add((a, _chiave_nome(b)))
    return coppie


_cache_appresi = {"coppie": None, "quando": 0.0}


def _appresi():
    """Nomi appresi, ricalcolati al massimo una volta al minuto (servono a ogni confronto)."""
    import time
    if _cache_appresi["coppie"] is None or time.monotonic() - _cache_appresi["quando"] > 60:
        _cache_appresi["coppie"] = _nomi_appresi()
        _cache_appresi["quando"] = time.monotonic()
    return _cache_appresi["coppie"]


# Le fatture dei fornitori si pagano anche a 90-150 giorni: per le SDI si cerca fino a 180 giorni prima.
# Oltre i 15 giorni il punteggio arriva alla soglia solo se coincidono importo e nome.
GIORNI_SDI_PRIMA = 180


def _get_candidates(bt, source):
    """Recupera transazioni candidate per il matching."""
    # Finestra temporale: +-30 giorni dalla data operazione (SDI: da 90 giorni prima)
    date_from = bt.operation_date - timedelta(days=GIORNI_SDI_PRIMA if source == "sdi" else 30)
    date_to = bt.operation_date + timedelta(days=30)

    # Tipo: credito = entrata, debito = uscita
    tx_type = "entrata" if bt.direction == "C" else "uscita"

    query = Transaction.query.filter(
        Transaction.source == source,
        Transaction.type == tx_type,
        Transaction.date.between(date_from, date_to),
    )

    if source == "sdi":
        # le note di credito non pagano e non incassano niente
        note_credito = db.select(SdiInvoice.id).where(SdiInvoice.invoice_type.in_(NOTE_DI_CREDITO))
        query = query.filter(Transaction.amount > 0, ~Transaction.invoice_id.in_(note_credito))
        # da pagare, oppure segnate "pagato" a mano senza il bonifico collegato
        # (quelle pagate in contanti o non applicabili restano fuori)
        query = query.filter(db.or_(
            Transaction.payment_status.in_(["da_pagare", "parziale"]),
            db.and_(Transaction.payment_status == "pagato",
                    db.or_(Transaction.payment_method.is_(None),
                           Transaction.payment_method.notin_(["contanti", "non_applicabile"]))),
        ))

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

    # Match importo (tolleranza +-2%): per le fatture SDI vale anche l'importo da pagare
    # (netto della ritenuta d'acconto, somma delle rate)
    importi = [tx.amount]
    if tx.invoice is not None and tx.invoice.importo_da_pagare:
        importi.append(tx.invoice.importo_da_pagare)
    importo = min(importi, key=lambda v: abs(bt.amount - v)) if tx.amount and tx.amount > 0 else tx.amount
    lontana = tx.date is not None and abs((bt.operation_date - tx.date).days) > 30
    if tx.amount > 0:
        diff_pct = abs(bt.amount - importo) / importo
        if lontana and abs(bt.amount - importo) > 0.01:
            # oltre 30 giorni solo l'importo identico conta: i fornitori che fatturano ogni mese
            # importi quasi uguali (telefono, energia) altrimenti finiscono sulla fattura sbagliata
            diff_pct = 1
        if diff_pct <= 0.02:
            score += 50
            if diff_pct == 0:
                reasons.append("Importo identico" if importo == tx.amount else "Importo identico al netto da pagare")
            else:
                reasons.append(f"Importo simile ({diff_pct:.1%})")
        elif diff_pct <= 0.10:
            score += 20
            reasons.append(f"Importo vicino ({diff_pct:.1%})")

    # Match nome controparte: contatto, fornitore della fattura, o coppia già abbinata in passato
    nomi = [n for n in ((tx.contact.name if tx.contact else None),
                        (tx.invoice.sender_name if tx.invoice is not None else None)) if n]
    if bt.counterpart_name and nomi:
        similarity = max(_name_similarity(bt.counterpart_name, n) for n in nomi)
        appresi = _appresi()
        gia_visto = any((_chiave_nome(bt.counterpart_name), _chiave_nome(n)) in appresi for n in nomi)
        if similarity > 0.7:
            score += 30
            reasons.append(f"Nome controparte simile ({similarity:.0%})")
        elif gia_visto:
            score += 30
            reasons.append("Stessa controparte già abbinata in passato")
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

    # Aggiorna stato pagamento
    if tx.payment_status in ("da_pagare", "parziale"):
        tx.payment_status = "pagato"
        tx.payment_date = bt.operation_date
    elif tx.payment_status == "pagato" and not tx.payment_date:
        tx.payment_date = bt.operation_date


def _create_transaction_from_bank(bt, actions):
    """Crea una transazione in prima nota da un movimento bancario."""
    payment_method = actions.get("payment_method", "bonifico")
    iva_rate = actions.get("iva_rate", 0) or 0
    amount = bt.amount

    if iva_rate > 0:
        net_amount = round(amount / (1 + iva_rate / 100), 2)
        iva_amount = round(amount - net_amount, 2)
    else:
        net_amount = amount
        iva_amount = 0

    # Calcola data contabile (con eventuale offset)
    tx_date = bt.operation_date
    if actions.get("date_end_prev_month"):
        first_of_month = tx_date.replace(day=1)
        tx_date = first_of_month - timedelta(days=1)
    elif actions.get("date_offset"):
        tx_date = tx_date - timedelta(days=actions["date_offset"])

    tx = Transaction(
        type="entrata" if bt.direction == "C" else "uscita",
        source="banca",
        official=True,
        amount=amount,
        net_amount=net_amount,
        iva_amount=iva_amount,
        iva_rate=iva_rate,
        date=tx_date,
        description=actions.get("description") or _build_description(bt),
        category_id=actions.get("category_id"),
        contact_id=actions.get("contact_id"),
        revenue_stream_id=actions.get("revenue_stream_id"),
        payment_status="pagato",
        payment_method=payment_method,
        payment_date=bt.operation_date,
        due_date=bt.operation_date,
        notes=actions.get("notes"),
    )
    db.session.add(tx)
    db.session.flush()

    bt.matched_transaction_id = tx.id


def create_transaction_from_rule(bt, actions):
    """Crea una transazione da regola e riconcilia il movimento bancario (API pubblica)."""
    _create_transaction_from_bank(bt, actions)
    bt.status = "riconciliato"
    bt.matched_by = "regola"
    bt.matched_rule_id = actions.get("rule_id")


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
        due_date=bt.operation_date,
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

    # SDI: non pagate, o segnate pagate senza bonifico collegato (non in contanti)
    sdi = base_query.filter(
        Transaction.source == "sdi",
        _sdi_aperta(),
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
    if bt.description:
        parts.append(bt.description[:100])
    elif bt.remittance_info:
        parts.append(bt.remittance_info[:100])
    return " - ".join(parts) if parts else f"Movimento bancario {bt.operation_date}"


def _sdi_aperta():
    """Filtro: fattura SDI ancora da abbinare a un pagamento (da pagare, parziale, oppure
    segnata pagata a mano ma non in contanti). Le già collegate a un bonifico si escludono a parte."""
    return db.or_(
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
        db.and_(Transaction.payment_status == "pagato",
                db.or_(Transaction.payment_method.is_(None),
                       Transaction.payment_method.notin_(["contanti", "non_applicabile"]))),
    )
