"""Backup notturno dei database del gestionale, con invio per email e avviso su Telegram.

Lo lancia lo scheduler (app/__init__.py → _init_scheduler, job "backup") e il pulsante
"Backup ora" in Impostazioni (app/routes/impostazioni.py → backup_now).

Dalla 3.3.3:
- salva TUTTI i database in data/ (gestionale.db, prodotti.db, ...), non solo quello principale;
- copia con l'API di backup di sqlite3 + integrity_check (vedi backup_sqlite.py: con il WAL un
  semplice copy2 del file perderebbe le ultime scritture);
- tiene gli ultimi 7 backup e il primo di ogni mese per 12 mesi;
- una volta a settimana (domenica) archivia anche i PDF delle etichette dei lotti
  (data/prodotti/etichette), che fanno parte del registro di legge.

I file si chiamano <database>_backup_AAAAMMGG_HHMMSS.db in backups/.
"""

import os
import logging
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from flask import current_app

from app.services.backup_sqlite import (
    archivia_cartella, backup_da_eliminare, copia_sqlite, database_da_salvare, nome_backup,
)

logger = logging.getLogger(__name__)

# Le email oltre questa dimensione vengono rifiutate da molti server: oltre, il file resta solo in locale.
LIMITE_ALLEGATI_BYTE = 20 * 1024 * 1024


def run_backup():
    """Backup di tutti i database in data/ e invio via email."""
    db_principale = _get_db_path()
    if not db_principale or not os.path.exists(db_principale):
        logger.warning("Database file not found, skipping backup.")
        return

    # Controlla frequenza: salta se il backup e' gia' stato fatto di recente
    if not _should_run_backup():
        logger.info("Backup saltato: eseguito di recente secondo la frequenza configurata.")
        return

    adesso = datetime.now()
    backup_dir = _backup_dir()
    os.makedirs(backup_dir, exist_ok=True)

    riusciti, problemi = [], []
    for db_path in database_da_salvare(os.path.dirname(db_principale)):
        nome = nome_backup(db_path, adesso)
        destinazione = os.path.join(backup_dir, nome)
        try:
            esito = copia_sqlite(db_path, destinazione)
        except Exception as e:
            esito = f"errore: {e}"
        if esito == "ok":
            riusciti.append(destinazione)
            logger.info(f"Backup creato: {destinazione}")
        else:
            problemi.append(f"{os.path.basename(db_path)}: {esito}")
            logger.error(f"Backup di {db_path} NON riuscito: {esito}")
        _pulisci(backup_dir, os.path.splitext(os.path.basename(db_path))[0], ".db")

    # Domenica: archivio dei PDF delle etichette (registro di legge, non stanno nei database)
    if adesso.weekday() == 6:
        cartella_pdf = os.path.join(os.path.dirname(db_principale), "prodotti", "etichette")
        archivio = os.path.join(backup_dir, f"etichette_backup_{adesso.strftime('%Y%m%d_%H%M%S')}.tar.gz")
        try:
            if archivia_cartella(cartella_pdf, archivio):
                logger.info(f"Archivio etichette creato: {archivio}")
                _pulisci(backup_dir, "etichette", ".tar.gz")
        except Exception as e:
            problemi.append(f"etichette PDF: {e}")

    try:
        _send_backup_email(riusciti)
        logger.info("Email backup completato.")
    except Exception as e:
        logger.error(f"Invio email backup fallito: {e}")

    try:
        from app.services.telegram_bot import send_telegram_message
        nomi = ", ".join(os.path.basename(p) for p in riusciti) or "nessun file"
        testo = f"Backup completato: {nomi}"
        if problemi:
            testo = "⚠️ Backup con problemi: " + "; ".join(problemi) + f"\nRiusciti: {nomi}"
        send_telegram_message(testo, canale="sistema")
    except Exception:
        pass


def _backup_dir():
    return os.path.join(current_app.root_path, "..", "backups")


def _pulisci(backup_dir, prefisso, estensione):
    """Applica la regola 7 giornalieri + 12 mensili ai backup di un database."""
    nomi = [f for f in os.listdir(backup_dir)
            if f.startswith(f"{prefisso}_backup_") and f.endswith(estensione)]
    for nome in backup_da_eliminare(nomi):
        os.remove(os.path.join(backup_dir, nome))


def _should_run_backup():
    """Controlla se il backup deve essere eseguito in base alla frequenza configurata."""
    try:
        from app.models import Setting
        freq_setting = Setting.query.get("backup_frequency_days")
        frequency_days = int(freq_setting.value) if freq_setting else 1
        if frequency_days <= 1:
            return True

        backup_dir = _backup_dir()
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


def _send_backup_email(percorsi):
    """Invia i file di backup come allegati di un'unica email (entro LIMITE_ALLEGATI_BYTE)."""
    if not percorsi:
        return
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

    allegati, esclusi, totale = [], [], 0
    for p in percorsi:
        dim = os.path.getsize(p)
        if totale + dim <= LIMITE_ALLEGATI_BYTE:
            allegati.append(p)
            totale += dim
        else:
            esclusi.append(os.path.basename(p))

    testo = (
        "Backup automatico del gestionale Ca Bianca.\n\n"
        + "".join(f"File: {os.path.basename(p)}\n" for p in allegati)
        + f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
    )
    if esclusi:
        testo += "\nTroppo grandi per l'email, restano solo sul server in backups/: " + ", ".join(esclusi) + "\n"
    msg.set_content(testo)

    for p in allegati:
        with open(p, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="octet-stream",
                filename=os.path.basename(p),
            )

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)
