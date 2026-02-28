"""Email backup service for Ca Bianca Gestionale."""

import os
import shutil
import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import current_app

logger = logging.getLogger(__name__)


def run_backup():
    """Backup del database SQLite e invio via email."""
    db_path = _get_db_path()
    if not db_path or not os.path.exists(db_path):
        logger.warning("Database file not found, skipping backup.")
        return

    # Controlla frequenza: salta se il backup e' gia' stato fatto di recente
    if not _should_run_backup():
        logger.info("Backup saltato: eseguito di recente secondo la frequenza configurata.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"gestionale_backup_{timestamp}.db"
    backup_dir = os.path.join(current_app.root_path, "..", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    local_backup_path = os.path.join(backup_dir, backup_filename)

    shutil.copy2(db_path, local_backup_path)
    logger.info(f"Local backup created: {local_backup_path}")

    _cleanup_local_backups(backup_dir, keep=7)

    try:
        _send_backup_email(local_backup_path, backup_filename)
        logger.info("Email backup completato.")
    except Exception as e:
        logger.error(f"Invio email backup fallito: {e}")

    try:
        from app.services.telegram_bot import send_telegram_message
        send_telegram_message(f"Backup completato: {backup_filename}")
    except Exception:
        pass


def _should_run_backup():
    """Controlla se il backup deve essere eseguito in base alla frequenza configurata."""
    try:
        from app.models import Setting
        freq_setting = Setting.query.get("backup_frequency_days")
        frequency_days = int(freq_setting.value) if freq_setting else 1
        if frequency_days <= 1:
            return True

        backup_dir = os.path.join(current_app.root_path, "..", "backups")
        if not os.path.exists(backup_dir):
            return True

        files = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("gestionale_backup_")],
            reverse=True,
        )
        if not files:
            return True

        # Estrae la data dal nome del file piu' recente
        latest = files[0]
        date_str = latest.replace("gestionale_backup_", "").replace(".db", "")[:8]
        last_backup_date = datetime.strptime(date_str, "%Y%m%d")
        return datetime.now() - last_backup_date >= timedelta(days=frequency_days)
    except Exception:
        return True


def _get_db_path():
    """Estrae il percorso del file dal URI SQLAlchemy."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return None


def _cleanup_local_backups(backup_dir, keep=7):
    """Rimuove i vecchi backup locali, mantenendo i piu' recenti."""
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("gestionale_backup_")],
        reverse=True,
    )
    for old_file in files[keep:]:
        os.remove(os.path.join(backup_dir, old_file))


def _send_backup_email(filepath, filename):
    """Invia il file di backup come allegato email."""
    smtp_host = current_app.config.get("SMTP_HOST", "")
    smtp_port = int(current_app.config.get("SMTP_PORT", 587))
    smtp_user = current_app.config.get("SMTP_USER", "")
    smtp_password = current_app.config.get("SMTP_PASSWORD", "")

    from app.models import Setting
    setting = Setting.query.get("backup_email_to")
    email_to = setting.value if setting else ""

    if not smtp_host or not smtp_user or not email_to:
        logger.debug("Email backup non configurato, salto invio.")
        return

    msg = EmailMessage()
    msg["Subject"] = f"[Ca Bianca] Backup Gestionale - {datetime.now().strftime('%d/%m/%Y')}"
    msg["From"] = smtp_user
    msg["To"] = email_to
    msg.set_content(
        f"Backup automatico del gestionale Ca Bianca.\n\n"
        f"File: {filename}\n"
        f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    )

    with open(filepath, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="octet-stream",
            filename=filename,
        )

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)
