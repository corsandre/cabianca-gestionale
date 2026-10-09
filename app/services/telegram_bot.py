"""Telegram bot notifications for Ca Bianca Gestionale."""

import logging
from datetime import date, timedelta
from flask import current_app
import requests

logger = logging.getLogger(__name__)


def _chat_del_canale(canale):
    """canale="finanza" → TELEGRAM_CHAT_ID; "sistema" → TELEGRAM_SISTEMA_CHAT_ID; "allevamento" →
    TELEGRAM_GROUP_ID (gruppo del bot allevamento). Se il gruppo specifico manca, TELEGRAM_CHAT_ID."""
    chat_id = current_app.config.get("TELEGRAM_CHAT_ID", "")
    if canale == "sistema":
        chat_id = current_app.config.get("TELEGRAM_SISTEMA_CHAT_ID") or chat_id
    elif canale == "allevamento":
        chat_id = current_app.config.get("TELEGRAM_GROUP_ID") or chat_id
    return chat_id


def send_telegram_message(message: str, canale: str = "finanza"):
    """Invia una notifica via bot nel gruppo del canale (vedi _chat_del_canale)."""
    token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = _chat_del_canale(canale)

    if not token or not chat_id:
        logger.debug("Telegram not configured, skipping notification.")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
        }, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send error: {e}")
        return False


def send_telegram_foto(png: bytes, didascalia: str, canale: str = "sistema"):
    """Invia una fotografia (PNG) con didascalia nel gruppo del canale."""
    token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = _chat_del_canale(canale)
    if not token or not chat_id:
        return False
    try:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                             data={"chat_id": chat_id, "caption": didascalia[:1000], "parse_mode": "HTML"},
                             files={"photo": ("schermo.png", png, "image/png")}, timeout=30)
        resp.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Telegram send photo error: {e}")
        return False


def check_and_notify_deadlines():
    """Messaggio del mattino nel gruppo della finanza: scadenze, banca e controllo di fine mese
    in un unico messaggio (niente messaggio se non c'è niente da dire)."""
    from app.models import BankTransaction, Transaction

    today = date.today()
    week_ahead = today + timedelta(days=7)
    eur = lambda v: f"\u20AC{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    righe = []

    upcoming = Transaction.query.filter(
        Transaction.due_date.between(today, week_ahead),
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).order_by(Transaction.due_date).all()
    if upcoming:
        righe.append(f"<b>Scadenze nei prossimi 7 giorni: {len(upcoming)}</b> ({eur(sum(t.amount for t in upcoming))})")
        for t in upcoming[:5]:
            nome = t.contact.name if t.contact else (t.description or "")[:30]
            righe.append(f"  · {t.due_date.strftime('%d/%m')} {nome[:30]} {eur(t.amount)}")

    overdue = Transaction.query.filter(
        Transaction.due_date < today,
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).all()
    if overdue:
        righe.append(f"<b>Da pagare già scadute: {len(overdue)}</b> ({eur(sum(t.amount for t in overdue))}): "
                     "pagale o, se sono già pagate, collegale al bonifico.")

    sospesi = BankTransaction.query.filter_by(status="non_riconciliato").count()
    last_import = BankTransaction.query.order_by(BankTransaction.created_at.desc()).first()
    giorni = (today - last_import.created_at.date()).days if last_import else None
    banca = []
    if sospesi:
        banca.append(f"{sospesi} movimenti da riconciliare")
    if giorni is not None and giorni > 7:
        banca.append(f"estratto conto caricato {giorni} giorni fa")
    if banca:
        righe.append("<b>Banca:</b> " + ", ".join(banca) + ".")

    if righe:
        send_telegram_message("📋 <b>Finanza</b>\n" + "\n".join(righe) +
                              "\nDettagli in Finanza › Controllo di fine mese.")
