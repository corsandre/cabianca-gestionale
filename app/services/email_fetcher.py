"""Recupero automatico fatture SDI via email IMAP."""

import email
import imaplib
import logging
import subprocess
import tempfile
from email.header import decode_header

from app import db
from app.services.sdi_importer import import_sdi_file
from app.services.telegram_bot import send_telegram_message

logger = logging.getLogger(__name__)

ARCHIVE_FOLDER = '"INBOX.TEAM SYSTEM"'


def extract_xml_from_p7m(p7m_data: bytes) -> bytes:
    """Estrae il contenuto XML da una busta PKCS#7 (.p7m) usando openssl."""
    with tempfile.NamedTemporaryFile(suffix=".p7m", delete=True) as tmp_in:
        tmp_in.write(p7m_data)
        tmp_in.flush()
        try:
            result = subprocess.run(
                ["openssl", "smime", "-verify", "-noverify", "-in", tmp_in.name, "-inform", "DER"],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
            result = subprocess.run(
                ["openssl", "smime", "-verify", "-noverify", "-in", tmp_in.name, "-inform", "PEM"],
                capture_output=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout:
                return result.stdout
        except subprocess.TimeoutExpired:
            logger.error("Timeout estrazione P7M")
        except Exception as e:
            logger.error(f"Errore estrazione P7M: {e}")
    return b""


def _decode_header_value(value):
    """Decodifica un header email."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def fetch_sdi_emails(app) -> dict:
    """Recupera fatture SDI dagli allegati email via IMAP.

    - Prima esecuzione: scansiona anche la cartella archivio (TEAM SYSTEM) per lo storico
    - Esecuzioni successive: solo INBOX, email non lette
    - Dopo il processing, sposta le email da INBOX a TEAM SYSTEM

    Returns:
        {"imported": N, "duplicates": N, "errors": N}
    """
    stats = {"imported": 0, "duplicates": 0, "errors": 0}

    host = app.config.get("IMAP_HOST", "")
    port = app.config.get("IMAP_PORT", 993)
    user = app.config.get("IMAP_USER", "")
    password = app.config.get("IMAP_PASSWORD", "")
    search_from = app.config.get("IMAP_SEARCH_FROM", "")

    if not host or not user or not password:
        logger.debug("IMAP non configurato, skip.")
        return stats

    mail = None
    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)

        from app.models import SdiInvoice
        first_run = SdiInvoice.query.count() == 0

        # Prima esecuzione: importa storico dalla cartella archivio
        if first_run:
            logger.info("Prima esecuzione: recupero storico da TEAM SYSTEM.")
            _process_folder(mail, ARCHIVE_FOLDER, search_from, stats, move_to=None, search_all=True)
            db.session.commit()

        # Sempre: controlla INBOX per nuove email
        _process_folder(mail, "INBOX", search_from, stats, move_to=ARCHIVE_FOLDER, search_all=first_run)
        db.session.commit()

    except imaplib.IMAP4.error as e:
        logger.error(f"Errore IMAP: {e}")
        stats["errors"] += 1
    except Exception as e:
        logger.error(f"Errore connessione email: {e}")
        stats["errors"] += 1
    finally:
        if mail:
            try:
                mail.logout()
            except Exception:
                pass

    logger.info(f"Email fetch completato: {stats}")

    if stats["imported"] > 0:
        msg = (
            f"<b>Fatture SDI da email</b>\n"
            f"Importate: {stats['imported']}\n"
            f"Duplicati: {stats['duplicates']}\n"
            f"Errori: {stats['errors']}"
        )
        send_telegram_message(msg)

    return stats


def _process_folder(mail, folder, search_from, stats, move_to=None, search_all=False):
    """Elabora una cartella IMAP cercando fatture SDI."""
    mail.select(folder)

    if search_from:
        if search_all:
            search_criteria = f'(FROM "{search_from}")'
        else:
            search_criteria = f'(UNSEEN FROM "{search_from}")'
    else:
        search_criteria = "ALL" if search_all else "(UNSEEN)"

    status, msg_ids = mail.search(None, search_criteria)
    if status != "OK" or not msg_ids[0]:
        logger.info(f"Nessuna email trovata in {folder}.")
        return

    id_list = msg_ids[0].split()
    logger.info(f"Trovate {len(id_list)} email in {folder}.")

    for msg_id in id_list:
        try:
            found = _process_email(mail, msg_id, stats)
            # Sposta email da INBOX ad archivio dopo il processing
            if found and move_to:
                mail.copy(msg_id, move_to)
                mail.store(msg_id, "+FLAGS", "\\Deleted")
        except Exception as e:
            logger.error(f"Errore elaborazione email {msg_id}: {e}")
            stats["errors"] += 1

    # Espunge le email marcate per cancellazione (spostate)
    if move_to:
        try:
            mail.expunge()
        except Exception:
            pass


def _process_email(mail, msg_id, stats) -> bool:
    """Elabora una singola email cercando allegati fattura (XML, P7M, PDF).

    Returns:
        True se ha trovato e processato allegati fattura.
    """
    status, msg_data = mail.fetch(msg_id, "(RFC822)")
    if status != "OK":
        return False

    raw_email = msg_data[0][1]
    msg = email.message_from_bytes(raw_email)
    subject = _decode_header_value(msg.get("Subject", ""))
    logger.info(f"Elaboro email: {subject}")

    found = False
    for part in msg.walk():
        content_disposition = str(part.get("Content-Disposition", ""))
        if "attachment" not in content_disposition:
            continue

        filename = part.get_filename()
        if not filename:
            continue
        filename = _decode_header_value(filename)
        filename_lower = filename.lower()

        # Allegati: .xml, .xml.p7m, .xml.pdf (rendering TeamSystem)
        is_xml = filename_lower.endswith(".xml")
        is_p7m = filename_lower.endswith(".xml.p7m")
        is_pdf = filename_lower.endswith(".xml.pdf") or filename_lower.endswith(".pdf")

        if not (is_xml or is_p7m or is_pdf):
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        # Determina il contenuto da importare
        if is_p7m:
            content = extract_xml_from_p7m(payload)
            if not content:
                logger.warning(f"Impossibile estrarre XML da {filename}")
                stats["errors"] += 1
                continue
            filename = filename[:-4]  # rimuovi .p7m
        else:
            content = payload

        result = import_sdi_file(content, filename)
        if result["status"] == "imported":
            stats["imported"] += 1
            found = True
        elif result["status"] == "duplicate":
            stats["duplicates"] += 1
            found = True
        else:
            stats["errors"] += 1
            logger.warning(f"Errore import {filename}: {result['message']}")

    return found
