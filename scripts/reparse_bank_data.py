#!/usr/bin/env python3
"""Re-parsing dati bancari esistenti con parser CBI aggiornato.

Aggiorna description, counterpart_name, causale_description per ogni
BankTransaction esistente, ri-parsando raw_data. NON tocca:
status, matched_transaction_id, matched_by, matched_rule_id, ignore_reason_id.

Uso:
    cd /path/to/cabianca-gestionale
    python scripts/reparse_bank_data.py [--dry-run]
"""

import os
import sys
import shutil
import hashlib
import logging
from datetime import datetime

# Aggiungi la root del progetto al path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import create_app, db
from app.models import BankTransaction
from app.services.cbi_parser import _build_transaction, _get_causale_abi_description

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def backup_db(app):
    """Crea backup del database."""
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not db_uri.startswith("sqlite:///"):
        logger.warning("Non SQLite, skip backup")
        return None

    db_path = db_uri.replace("sqlite:///", "")
    if not os.path.exists(db_path):
        logger.warning(f"DB non trovato: {db_path}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{db_path}.backup.{timestamp}"
    shutil.copy2(db_path, backup_path)
    size_mb = os.path.getsize(backup_path) / 1024 / 1024
    logger.info(f"Backup creato: {backup_path} ({size_mb:.1f} MB)")
    return backup_path


def reparse_transaction(bt):
    """Ri-parsa una singola BankTransaction e restituisce i campi aggiornati."""
    if not bt.raw_data:
        return None

    lines = bt.raw_data.split("\n")
    if not lines:
        return None

    line_62 = lines[0] if lines[0].lstrip(" ")[:2] == "62" else None
    if not line_62:
        return None

    lines_63 = [l for l in lines[1:] if l.lstrip(" ")[:2] == "63"]

    # Ri-parsa con il parser aggiornato
    tx_data = _build_transaction(line_62.lstrip(" "), [l.lstrip(" ") for l in lines_63], bt.operation_date)
    if not tx_data:
        return None

    return tx_data


def main():
    dry_run = "--dry-run" in sys.argv

    app = create_app()

    with app.app_context():
        if not dry_run:
            backup_db(app)

        total = BankTransaction.query.count()
        logger.info(f"Totale transazioni bancarie: {total}")

        all_bt = BankTransaction.query.all()
        updated = 0
        errors = 0
        changes_log = []

        # Raccogli tutti i dedup_hash esistenti per verifica collisioni
        existing_hashes = {}
        for bt in all_bt:
            if bt.dedup_hash:
                existing_hashes[bt.dedup_hash] = bt.id

        for bt in all_bt:
            try:
                tx_data = reparse_transaction(bt)
                if not tx_data:
                    continue

                changes = []

                # Aggiorna description
                new_desc = tx_data.get("description", "")
                if (bt.description or "") != new_desc:
                    changes.append(f"  description: '{bt.description or ''}' -> '{new_desc[:80]}'")
                    if not dry_run:
                        bt.description = new_desc

                # Aggiorna counterpart_name
                new_cp = tx_data.get("counterpart_name", "")
                if (bt.counterpart_name or "") != new_cp:
                    changes.append(f"  counterpart_name: '{bt.counterpart_name or ''}' -> '{new_cp}'")
                    if not dry_run:
                        bt.counterpart_name = new_cp

                # Aggiorna causale_description
                new_cd = tx_data.get("causale_description", "")
                if (bt.causale_description or "") != new_cd:
                    changes.append(f"  causale_description: '{bt.causale_description or ''}' -> '{new_cd}'")
                    if not dry_run:
                        bt.causale_description = new_cd

                # Ricalcola dedup_hash
                new_hash = tx_data.get("dedup_hash", "")
                if new_hash and new_hash != bt.dedup_hash:
                    # Verifica collisioni
                    if new_hash in existing_hashes and existing_hashes[new_hash] != bt.id:
                        logger.warning(
                            f"  COLLISIONE hash per bt#{bt.id}: nuovo hash {new_hash} "
                            f"gia' usato da bt#{existing_hashes[new_hash]}. Skip hash update."
                        )
                    else:
                        changes.append(f"  dedup_hash: '{bt.dedup_hash}' -> '{new_hash}'")
                        if not dry_run:
                            # Aggiorna mappa
                            if bt.dedup_hash in existing_hashes:
                                del existing_hashes[bt.dedup_hash]
                            existing_hashes[new_hash] = bt.id
                            bt.dedup_hash = new_hash

                if changes:
                    updated += 1
                    header = (
                        f"bt#{bt.id} | {bt.operation_date} | "
                        f"{'C' if bt.direction == 'C' else 'D'} {bt.amount} | "
                        f"{bt.causale_abi}"
                    )
                    changes_log.append(header)
                    changes_log.extend(changes)

            except Exception as e:
                errors += 1
                logger.error(f"Errore bt#{bt.id}: {e}")

        # Log riepilogo
        logger.info(f"\n{'='*60}")
        logger.info(f"{'DRY RUN - ' if dry_run else ''}Riepilogo re-parsing:")
        logger.info(f"  Totale: {total}")
        logger.info(f"  Aggiornati: {updated}")
        logger.info(f"  Errori: {errors}")
        logger.info(f"{'='*60}")

        if changes_log:
            logger.info("\nDettaglio modifiche:")
            for line in changes_log:
                logger.info(line)

        # Verifica integrita'
        matched_count = BankTransaction.query.filter(
            BankTransaction.matched_transaction_id.isnot(None)
        ).count()
        ignored_count = BankTransaction.query.filter_by(status="ignorato").count()
        pending_count = BankTransaction.query.filter_by(status="non_riconciliato").count()
        logger.info(f"\nIntegrita':")
        logger.info(f"  Riconciliati (con match): {matched_count}")
        logger.info(f"  Ignorati: {ignored_count}")
        logger.info(f"  Sospesi: {pending_count}")

        if not dry_run:
            db.session.commit()
            logger.info("\nCommit completato.")
        else:
            logger.info("\nDRY RUN: nessuna modifica salvata.")


if __name__ == "__main__":
    main()
