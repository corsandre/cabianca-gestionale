"""Parser per file CBI (Corporate Banking Interbancario) a record fissi.

Formato CBI YouBusiness Web (con spazio iniziale su ogni riga):
- RH: Header giornata (data DDMMYY alla posizione 14-19 dopo strip)
- 61: Info conto, saldo apertura
- 62: Dettaglio transazione
- 63: Info aggiuntive (controparte, causale pagamento, riferimenti)
- 64: Saldo chiusura giornata
- 65: Saldi infragiornalieri
- EF: Footer

Posizioni record 62 (dopo strip spazio iniziale, 0-based):
    [0:2]   = "62" tipo record
    [2:9]   = Numero conto (7 cifre)
    [9:12]  = Progressivo operazione (3 cifre)
    [12:18] = Data operazione (DDMMYY)
    [18:24] = Data valuta (DDMMYY)
    [24:25] = Segno (C=credito, D=debito)
    [25:40] = Importo (15 char, formato 000000004377,96)
    [40:43] = Causale ABI (3 char)
    [43:60] = Riferimento banca (17 char)
    [60:]   = Descrizione

Posizioni record 63 (dopo strip spazio iniziale, 0-based):
    [0:2]   = "63" tipo record
    [2:9]   = Numero conto
    [9:12]  = Progressivo (uguale al 62 corrispondente)
    [12:15] = Tag info (YYY=controparte, ID1=riferimento, RI1=causale pagamento)
    [15:]   = Contenuto
"""

import hashlib
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def parse_cbi_file(content):
    """Parsa un file CBI e restituisce transazioni e saldi.

    Args:
        content: Contenuto del file CBI (bytes o str)

    Returns:
        dict con:
        - "transactions": Lista di dict con i dati di ogni transazione bancaria
        - "balances": Lista di dict con saldi estratti da record 61/64
    """
    if isinstance(content, bytes):
        for enc in ("utf-8", "latin-1", "cp1252"):
            try:
                text = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = content.decode("latin-1", errors="replace")
    else:
        text = content

    lines = text.splitlines()
    transactions = []
    balances = []
    current_62 = None
    current_63_lines = []
    header_date = None

    for raw_line in lines:
        # Rimuovi spazio iniziale presente in tutti i record CBI YouBusiness
        line = raw_line.lstrip(" ")

        if len(line) < 2:
            continue

        record_type = line[:2]

        if record_type == "RH":
            # Header giornata: data DDMMYY alla posizione 14-20
            if len(line) >= 20:
                date_str = line[14:20]
                header_date = _parse_cbi_date(date_str) or header_date

        elif record_type == "61":
            # Saldo apertura giornata
            bal = _parse_balance_record(line, "apertura", header_date)
            if bal:
                balances.append(bal)

        elif record_type == "62":
            # Salva il record 62 precedente se presente
            if current_62 is not None:
                tx = _build_transaction(current_62, current_63_lines, header_date)
                if tx:
                    transactions.append(tx)

            current_62 = line
            current_63_lines = []

        elif record_type == "63":
            current_63_lines.append(line)

        elif record_type == "64":
            # Saldo chiusura giornata + salva ultimo record 62
            if current_62 is not None:
                tx = _build_transaction(current_62, current_63_lines, header_date)
                if tx:
                    transactions.append(tx)
                current_62 = None
                current_63_lines = []

            bal = _parse_balance_record(line, "chiusura", header_date)
            if bal:
                balances.append(bal)

        elif record_type in ("65", "EF"):
            # Fine giornata/file: salva l'ultimo record 62
            if current_62 is not None:
                tx = _build_transaction(current_62, current_63_lines, header_date)
                if tx:
                    transactions.append(tx)
                current_62 = None
                current_63_lines = []

    # Ultimo record pendente
    if current_62 is not None:
        tx = _build_transaction(current_62, current_63_lines, header_date)
        if tx:
            transactions.append(tx)

    return {"transactions": transactions, "balances": balances}


