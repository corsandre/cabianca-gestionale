"""Parser per fatture SDI in formato PDF (rendering TeamSystem)."""

import re
import logging
from datetime import datetime

import pdfplumber
from app.config import Config

logger = logging.getLogger(__name__)

CA_BIANCA_PIVA = Config.COMPANY_PIVA


def parse_fattura_pdf(pdf_content: bytes) -> dict:
    """Estrae i dati di una fattura SDI da un PDF TeamSystem.

    Args:
        pdf_content: Contenuto PDF grezzo (bytes)

    Returns:
        dict con le stesse chiavi di parse_fattura_xml() per compatibilita'
    """
    import io

    text = ""
    with pdfplumber.open(io.BytesIO(pdf_content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text += t + "\n"

    if not text.strip():
        raise ValueError("PDF vuoto o non leggibile")

    # P.IVA
    piva_matches = re.findall(
        r"Identificativo fiscale ai fini IVA:\s*(IT\w+)", text
    )
    sender_piva = ""
    receiver_piva = ""
    for p in piva_matches:
        piva_num = p[2:]  # rimuovi "IT"
        if not sender_piva:
            sender_piva = piva_num
        elif piva_num == CA_BIANCA_PIVA:
            receiver_piva = piva_num
        elif not receiver_piva:
            receiver_piva = piva_num

    # Codice fiscale del cedente (primo trovato, diverso da Ca Bianca)
    cf_matches = re.findall(r"Codice fiscale:\s*(\w+)", text)
    sender_cf = ""
    for cf in cf_matches:
        if cf != CA_BIANCA_PIVA and cf != sender_piva:
            sender_cf = cf
            break
        elif cf == sender_piva:
            sender_cf = cf
            break

    # Denominazioni
    denom_matches = re.findall(
        r"Denominazione:\s*(.+?)(?=\s+(?:Indirizzo|Regime\s+fiscale|Denominazione|Codice\s+\w+|Cognome\s+nome|Cap|Comune|Pec|Riferimento):|$)",
        text,
    )
    sender_name = ""
    receiver_name = ""
    is_internal = sender_piva == CA_BIANCA_PIVA and receiver_piva == CA_BIANCA_PIVA
    for d in denom_matches:
        d = d.strip()
        d_upper = d.upper().replace("'", " ").replace("\u2019", " ")
        if "FATTORIA CA" in d_upper or "CA BIANCA" in d_upper:
            if not sender_name and is_internal:
                sender_name = d
            elif not receiver_name:
                receiver_name = d
        elif not sender_name:
            sender_name = d

    # Fallback per persone fisiche: "Cognome nome:" (formato TeamSystem)
    if not sender_name:
        cn_matches = re.findall(
            r"Cognome nome:\s*(.+?)(?=\s+(?:Denominazione|Indirizzo|Regime\s+fiscale|Codice\s+\w+|Cap|Comune|Pec|Riferimento):|$)",
            text,
        )
        if cn_matches:
            sender_name = cn_matches[0].strip()

    if not receiver_name:
        receiver_name = "FATTORIA CA' BIANCA"
    if is_internal and not sender_name:
        sender_name = "FATTORIA CA' BIANCA"

    # Tipo documento, numero, data
    doc_match = re.search(
        r"(TD\d+)\s*\([^)]+\)\s+(.+?)\s+(\d{2}-\d{2}-\d{4})", text
    )
    invoice_type = doc_match.group(1) if doc_match else ""
    invoice_number = doc_match.group(2).strip() if doc_match else ""
    invoice_date_str = doc_match.group(3) if doc_match else ""

    invoice_date = None
    if invoice_date_str:
        invoice_date = datetime.strptime(invoice_date_str, "%d-%m-%Y").date()

    # Importi in formato italiano: 1.500,00 | 330,00 | -5,00
    # Richiede la virgola decimale, cosi' non cattura codici come N2.2
    _IT_AMOUNT = r'-?\d{1,3}(?:\.\d{3})*,\d+'

    def _parse_it(s):
        return float(s.replace(".", "").replace(",", "."))

    # Riepilogo IVA
    taxable = 0.0
    iva = 0.0
    in_iva_section = False
    for line in text.split("\n"):
        if "RIEPILOGHI IVA" in line:
            in_iva_section = True
            continue
        if in_iva_section and "TOTALI" in line:
            in_iva_section = False
            continue
        if in_iva_section and "Totale imponibile" not in line:
            amounts = re.findall(_IT_AMOUNT, line)
            has_trailing_zero = bool(re.search(r'\b0\s*$', line))
            try:
                if len(amounts) >= 2:
                    taxable += _parse_it(amounts[-2])
                    iva += _parse_it(amounts[-1])
                elif len(amounts) == 1 and has_trailing_zero:
                    taxable += _parse_it(amounts[0])
            except ValueError:
                pass

    # Totale documento - prende l'ultimo importo sulla riga
    total = 0.0
    total_match = re.search(r"Totale documento\s*\n\s*(.+)", text)
    if total_match:
        nums = re.findall(_IT_AMOUNT, total_match.group(1))
        if nums:
            total = _parse_it(nums[-1])
    else:
        totali_match = re.search(
            r"TOTALI.*?Totale documento\s*\n\s*(.+)",
            text,
            re.DOTALL,
        )
        if totali_match:
            nums = re.findall(_IT_AMOUNT, totali_match.group(1))
            if nums:
                total = _parse_it(nums[-1])

    if total == 0 and taxable > 0:
        total = round(taxable + iva, 2)

    # Data scadenza dalla sezione pagamento (es. "MP05 Bonifico ... 06-11-2025 1.830,00")
    due_date = None
    payment_match = re.search(
        r"MP\d+\s+.+?\s+(\d{2}-\d{2}-\d{4})\s+[\d.,]+",
        text,
    )
    if payment_match:
        try:
            due_date = datetime.strptime(payment_match.group(1), "%d-%m-%Y").date()
        except ValueError:
            due_date = None

    # Direction based on P.IVA
    if sender_piva == CA_BIANCA_PIVA and receiver_piva == CA_BIANCA_PIVA:
        direction = "interna"
    elif sender_piva == CA_BIANCA_PIVA:
        direction = "emessa"
    else:
        direction = "ricevuta"

    if not sender_piva and not invoice_number:
        raise ValueError("Impossibile estrarre dati dalla fattura PDF")

    return {
        "sender_name": sender_name,
        "sender_partita_iva": sender_piva,
        "sender_codice_fiscale": sender_cf,
        "receiver_name": receiver_name,
        "receiver_partita_iva": receiver_piva or CA_BIANCA_PIVA,
        "invoice_type": invoice_type,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "total_amount": round(total, 2),
        "taxable_amount": round(taxable, 2),
        "iva_amount": round(iva, 2),
        "direction": direction,
        "due_date": due_date,
    }
