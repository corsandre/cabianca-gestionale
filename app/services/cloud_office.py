"""4CloudOffice integration for cash register data sync."""

import logging
from datetime import date, datetime, timedelta
from flask import current_app
import requests

logger = logging.getLogger(__name__)


def sync_cash_register():
    """Sync daily cash register totals from 4CloudOffice.

    Returns the number of days updated.
    """
    from app import db
    from app.models import CashRegisterDaily, Transaction

    base_url = current_app.config.get("CLOUD_OFFICE_URL", "").rstrip("/")
    username = current_app.config.get("CLOUD_OFFICE_USER", "")
    password = current_app.config.get("CLOUD_OFFICE_PASSWORD", "")

    if not base_url or not username:
        raise ValueError("4CloudOffice non configurato. Controlla le impostazioni.")

    session = requests.Session()

    # Login
    login_resp = session.post(f"{base_url}/api/login", json={
        "username": username,
        "password": password,
    }, timeout=30)

    if login_resp.status_code != 200:
        # Try alternative auth methods
        login_resp = session.post(f"{base_url}/login", data={
            "username": username,
            "password": password,
        }, timeout=30)

    if login_resp.status_code not in (200, 302):
        raise ConnectionError(f"Login fallito (status {login_resp.status_code})")

    # Determine date range: last 90 days or since last sync
    last_record = CashRegisterDaily.query.order_by(CashRegisterDaily.date.desc()).first()
    if last_record and last_record.date:
        start_date = last_record.date
    else:
        start_date = date.today() - timedelta(days=90)

    end_date = date.today()
    count = 0

    # Try to fetch daily totals
    # Note: The actual API endpoints depend on 4CloudOffice version.
    # This is a best-effort implementation that tries common patterns.
    try:
        resp = session.get(f"{base_url}/api/corrispettivi", params={
            "from": start_date.isoformat(),
            "to": end_date.isoformat(),
        }, timeout=30)

        if resp.status_code == 200:
            data = resp.json()
            records = data if isinstance(data, list) else data.get("data", data.get("records", []))

            for record in records:
                rec_date = _parse_date(record.get("date") or record.get("data"))
                amount = float(record.get("total") or record.get("totale") or record.get("amount", 0))

                if rec_date and amount > 0:
                    existing = CashRegisterDaily.query.filter_by(date=rec_date).first()
                    if existing:
                        existing.total_amount = amount
                        existing.synced_at = datetime.utcnow()
                    else:
                        entry = CashRegisterDaily(
                            date=rec_date,
                            total_amount=amount,
                            synced_at=datetime.utcnow(),
                        )
                        db.session.add(entry)

                        # Also create a transaction entry
                        tx = Transaction(
                            type="entrata",
                            source="cassa",
                            official=True,
                            amount=amount,
                            net_amount=amount,
                            date=rec_date,
                            description=f"Corrispettivo giornaliero {rec_date.strftime('%d/%m/%Y')}",
                            payment_status="pagato",
                            payment_method="contanti",
                            payment_date=rec_date,
                        )
                        db.session.add(tx)

                    count += 1

            db.session.commit()

    except requests.exceptions.RequestException as e:
        logger.error(f"4CloudOffice API error: {e}")
        raise ConnectionError(f"Errore di connessione a 4CloudOffice: {e}")

    # Send Telegram notification
    try:
        from app.services.telegram_bot import send_telegram_message
        if count:
            send_telegram_message(f"Cassa sincronizzata: {count} giorni aggiornati.")
    except Exception:
        pass

    return count


def _parse_date(date_str):
    """Parse a date string in various formats."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).date()
        except (ValueError, TypeError):
            continue
    return None