def _parse_balance_record(line, balance_type, header_date):
    """Parsa un record 61 (apertura) o 64 (chiusura) per estrarre il saldo.

    Record 64 (chiusura) - posizioni fisse:
        [0:2]   = "64"
        [2:9]   = numero conto
        [9:12]  = valuta (EUR)
        [12:18] = data (DDMMYY)
        [18:19] = segno (C/D)
        [19:34] = importo (15 chars)

    Record 61 (apertura) - struttura diversa, il saldo e' dopo il marker EUR:
        ...EUR + DDMMYY + segno + importo (15 chars)
    """
    if len(line) < 34:
        return None
    try:
        record_type = line[0:2]

        if record_type == "64":
            # Posizioni fisse per record 64
            date_str = line[12:18]
            sign = line[18:19]
            amount_raw = line[19:34].strip()
        elif record_type == "61":
            # Record 61: cerco il marker EUR per trovare data e saldo
            eur_idx = line.find("EUR")
            if eur_idx < 0 or len(line) < eur_idx + 25:
                return None
            date_str = line[eur_idx + 3:eur_idx + 9]
            sign = line[eur_idx + 9:eur_idx + 10]
            amount_raw = line[eur_idx + 10:eur_idx + 25].strip()
        else:
            return None

        bal_date = _parse_cbi_date(date_str) or header_date
        if not bal_date:
            return None

        amount = _parse_italian_amount(amount_raw)
        if sign == "D":
            amount = -amount

        return {
            "date": bal_date,
            "balance": round(amount, 2),
            "type": balance_type,
        }
    except (ValueError, IndexError):
        return None


