"""Motore regole unificato per categorizzazione automatica.

Applica regole AutoRule a transazioni da qualsiasi fonte:
- CBI (banca): match su descrizione, controparte, causale ABI, importo, direzione
- SDI (fatture): match su descrizione, controparte/fornitore, P.IVA, importo, direzione
- Cassa: match su descrizione, importo
"""

import logging
from app import db
from app.models import AutoRule

logger = logging.getLogger(__name__)


def apply_rules(transaction_data, source):
    """Applica le regole attive a una transazione.

    Args:
        transaction_data: dict con i dati della transazione:
            - description: Descrizione/causale
            - counterpart: Nome controparte/fornitore
            - partita_iva: P.IVA (opzionale, per SDI)
            - causale_abi: Codice causale ABI (opzionale, per CBI)
            - amount: Importo
            - direction: C/D (CBI) o ricevuta/emessa (SDI)
        source: "banca", "sdi", "cassa"

    Returns:
        dict con le azioni da applicare, o None se nessuna regola matcha.
        Keys possibili: category_id, contact_id, revenue_stream_id,
                       description, auto_create, rule_id, rule_name
    """
    rules = AutoRule.query.filter(
        AutoRule.active == True,
        AutoRule.applies_to.in_([source, "tutti"]),
    ).order_by(AutoRule.priority.desc()).all()

    for rule in rules:
        if _matches(rule, transaction_data, source):
            actions = _build_actions(rule)
            logger.info(f"Regola '{rule.name}' (id={rule.id}) applicata a {source}: {transaction_data.get('description', '')[:50]}")
            return actions

    return None


def apply_specific_rules(transaction_data, source, rule_ids):
    """Applica solo le regole con gli ID specificati a una transazione.

    Args:
        transaction_data: dict con i dati della transazione (come apply_rules)
        source: "banca", "sdi", "cassa"
        rule_ids: lista di ID regole da applicare

    Returns:
        dict con le azioni da applicare, o None se nessuna regola matcha.
    """
    rules = AutoRule.query.filter(
        AutoRule.id.in_(rule_ids),
        AutoRule.active == True,
        AutoRule.applies_to.in_([source, "tutti"]),
    ).order_by(AutoRule.priority.desc()).all()

    for rule in rules:
        if _matches(rule, transaction_data, source):
            actions = _build_actions(rule)
            logger.info(f"Regola '{rule.name}' (id={rule.id}) riapplicata a {source}: {transaction_data.get('description', '')[:50]}")
            return actions

    return None


def apply_rules_bulk(transactions_data, source):
    """Applica le regole a una lista di transazioni.

    Args:
        transactions_data: Lista di dict (come per apply_rules)
        source: "banca", "sdi", "cassa"

    Returns:
        Lista di (transaction_data, actions_or_none)
    """
    rules = AutoRule.query.filter(
        AutoRule.active == True,
        AutoRule.applies_to.in_([source, "tutti"]),
    ).order_by(AutoRule.priority.desc()).all()

    results = []
    for td in transactions_data:
        matched = None
        for rule in rules:
            if _matches(rule, td, source):
                matched = _build_actions(rule)
                break
        results.append((td, matched))

    return results


def _matches(rule, data, source):
    """Verifica se una regola matcha i dati della transazione (AND di tutte le condizioni)."""
    # Match descrizione (case-insensitive, substring)
    if rule.match_description:
        desc = (data.get("description") or "").upper()
        remittance = (data.get("remittance_info") or "").upper()
        target = rule.match_description.upper()
        if target not in desc and target not in remittance:
            return False

    # Match controparte (case-insensitive, substring)
    if rule.match_counterpart:
        counterpart = (data.get("counterpart") or "").upper()
        if rule.match_counterpart.upper() not in counterpart:
            return False

    # Match P.IVA (esatta)
    if rule.match_partita_iva:
        piva = data.get("partita_iva") or ""
        if piva != rule.match_partita_iva:
            return False

    # Match causale ABI (per CBI)
    if rule.match_causale_abi:
        causale = data.get("causale_abi") or ""
        if causale != rule.match_causale_abi:
            return False

    # Match importo min
    if rule.match_amount_min is not None:
        amount = data.get("amount", 0)
        if amount < rule.match_amount_min:
            return False

    # Match importo max
    if rule.match_amount_max is not None:
        amount = data.get("amount", 0)
        if amount > rule.match_amount_max:
            return False

    # Match direzione
    if rule.match_direction:
        direction = data.get("direction") or ""
        if direction.upper() != rule.match_direction.upper():
            return False

    return True


def _build_actions(rule):
    """Costruisce il dict delle azioni da una regola."""
    actions = {
        "rule_id": rule.id,
        "rule_name": rule.name,
    }

    if rule.action_category_id:
        actions["category_id"] = rule.action_category_id

    if rule.action_contact_id:
        actions["contact_id"] = rule.action_contact_id

    if rule.action_revenue_stream_id:
        actions["revenue_stream_id"] = rule.action_revenue_stream_id

    if rule.action_description:
        actions["description"] = rule.action_description

    if rule.action_auto_create:
        actions["auto_create"] = True

    if rule.action_payment_method:
        actions["payment_method"] = rule.action_payment_method

    if rule.action_iva_rate is not None:
        actions["iva_rate"] = rule.action_iva_rate

    if rule.action_notes:
        actions["notes"] = rule.action_notes

    return actions
