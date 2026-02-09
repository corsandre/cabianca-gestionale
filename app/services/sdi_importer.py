"""Shared SDI import logic for Ca Bianca Gestionale (XML and PDF)."""

import os
import logging
from flask import current_app
from werkzeug.utils import secure_filename
from app import db
from app.models import SdiInvoice, Transaction, Contact, Category, RevenueStream
from app.services.sdi_parser import parse_fattura_xml
from app.config import Config

logger = logging.getLogger(__name__)


def import_sdi_file(content: bytes, filename: str, uploaded_by: int = None) -> dict:
    """Importa una fattura SDI da XML o PDF.

    Args:
        content: Contenuto del file (XML o PDF)
        filename: Nome del file originale
        uploaded_by: ID utente (opzionale, None per import automatico)

    Returns:
        {"status": "imported"|"duplicate"|"error", "message": "..."}
    """
    try:
        safe_fn = secure_filename(filename)
        filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], safe_fn)
        with open(filepath, "wb") as f:
            f.write(content)

        # Scegli il parser in base al tipo di file
        if filename.lower().endswith(".pdf") or content[:5] == b"%PDF-":
            from app.services.pdf_parser import parse_fattura_pdf
            data = parse_fattura_pdf(content)
        else:
            data = parse_fattura_xml(content)

        # Check duplicate
        existing = SdiInvoice.query.filter_by(
            invoice_number=data["invoice_number"],
            sender_partita_iva=data["sender_partita_iva"],
            invoice_date=data["invoice_date"],
        ).first()
        if existing:
            return {"status": "duplicate", "message": f"Fattura {data['invoice_number']} gia presente."}

        invoice = SdiInvoice(
            xml_filename=safe_fn,
            xml_path=filepath,
            invoice_number=data["invoice_number"],
            invoice_date=data["invoice_date"],
            sender_name=data["sender_name"],
            sender_partita_iva=data["sender_partita_iva"],
            sender_codice_fiscale=data.get("sender_codice_fiscale", ""),
            receiver_name=data["receiver_name"],
            receiver_partita_iva=data["receiver_partita_iva"],
            total_amount=data["total_amount"],
            taxable_amount=data["taxable_amount"],
            iva_amount=data["iva_amount"],
            invoice_type=data["invoice_type"],
            direction=data["direction"],
            parsed_data=str(data),
            uploaded_by=uploaded_by,
        )
        db.session.add(invoice)
        db.session.flush()

        # Auto-create or find contact
        contact = Contact.query.filter_by(
            partita_iva=data["sender_partita_iva"]
        ).first()
        if not contact and data["sender_partita_iva"]:
            contact = Contact(
                type="fornitore" if data["direction"] == "ricevuta" else "cliente_b2b",
                name=data["sender_name"],
                partita_iva=data["sender_partita_iva"],
                codice_fiscale=data.get("sender_codice_fiscale", ""),
            )
            db.session.add(contact)
            db.session.flush()

        # IVA rate
        iva_rate = 0
        if data["taxable_amount"] and data["taxable_amount"] > 0:
            iva_rate = round(data["iva_amount"] / data["taxable_amount"] * 100, 0)

        if data["direction"] == "interna":
            # Internal invoice: create both entrata and uscita
            cat = Category.query.filter_by(name="Trasferimento interno").first()
            cat_id = cat.id if cat else None

            stream_vendita = RevenueStream.query.filter_by(name="Vendita diretta").first()
            stream_agriturismo = RevenueStream.query.filter_by(name="Agriturismo").first()

            # Ensure self-contact exists
            self_contact = Contact.query.filter_by(
                partita_iva=Config.COMPANY_PIVA
            ).first()
            if not self_contact:
                self_contact = Contact(
                    type="cliente_b2b",
                    name="Fattoria Ca' Bianca",
                    partita_iva=Config.COMPANY_PIVA,
                )
                db.session.add(self_contact)
                db.session.flush()

            # Entrata: vendita dell'azienda agricola all'agriturismo
            tx_entrata = Transaction(
                type="entrata",
                source="sdi",
                official=True,
                amount=data["total_amount"],
                iva_amount=data["iva_amount"],
                net_amount=data["taxable_amount"],
                iva_rate=iva_rate,
                date=data["invoice_date"],
                description=f"Fattura interna {data['invoice_number']} - Vendita a Agriturismo",
                contact_id=self_contact.id,
                invoice_id=invoice.id,
                category_id=cat_id,
                revenue_stream_id=stream_vendita.id if stream_vendita else None,
                payment_status="pagato",
                due_date=data.get("due_date"),
                created_by=uploaded_by,
            )
            db.session.add(tx_entrata)

            # Uscita: acquisto dell'agriturismo dall'azienda agricola
            tx_uscita = Transaction(
                type="uscita",
                source="sdi",
                official=True,
                amount=data["total_amount"],
                iva_amount=data["iva_amount"],
                net_amount=data["taxable_amount"],
                iva_rate=iva_rate,
                date=data["invoice_date"],
                description=f"Fattura interna {data['invoice_number']} - Acquisto da Azienda Agricola",
                contact_id=self_contact.id,
                invoice_id=invoice.id,
                category_id=cat_id,
                revenue_stream_id=stream_agriturismo.id if stream_agriturismo else None,
                payment_status="pagato",
                due_date=data.get("due_date"),
                created_by=uploaded_by,
            )
            db.session.add(tx_uscita)

            return {"status": "imported", "message": f"Fattura interna {data['invoice_number']} importata (entrata + uscita)."}
        else:
            # Normal invoice: single transaction
            tx = Transaction(
                type="uscita" if data["direction"] == "ricevuta" else "entrata",
                source="sdi",
                official=True,
                amount=data["total_amount"],
                iva_amount=data["iva_amount"],
                net_amount=data["taxable_amount"],
                iva_rate=iva_rate,
                date=data["invoice_date"],
                description=f"Fattura {data['invoice_number']} - {data['sender_name']}",
                contact_id=contact.id if contact else None,
                invoice_id=invoice.id,
                payment_status="da_pagare",
                due_date=data.get("due_date"),
                created_by=uploaded_by,
            )
            db.session.add(tx)

            return {"status": "imported", "message": f"Fattura {data['invoice_number']} importata."}

    except Exception as e:
        logger.error(f"Errore import {filename}: {e}")
        return {"status": "error", "message": str(e)}


# Alias per retrocompatibilita'
import_sdi_xml = import_sdi_file
