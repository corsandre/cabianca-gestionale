import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-key-change-me")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///data/gestionale.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")

    # Cookie solo su HTTPS (produzione dietro Caddy). COOKIE_SECURE=0 solo per installazioni LAN in http,
    # altrimenti il browser non rimanda il cookie e il login non funziona.
    SESSION_COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") != "0"
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_DURATION = timedelta(days=30)

    # Azienda
    COMPANY_PIVA = "01846180196"

    # Telegram
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # notifiche finanza (scadenze, banca, cassa, SDI…)
    # notifiche di sistema (backup…); vuoto = vanno anche loro in TELEGRAM_CHAT_ID
    TELEGRAM_SISTEMA_CHAT_ID = os.getenv("TELEGRAM_SISTEMA_CHAT_ID", "")
    # Gruppo aziendale: il bot risponde solo lì e, in privato, solo ai suoi membri (vuoto = tutti)
    TELEGRAM_GROUP_ID = os.getenv("TELEGRAM_GROUP_ID", "")

    # 4CloudOffice
    CLOUD_OFFICE_URL = os.getenv("CLOUD_OFFICE_URL", "")
    CLOUD_OFFICE_USER = os.getenv("CLOUD_OFFICE_USER", "")
    CLOUD_OFFICE_PASSWORD = os.getenv("CLOUD_OFFICE_PASSWORD", "")

    # SMTP - Backup via email
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.hostinger.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")

    # IMAP - Recupero fatture SDI via email
    IMAP_HOST = os.getenv("IMAP_HOST", "")
    IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
    IMAP_USER = os.getenv("IMAP_USER", "")
    IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
    IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")
    IMAP_SEARCH_FROM = os.getenv("IMAP_SEARCH_FROM", "")

    # Admin
    ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
    ADMIN_DISPLAY_NAME = os.getenv("ADMIN_DISPLAY_NAME", "Amministratore")