def _build_transaction(line_62, lines_63, header_date):
    """Costruisce un dict transazione da un record 62 e i suoi record 63."""
    if not line_62 or len(line_62) < 43:
        return None

    try:
        # Data operazione e valuta
        op_date_str = line_62[12:18]
        val_date_str = line_62[18:24]
        operation_date = _parse_cbi_date(op_date_str) or header_date
        value_date = _parse_cbi_date(val_date_str)

        if not operation_date:
            return None

        # Direzione
        direction = line_62[24:25]
        if direction not in ("C", "D"):
            return None

        # Importo: formato italiano 000000004377,96 (15 chars)
        amount_raw = line_62[25:40].strip()
        amount = _parse_italian_amount(amount_raw)
        if amount == 0:
            return None

        # Causale ABI (3 char)
        causale_abi = line_62[40:43].strip()

        # Riferimento banca
        reference_code = line_62[43:60].strip() if len(line_62) > 43 else ""

        # Descrizione dal record 62
        description = line_62[60:].strip() if len(line_62) > 60 else ""

        # Parse record 63
        counterpart_name = ""
        counterpart_address = ""
        ordinante_abi_cab = ""
        remittance_parts = []
        extra_parts = []

        for line_63 in lines_63:
            if len(line_63) < 15:
                # Riga 63 corta: potrebbe contenere testo libero
                text = line_63[12:].strip() if len(line_63) > 12 else ""
                if text:
                    extra_parts.append(text)
                continue

            tag = line_63[12:15]
            content = line_63[15:].strip()

            if tag == "YYY":
                # Nome e indirizzo controparte
                # Formato: YYYddmmyyyy              NOME                     INDIRIZZO
                # La data e' ai char 15-25, poi spazi, poi nome + indirizzo
                text_after_tag = line_63[15:]
                # Salta la data (10 char, formato ddmmyyyy + spazi)
                remaining = text_after_tag[10:].strip() if len(text_after_tag) > 10 else text_after_tag.strip()
                # Dividi nome e indirizzo: il nome occupa i primi ~40 char circa
                # Prendiamo tutto come una stringa e splittiamo dopo
                parts = remaining.split()
                if parts:
                    # Cerco di separare nome e indirizzo
                    # Tipicamente il nome e' nella prima meta, l'indirizzo nella seconda
                    full_text = remaining.strip()
                    # Se c'e' gia un nome, questa riga contiene l'indirizzo
                    if not counterpart_name:
                        # Prima riga YYY: nome (primi ~40 char) + indirizzo
                        # Cerchiamo il pattern: spazi multipli separano nome e indirizzo
                        import re
                        split = re.split(r"\s{3,}", full_text, maxsplit=1)
                        counterpart_name = split[0].strip()
                        if len(split) > 1:
                            counterpart_address = split[1].strip()
                    else:
                        counterpart_address += " " + full_text

            elif tag == "ID1":
                ref = content.strip()
                if ref and ref not in ("NOTPROVIDED", "NOT PROVIDED"):
                    reference_code = ref[:50]

            elif tag == "RI1" or tag == "RI2":
                if content:
                    remittance_parts.append(content)

            elif tag == "COD":
                # CODICE ABI/CAB ORDINANTE: 03475/01605
                full_text = line_63[12:].strip()
                import re
                m = re.search(r"(\d{5})/(\d{5})", full_text)
                if m:
                    ordinante_abi_cab = f"{m.group(1)}/{m.group(2)}"

            elif tag == "VS.":
                # Disposizione: VS.DISP. RIF. ... FAVORE  NOME_CONTROPARTE
                full_text = line_63[12:].strip()
                name = _extract_counterpart_from_text(full_text)
                if name and not counterpart_name:
                    counterpart_name = name
                extra_parts.append(full_text[:80])

            elif tag == "SDD":
                # SDD CORE/B2B: ... NOME_CONTROPARTE
                full_text = line_63[12:].strip()
                name = _extract_counterpart_from_text(full_text)
                if name and not counterpart_name:
                    counterpart_name = name
                extra_parts.append(full_text[:80])

            elif tag == "BOL":
                # BOLL.CBILL NOME_ENTE
                full_text = line_63[12:].strip()
                name = _extract_counterpart_from_text(full_text)
                if name and not counterpart_name:
                    counterpart_name = name
                extra_parts.append(full_text[:80])

            elif tag == "CAR":
                # CARTA*XXXX-HH:MM-NOME_ESERCENTE CITTA PAESE
                full_text = line_63[12:].strip()
                name = _extract_counterpart_from_text(full_text)
                if name and not counterpart_name:
                    counterpart_name = name
                extra_parts.append(full_text[:80])

            else:
                # Testo libero o tag sconosciuto
                full_line_text = line_63[12:].strip()
                if full_line_text:
                    # Controlla se contiene RI1, ID1 nel testo
                    if "RI1" in full_line_text:
                        idx = full_line_text.find("RI1")
                        remittance_parts.append(full_line_text[idx + 3:].strip())
                    elif "ID1" in full_line_text:
                        idx = full_line_text.find("ID1")
                        ref = full_line_text[idx + 3:].strip()
                        if ref and ref not in ("NOTPROVIDED", "NOT PROVIDED"):
                            reference_code = ref[:50]
                    elif full_line_text.startswith("CODICE ABI"):
                        pass  # Ignora
                    else:
                        # Estrai controparte da testo libero
                        name = _extract_counterpart_from_text(full_line_text)
                        if name and not counterpart_name:
                            counterpart_name = name
                        extra_parts.append(full_line_text[:80])

        # Fallback: se non abbiamo controparte, prova a estrarla dalla descrizione del 62
        if not counterpart_name and description:
            import re
            # "I24 AGENZIA ENTRATE" -> "AGENZIA ENTRATE"
            m = re.match(r"[A-Z0-9]+\s{2,}(.+?)(?:\s{2,}|$)", description)
            if m:
                candidate = m.group(1).strip()
                # Ignora descrizioni generiche
                if candidate and candidate not in ("COMMISSIONI", "COMPETENZE"):
                    counterpart_name = candidate

        # Descrizione completa
        full_description = description
        if extra_parts:
            full_description += " " + " ".join(extra_parts)
        full_description = full_description.strip()

        # Causale pagamento
        remittance_info = " ".join(remittance_parts).strip()

        # Descrizione causale ABI
        causale_description = _get_causale_abi_description(causale_abi)

        # Hash per deduplicazione
        dedup_str = f"{operation_date}|{amount}|{reference_code}|{causale_abi}|{counterpart_name}"
        dedup_hash = hashlib.sha256(dedup_str.encode()).hexdigest()[:16]

        # Raw data
        raw_lines = [line_62] + lines_63
        raw_data = "\n".join(raw_lines)

        return {
            "operation_date": operation_date,
            "value_date": value_date,
            "amount": round(amount, 2),
            "direction": direction,
            "causale_abi": causale_abi,
            "causale_description": causale_description,
            "counterpart_name": counterpart_name,
            "counterpart_address": counterpart_address,
            "ordinante_abi_cab": ordinante_abi_cab,
            "remittance_info": remittance_info,
            "reference_code": reference_code,
            "description": full_description,
            "raw_data": raw_data,
            "dedup_hash": dedup_hash,
        }

    except (ValueError, IndexError) as e:
        logger.warning(f"Errore parsing record CBI: {e}")
        return None


