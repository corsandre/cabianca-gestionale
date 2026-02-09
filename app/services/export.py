"""CSV/PDF export service for Ca Bianca Gestionale."""

import csv
import io
from flask import Response


def generate_csv(transactions):
    """Generate a CSV file response from a list of transactions."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    # Header
    writer.writerow([
        "Data", "Tipo", "Fonte", "Ufficiale", "Descrizione",
        "Contatto", "Categoria", "Flusso Ricavo",
        "Importo Lordo", "Imponibile", "IVA", "Aliquota IVA %",
        "Metodo Pagamento", "Stato Pagamento", "Scadenza", "Data Pagamento",
        "Note",
    ])

    for t in transactions:
        writer.writerow([
            t.date.strftime("%d/%m/%Y") if t.date else "",
            t.type,
            t.source,
            "Si" if t.official else "No",
            t.description or "",
            t.contact.name if t.contact else "",
            t.category.name if t.category else "",
            t.revenue_stream.name if t.revenue_stream else "",
            f"{t.amount:.2f}".replace(".", ","),
            f"{t.net_amount:.2f}".replace(".", ",") if t.net_amount else "",
            f"{t.iva_amount:.2f}".replace(".", ",") if t.iva_amount else "",
            f"{t.iva_rate:.0f}" if t.iva_rate else "",
            t.payment_method or "",
            t.payment_status or "",
            t.due_date.strftime("%d/%m/%Y") if t.due_date else "",
            t.payment_date.strftime("%d/%m/%Y") if t.payment_date else "",
            t.notes or "",
        ])

    response = Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=esportazione_movimenti.csv"},
    )
    return response
