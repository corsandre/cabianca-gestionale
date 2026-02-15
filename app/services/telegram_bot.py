"""Telegram bot notifications for Ca Bianca Gestionale."""

import logging
from datetime import date, timedelta
from flask import current_app
import requests

logger = logging.getLogger(__name__)


def send_telegram_message(message: str):
    """Send a message via Telegram bot."""
    token = current_app.config.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = current_app.config.get("TELEGRAM_CHAT_ID", "")

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


def check_and_notify_deadlines():
    """Check for overdue and upcoming deadlines and send Telegram alerts."""
    from app.models import Transaction

    today = date.today()
    week_ahead = today + timedelta(days=7)

    # Overdue
    overdue = Transaction.query.filter(
        Transaction.due_date < today,
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).all()

    if overdue:
        lines = [f"<b>Scadenze arretrate: {len(overdue)}</b>"]
        for t in overdue[:10]:
            days = (today - t.due_date).days
            contact_name = t.contact.name if t.contact else "N/D"
            lines.append(
                f"  - {t.description[:40]} | {contact_name} | "
                f"\u20AC{t.amount:,.2f} | scaduta da {days}gg"
            )
        send_telegram_message("\n".join(lines))

    # Upcoming (next 7 days)
    upcoming = Transaction.query.filter(
        Transaction.due_date.between(today, week_ahead),
        Transaction.payment_status.in_(["da_pagare", "parziale"]),
    ).all()

    if upcoming:
        lines = [f"<b>Scadenze prossimi 7 giorni: {len(upcoming)}</b>"]
        for t in upcoming[:10]:
            days = (t.due_date - today).days
            contact_name = t.contact.name if t.contact else "N/D"
            lines.append(
                f"  - {t.due_date.strftime('%d/%m')} | {t.description[:40]} | "
                f"{contact_name} | \u20AC{t.amount:,.2f} ({days}gg)"
            )
        send_telegram_message("\n".join(lines))

    # Avviso se nessun import CBI da >3 giorni
    from app.models import BankTransaction
    last_import = BankTransaction.query.order_by(
        BankTransaction.created_at.desc()
    ).first()
    if last_import:
        days_since = (today - last_import.created_at.date()).days
        if days_since > 3:
            send_telegram_message(
                f"<b>Banca:</b> nessun import CBI da {days_since} giorni. "
                "Ricordati di caricare l'estratto conto."
            )

    # Movimenti bancari sospesi
    sospesi_count = BankTransaction.query.filter_by(
        status="non_riconciliato"
    ).count()
    if sospesi_count > 0:
        send_telegram_message(
            f"<b>Banca:</b> {sospesi_count} movimenti da riconciliare."
        )

    # Low stock alerts
    from app.models import Product
    low_stock = Product.query.filter(
        Product.active == True,
        Product.current_quantity <= Product.min_quantity,
        Product.min_quantity > 0,
    ).all()

    if low_stock:
        lines = [f"<b>Scorte basse: {len(low_stock)} prodotti</b>"]
        for p in low_stock:
            lines.append(f"  - {p.name}: {p.current_quantity} {p.unit} (min: {p.min_quantity})")
        send_telegram_message("\n".join(lines))