def _extract_counterpart_from_text(text):
    """Estrai il nome della controparte dal testo libero di un record 63.

    Pattern supportati:
    - VS.DISP...FAVORE  NOME - bonifici emessi
    - SDD CORE/B2B: ...  NOME - addebiti diretti
    - BOLL.CBILL NOME - bollettini
    - CARTA*XXXX-HH:MM-NOME CITTA PAESE - pagamenti carta
    - ADD.EFFETTO - NOME - effetti
    """
    import re

    if not text:
        return ""

    # Pattern 1: FAVORE  NOME (disposizioni/bonifici emessi)
    m = re.search(r"FAVORE\s{2,}(.+?)(?:\s{2,}|\s*-\s*ADD|\s*$)", text)
    if m:
        name = m.group(1).strip()
        # Rimuovi NOTPROVIDE e simili
        name = re.sub(r"\s*NOTPROVIDE.*$", "", name).strip()
        if name:
            return name

    # Pattern 2: SDD CORE/B2B: codice  NOME (SDD)
    m = re.match(r"SDD\s+(?:CORE|B2B)\s*:\s*\S+\s{2,}(.+)", text)
    if m:
        return m.group(1).strip()
    # SDD B2B senza spazi multipli: il nome e' alla fine dopo i codici
    m = re.match(r"SDD\s+B2B\s*:\s*\S+(.{20,})", text)
    if m:
        # Prendi gli ultimi token che sembrano un nome
        tail = m.group(1).strip()
        # Cerca il nome (lettere e spazi) alla fine
        m2 = re.search(r"([A-Z][A-Z\s'.&]+(?:SRL|SPA|SOC|COOP|S\.R\.L\.|S\.P\.A\.)?)$", tail)
        if m2:
            return m2.group(1).strip()

    # Pattern 3: BOLL.CBILL NOME o Bollettino NOME o Utenze NOME (bollettini/utenze)
    m = re.match(r"BOLL\.CBILL\s+(.+?)(?:\s{3,}|\s+CBILL\s)", text)
    if m:
        return m.group(1).strip()
    m = re.match(r"Bollettino\s+(.+?)(?:\s{3,}|\s+Rif\.)", text)
    if m:
        return m.group(1).strip()
    m = re.match(r"Utenze\s+(.+?)(?:\s{3,}|\s+Rif\.)", text)
    if m:
        return m.group(1).strip()

    # Pattern 4: CARTA*XXXX-HH:MM-NOME CITTA PAESE (pagamenti carta)
    m = re.match(r"CARTA\*\d{4}-\d{2}:\d{2}-(.+?)(?:\s+[A-Z]{3}\s*$|\s*$)", text)
    if m:
        name = m.group(1).strip()
        # Rimuovi la citta alla fine (ultima parola prima del paese)
        parts = name.rsplit(" ", 1)
        if len(parts) > 1 and len(parts[-1]) <= 15:
            # Potrebbe essere CITTA, teniamo tutto
            pass
        return name

    # Pattern 5: ADD.EFFETTO - NOME (effetti ritirati)
    m = re.match(r"ADD\.EFFETTO\s*-\s*(.+?)(?:\s+Via\b|\s*$)", text)
    if m:
        return m.group(1).strip()

    # Pattern 6: Comm.sdd: codice  NOME
    m = re.match(r"[Cc]omm\.sdd:\s*\S+\s{2,}(.+)", text)
    if m:
        return ""  # Le commissioni non hanno controparte utile

    return ""


def _parse_cbi_date(date_str):
    """Parsa una data CBI in formato DDMMYY."""
    if not date_str or len(date_str) < 6:
        return None
    date_str = date_str[:6].strip()
    if len(date_str) != 6 or not date_str.isdigit():
        return None
    try:
        return datetime.strptime(date_str, "%d%m%y").date()
    except ValueError:
        return None


def _parse_italian_amount(text):
    """Parsa un importo in formato italiano (000000004377,96)."""
    if not text:
        return 0.0
    cleaned = text.replace(".", "").replace(",", ".").strip()
    try:
        return abs(float(cleaned))
    except (ValueError, TypeError):
        return 0.0


def _get_causale_abi_description(code):
    """Restituisce la descrizione di una causale ABI."""
    causali = {
        "480": "Bonifico ricevuto",
        "260": "Disposizione di pagamento",
        "110": "Utenze",
        "780": "Versamento contanti",
        "198": "Agenzia delle Entrate",
        "50C": "SDD addebito diretto",
        "050": "Assegno",
        "270": "Stipendi",
        "450": "Effetti",
        "010": "Versamento",
        "090": "Prelevamento",
        "120": "Pagamento POS",
        "540": "Carte di credito",
        "680": "Commissioni",
        "430": "Interessi",
        "16G": "Commissioni",
        "16K": "Emissione/attivazione carta",
        "48": "Bonifico ricevuto",
        "26": "Disposizione di pagamento",
        "11": "Utenze",
        "78": "Versamento contanti",
    }
    return causali.get(code, "")
