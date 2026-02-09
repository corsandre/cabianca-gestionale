"""Google Drive backup service for Ca Bianca Gestionale."""

import os
import shutil
import logging
from datetime import datetime
from flask import current_app

logger = logging.getLogger(__name__)


def run_backup():
    """Backup the SQLite database to Google Drive."""
    db_path = _get_db_path()
    if not db_path or not os.path.exists(db_path):
        logger.warning("Database file not found, skipping backup.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"gestionale_backup_{timestamp}.db"
    backup_dir = os.path.join(current_app.root_path, "..", "backups")
    os.makedirs(backup_dir, exist_ok=True)
    local_backup_path = os.path.join(backup_dir, backup_filename)

    # Copy database (SQLite safe copy)
    shutil.copy2(db_path, local_backup_path)
    logger.info(f"Local backup created: {local_backup_path}")

    # Clean old local backups (keep last 7)
    _cleanup_local_backups(backup_dir, keep=7)

    # Upload to Google Drive
    try:
        _upload_to_gdrive(local_backup_path, backup_filename)
        logger.info("Google Drive backup completed.")
    except Exception as e:
        logger.error(f"Google Drive upload failed: {e}")
        # Local backup still exists, so not a total failure

    # Send Telegram notification
    try:
        from app.services.telegram_bot import send_telegram_message
        send_telegram_message(f"Backup completato: {backup_filename}")
    except Exception:
        pass


def _get_db_path():
    """Extract the actual file path from the SQLAlchemy URI."""
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    if uri.startswith("sqlite:///"):
        return uri.replace("sqlite:///", "")
    return None


def _cleanup_local_backups(backup_dir, keep=7):
    """Remove old local backup files, keeping the most recent ones."""
    files = sorted(
        [f for f in os.listdir(backup_dir) if f.startswith("gestionale_backup_")],
        reverse=True,
    )
    for old_file in files[keep:]:
        os.remove(os.path.join(backup_dir, old_file))


def _upload_to_gdrive(filepath, filename):
    """Upload a file to Google Drive."""
    creds_json = current_app.config.get("GOOGLE_DRIVE_CREDENTIALS_JSON", "")
    folder_id = current_app.config.get("GOOGLE_DRIVE_FOLDER_ID", "")

    if not creds_json or not folder_id:
        logger.debug("Google Drive not configured, skipping upload.")
        return

    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    # Load credentials from JSON string or file path
    if os.path.isfile(creds_json):
        credentials = service_account.Credentials.from_service_account_file(
            creds_json, scopes=["https://www.googleapis.com/auth/drive.file"]
        )
    else:
        creds_dict = json.loads(creds_json)
        credentials = service_account.Credentials.from_service_account_info(
            creds_dict, scopes=["https://www.googleapis.com/auth/drive.file"]
        )

    service = build("drive", "v3", credentials=credentials)

    file_metadata = {
        "name": filename,
        "parents": [folder_id],
    }
    media = MediaFileUpload(filepath, mimetype="application/x-sqlite3")
    service.files().create(body=file_metadata, media_body=media, fields="id").execute()

    # Clean old Drive backups (keep last 14)
    results = service.files().list(
        q=f"'{folder_id}' in parents and name contains 'gestionale_backup_'",
        orderBy="createdTime desc",
        fields="files(id, name)",
        pageSize=50,
    ).execute()

    files = results.get("files", [])
    for old_file in files[14:]:
        service.files().delete(fileId=old_file["id"]).execute()
