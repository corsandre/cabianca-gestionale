"""Parser for Italian FatturaPA XML (SDI electronic invoices)."""

from datetime import date
from lxml import etree
from app.config import Config

# FatturaPA namespace
NS = {"p": "http://ivaservizi.agenziaentrate.gov.it/docs/xsd/fatture/v1.2"}


def parse_fattura_xml(xml_content: bytes) -> dict:
    """Parse a FatturaPA XML and return structured data.

    Handles both namespace-prefixed and non-prefixed XML.
    """
    root = etree.fromstring(xml_content)

    # Detect namespace usage
    nsmap = root.nsmap
    ns = ""
    if None in nsmap:
        ns = f"{{{nsmap[None]}}}"
    elif "p" in nsmap:
        ns = f"{{{nsmap['p']}}}"

    # Helper to find element text
    def find(parent, path):
        """Find element by local name path (dot-separated)."""
        el = parent
        for part in path.split("."):
            if el is None:
                return None
            # Try with namespace first, then without
            found = el.find(f"{ns}{part}")
            if found is None:
                found = el.find(part)
            if found is None:
                # Try searching all children by local name
                for child in el:
                    local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if local == part:
                        found = child
                        break
            el = found
        return el.text if el is not None and el.text else ""

    def find_el(parent, path):
        """Find element node (not text)."""
        el = parent
        for part in path.split("."):
            if el is None:
                return None
            found = el.find(f"{ns}{part}")
            if found is None:
                found = el.find(part)
            if found is None:
                for child in el:
                    local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if local == part:
                        found = child
                        break
            el = found
        return el

    # Header
    header = find_el(root, "FatturaElettronicaHeader")

    # Sender (CedentePrestatore)
    sender = find_el(header, "CedentePrestatore")
    sender_name = find(sender, "DatiAnagrafici.Anagrafica.Denominazione")
    if not sender_name:
        nome = find(sender, "DatiAnagrafici.Anagrafica.Nome") or ""
        cognome = find(sender, "DatiAnagrafici.Anagrafica.Cognome") or ""
        sender_name = f"{nome} {cognome}".strip()
    sender_piva = find(sender, "DatiAnagrafici.IdFiscaleIVA.IdCodice")
    sender_cf = find(sender, "DatiAnagrafici.CodiceFiscale")

    # Receiver (CessionarioCommittente)
    receiver = find_el(header, "CessionarioCommittente")
    receiver_name = find(receiver, "DatiAnagrafici.Anagrafica.Denominazione")
    if not receiver_name:
        nome = find(receiver, "DatiAnagrafici.Anagrafica.Nome") or ""
        cognome = find(receiver, "DatiAnagrafici.Anagrafica.Cognome") or ""
        receiver_name = f"{nome} {cognome}".strip()
    receiver_piva = find(receiver, "DatiAnagrafici.IdFiscaleIVA.IdCodice")

    # Body (first body - most invoices have one)
    body = find_el(root, "FatturaElettronicaBody")

    # General data
    invoice_number = find(body, "DatiGenerali.DatiGeneraliDocumento.Numero")
    invoice_date_str = find(body, "DatiGenerali.DatiGeneraliDocumento.Data")
    tipo_doc = find(body, "DatiGenerali.DatiGeneraliDocumento.TipoDocumento")

    try:
        invoice_date = date.fromisoformat(invoice_date_str) if invoice_date_str else None
    except (ValueError, TypeError):
        invoice_date = None

    # Determine invoice type
    invoice_type = "fattura"
    if tipo_doc in ("TD04", "TD08"):
        invoice_type = "nota_credito"

    # Amounts from DatiRiepilogo (summary by IVA rate)
    riepilogo_els = []
    dati_beni = find_el(body, "DatiBeniServizi")
    if dati_beni is not None:
        for child in dati_beni:
            local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if local == "DatiRiepilogo":
                riepilogo_els.append(child)

    taxable_amount = 0.0
    iva_amount = 0.0
    for riepilogo in riepilogo_els:
        imp = find(riepilogo, "ImponibileImporto")
        imposta = find(riepilogo, "Imposta")
        try:
            taxable_amount += float(imp) if imp else 0
        except (ValueError, TypeError):
            pass
        try:
            iva_amount += float(imposta) if imposta else 0
        except (ValueError, TypeError):
            pass

    total_amount = taxable_amount + iva_amount

    # If no riepilogo, try ImportoTotaleDocumento
    if total_amount == 0:
        total_str = find(body, "DatiGenerali.DatiGeneraliDocumento.ImportoTotaleDocumento")
        try:
            total_amount = float(total_str) if total_str else 0
        except (ValueError, TypeError):
            total_amount = 0

    # Payment due date from DatiPagamento/DettaglioPagamento/DataScadenzaPagamento
    due_date = None
    dati_pagamento = find_el(body, "DatiPagamento")
    if dati_pagamento is not None:
        due_date_str = find(dati_pagamento, "DettaglioPagamento.DataScadenzaPagamento")
        if due_date_str:
            try:
                due_date = date.fromisoformat(due_date_str)
            except (ValueError, TypeError):
                due_date = None

    # Determine direction based on P.IVA
    company_piva = Config.COMPANY_PIVA
    if sender_piva == company_piva and receiver_piva == company_piva:
        direction = "interna"
    elif sender_piva == company_piva:
        direction = "emessa"
    else:
        direction = "ricevuta"

    return {
        "invoice_number": invoice_number or "",
        "invoice_date": invoice_date,
        "sender_name": sender_name or "",
        "sender_partita_iva": sender_piva or "",
        "sender_codice_fiscale": sender_cf or "",
        "receiver_name": receiver_name or "",
        "receiver_partita_iva": receiver_piva or "",
        "total_amount": round(total_amount, 2),
        "taxable_amount": round(taxable_amount, 2),
        "iva_amount": round(iva_amount, 2),
        "invoice_type": invoice_type,
        "direction": direction,
        "tipo_documento": tipo_doc or "",
        "due_date": due_date,
    }
