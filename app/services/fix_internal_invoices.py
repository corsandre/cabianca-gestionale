"""Migrazione: corregge le fatture interne esistenti creando la doppia registrazione."""

import logging
from app import db
from app.models import SdiInvoice, Transaction, Contact, Category, RevenueStream
from app.config import Config

logger = logging.getLogger(__name__)


def fix_internal_invoices() -> dict:
    """Trova fatture interne (sender_piva == COMPANY_PIVA) e crea le transazioni mancanti.

    Returns:
        {"fixed": int, "skipped": int, "errors": list}
    """
    company_piva = Config.COMPANY_PIVA
    results = {"fixed": 0, "skipped": 0, "errors": []}

    # Find all invoices where sender is Ca Bianca
    invoices = SdiInvoice.query.filter_by(sender_partita_iva=company_piva).all()

    if not invoices:
        return results

    # Get category and revenue streams
    cat = Category.query.filter_by(name="Trasferimento interno").first()
    if not cat:
        cat = Category(name="Trasferimento interno", type="entrambi", color="#17a2b8")
        db.session.add(cat)
        db.session.flush()

    stream_vendita = RevenueStream.query.filter_by(name="Vendita diretta").first()
    stream_agriturismo = RevenueStream.query.filter_by(name="Agriturismo").first()

    # Ensure self-contact exists
    self_contact = Contact.query.filter_by(partita_iva=company_piva).first()
    if not self_contact:
        self_contact = Contact(
            type="cliente_b2b",
            name="Fattoria Ca' Bianca",
            partita_iva=company_piva,
        )
        db.session.add(self_contact)
        db.session.flush()

    for inv in invoices:
        try:
            # Update direction
            if inv.direction != "interna":
                inv.direction = "interna"

            # Check existing transactions
            existing_txs = Transaction.query.filter_by(invoice_id=inv.id).all()
            has_entrata = any(t.type == "entrata" for t in existing_txs)
            has_uscita = any(t.type == "uscita" for t in existing_txs)

            if has_entrata and has_uscita:
                results["skipped"] += 1
                continue

            # IVA rate
            iva_rate = 0
            if inv.taxable_amount and inv.taxable_amount > 0:
                iva_rate = round(inv.iva_amount / inv.taxable_amount * 100, 0)

            # Update existing transaction(s) with correct category and description
            for tx in existing_txs:
                tx.category_id = cat.id
                tx.contact_id = self_contact.id
                tx.payment_status = "pagato"
                if tx.type == "entrata":
                    tx.description = f"Fattura interna {inv.invoice_number} - Vendita a Agriturismo"
                    tx.revenue_stream_id = stream_vendita.id if stream_vendita else None
                elif tx.type == "uscita":
                    tx.description = f"Fattura interna {inv.invoice_number} - Acquisto da Azienda Agricola"
                    tx.revenue_stream_id = stream_agriturismo.id if stream_agriturismo else None

            # Create missing entrata
            if not has_entrata:
                tx_entrata = Transaction(
                    type="entrata",
                    source="sdi",
                    official=True,
                    amount=inv.total_amount,
                    iva_amount=inv.iva_amount,
                    net_amount=inv.taxable_amount,
                    iva_rate=iva_rate,
                    date=inv.invoice_date,
                    description=f"Fattura interna {inv.invoice_number} - Vendita a Agriturismo",
                    contact_id=self_contact.id,
                    invoice_id=inv.id,
                    category_id=cat.id,
                    revenue_stream_id=stream_vendita.id if stream_vendita else None,
                    payment_status="pagato",
                )
                db.session.add(tx_entrata)

            # Create missing uscita
            if not has_uscita:
                tx_uscita = Transaction(
                    type="uscita",
                    source="sdi",
                    official=True,
                    amount=inv.total_amount,
                    iva_amount=inv.iva_amount,
                    net_amount=inv.taxable_amount,
                    iva_rate=iva_rate,
                    date=inv.invoice_date,
                    description=f"Fattura interna {inv.invoice_number} - Acquisto da Azienda Agricola",
                    contact_id=self_contact.id,
                    invoice_id=inv.id,
                    category_id=cat.id,
                    revenue_stream_id=stream_agriturismo.id if stream_agriturismo else None,
                    payment_status="pagato",
                )
                db.session.add(tx_uscita)

            results["fixed"] += 1

        except Exception as e:
            logger.error(f"Errore fix fattura {inv.invoice_number}: {e}")
            results["errors"].append(f"{inv.invoice_number}: {e}")

    db.session.commit()
    return results
