"""Fatture emesse: recupero delle copie PDF dalle email, OCR, abbinamento con i bonifici.

Le fatture emesse non arrivano come XML SDI: la Coldiretti manda per email una copia PDF
di ogni fattura (mittente in FATTURE_EMESSE_MITTENTE). Qui:

1. si leggono le email di quel mittente in tutte le cartelle della casella, in SOLA
   LETTURA (le email non vengono spostate né segnate come lette: le archivia una persona);
   ogni email viene elaborata una volta sola (tabella email_elaborate);
2. ogni PDF passa dall'OCR (services/fatture_emesse_ocr.py); le fatture di Ca Bianca
   vengono salvate con il PDF in static/uploads/fatture_emesse/;
3. le note di credito segnano come stornata la fattura che citano;
4. ogni fattura viene abbinata al bonifico in entrata dello stesso importo con il cognome
   del cliente (o due parole del nome) nella causale (la fattura di solito si emette dopo il pagamento):
   - bonifico già riconciliato a mano -> la fattura si collega a quella transazione;
   - bonifico sospeso o ignorato -> si crea l'entrata e il bonifico diventa riconciliato
     (gli ignorati sono solo incassi già registrati altrove, es. con scontrino: se c'è
     una fattura non lo sono);
   - nessun bonifico sicuro -> la fattura resta "da abbinare" e si collega a mano.
"""

import email
import imaplib
import logging
import os
import re
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime

from flask import current_app

from app import db
from app.models import (BankTransaction, Category, EmailElaborata, FatturaEmessa,
                        RevenueStream, Setting, Transaction)
from app.services import fatture_emesse_ocr as ocr

logger = logging.getLogger(__name__)

CARTELLE_ESCLUSE = ("TRASH", "JUNK", "DRAFTS", "SENT", "SPAM", "CESTINO")
CARTELLA_PDF = "fatture_emesse"
NOTA_CREATA = "Creata dall'abbinamento con la fattura emessa"

# Finestra in cui cercare il bonifico rispetto alla data della fattura
GIORNI_PRIMA = 60       # il pagamento arriva quasi sempre prima della fattura
GIORNI_DOPO = 60        # scuole ed enti pagano anche un mese dopo

# Categoria e linea di ricavo per le entrate create, dalla descrizione della fattura
CATEGORIE = [
    (r"DIDATTIC|ESTATE|ESTAE|CAMP|CAMPUS|LABORATOR|VISITA|USCITA|CLASSE|FATTORIA", "Fattoria Didattica", "Attivita didattiche"),
    (r"CATERING|RINFRESCO|PRANZO|CENA|MENU|BUFFET|APERITIVO|CROSTATA", "Ristorazione", "Agriturismo"),
    (r"SUINI|MACELLO", "Vendita animali", "Allevamento suini"),
    (r"FORAGGIO", "Vendita prodotti", "B2B"),
]
CATEGORIA_DEFAULT = ("Vendita prodotti", "Vendita diretta")


# --------------------------------------------------------------------------- email

def _dh(v):
    if not v:
        return ""
    out = []
    for parte, cs in decode_header(v):
        out.append(parte.decode(cs or "utf-8", "replace") if isinstance(parte, bytes) else parte)
    return " ".join(out)


def _cartelle(mail):
    typ, righe = mail.list()
    out = []
    for r in righe or []:
        s = r.decode(errors="replace")
        if "\\Noselect" in s:
            continue
        nome = re.split(r' "[./]" ', s, maxsplit=1)[-1].strip()
        if any(x in nome.upper() for x in CARTELLE_ESCLUSE):
            continue
        out.append(nome)
    return out


def controlla_email(app=None) -> dict:
    """Legge le email nuove del mittente delle fatture emesse e importa le fatture.

    Returns: statistiche {"email", "fatture", "duplicate", "da_verificare", "errori", "abbinate"}.
    """
    app = app or current_app._get_current_object()
    stats = {"email": 0, "fatture": 0, "duplicate": 0, "da_verificare": 0, "errori": 0, "abbinate": 0}
    host, user = app.config.get("IMAP_HOST"), app.config.get("IMAP_USER")
    password, mittente = app.config.get("IMAP_PASSWORD"), app.config.get("FATTURE_EMESSE_MITTENTE")
    if not (host and user and password and mittente):
        logger.debug("Fatture emesse: IMAP o mittente non configurati.")
        return stats

    mail = imaplib.IMAP4_SSL(host, app.config.get("IMAP_PORT", 993))
    try:
        mail.login(user, password)
        for cartella in _cartelle(mail):
            typ, _ = mail.select(cartella, readonly=True)       # sola lettura: nessun flag cambia
            if typ != "OK":
                continue
            typ, ids = mail.search(None, f'(FROM "{mittente}")')
            if typ != "OK" or not ids or not ids[0]:
                continue
            for i, intest in _intestazioni(mail, ids[0].split()):
                try:
                    _elabora_email(mail, i, intest, cartella, stats)
                    db.session.commit()
                except Exception as e:                           # una email rotta non blocca le altre
                    db.session.rollback()
                    stats["errori"] += 1
                    logger.exception(f"Fatture emesse: errore email {i} in {cartella}: {e}")
    finally:
        try:
            mail.logout()
        except Exception:
            pass

    collega_note_di_credito()
    stats["abbinate"] = abbina_tutte()
    db.session.commit()
    _notifica(stats)
    logger.info(f"Fatture emesse: {stats}")
    return stats


def _intestazioni(mail, ids):
    """Message-ID, data e oggetto di tutte le email in una sola richiesta."""
    if not ids:
        return []
    typ, d = mail.fetch(b",".join(ids), "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID DATE SUBJECT)])")
    if typ != "OK":
        return []
    out = []
    for parte in d:
        if isinstance(parte, tuple):
            m = re.match(rb"(\d+)", parte[0])
            if m:
                out.append((m.group(1), email.message_from_bytes(parte[1])))
    return out


def _elabora_email(mail, i, intest, cartella, stats):
    oggetto = _dh(intest.get("Subject"))
    try:
        data_mail = parsedate_to_datetime(intest.get("Date")).replace(tzinfo=None)
    except Exception:
        data_mail = None
    mid = (intest.get("Message-ID") or "").strip() or f"{cartella}|{intest.get('Date')}|{oggetto}"
    if EmailElaborata.query.filter_by(message_id=mid[:300]).first():
        return

    typ, d = mail.fetch(i, "(BODY.PEEK[])")
    if typ != "OK":
        return
    msg = email.message_from_bytes(d[0][1])
    stats["email"] += 1
    nuove = dup = 0
    for parte in msg.walk():
        nome = _dh(parte.get_filename() or "")
        if not nome.lower().endswith(".pdf"):
            continue
        pdf = parte.get_payload(decode=True)
        if not pdf:
            continue
        fatture, _ = ocr.leggi_pdf(pdf)
        for f in fatture:
            esito = importa(f, pdf, mid[:300], data_mail)
            if esito == "nuova":
                nuove += 1
                stats["fatture"] += 1
                if f.get("_problemi"):
                    stats["da_verificare"] += 1
            else:
                dup += 1
                stats["duplicate"] += 1
    db.session.add(EmailElaborata(
        message_id=mid[:300], cartella=cartella[:200], oggetto=oggetto[:300], data=data_mail,
        esito=(f"{nuove} nuove, {dup} già presenti" if nuove or dup else "nessuna fattura")))


# --------------------------------------------------------------------------- import

def _cartella_pdf():
    p = os.path.join(current_app.config["UPLOAD_FOLDER"], CARTELLA_PDF)
    os.makedirs(p, exist_ok=True)
    return p


def importa(f: dict, pdf: bytes, message_id: str = None, data_mail: datetime = None) -> str:
    """Salva una fattura letta dall'OCR. Ritorna "nuova" o "duplicata"."""
    esistente = FatturaEmessa.query.filter_by(numero=f["numero"], data=f["data"]).first()
    if esistente:
        if not esistente.pdf_filename:
            esistente.pdf_filename = _salva_pdf(esistente.anno, esistente.sezionale,
                                                esistente.progressivo, esistente.numero, pdf)
        return "duplicata"

    sez, prog = ocr.sezionale(f["numero"])
    anno = f["data"].year
    problemi = ocr.problemi(f)
    f["_problemi"] = problemi
    cliente = f.get("cliente") or ""
    iva = f.get("iva")
    if f.get("imponibile") is not None and f.get("totale") and iva is not None \
            and abs(f["imponibile"] + iva - f["totale"]) > 0.05:
        iva = round(f["totale"] - f["imponibile"], 2)        # l'OCR sbaglia più spesso l'IVA
    fe = FatturaEmessa(
        numero=f["numero"], sezionale=sez, progressivo=prog, anno=anno, data=f["data"],
        tipo=f.get("tipo") or "fattura", cliente=cliente,
        cliente_partita_iva=f.get("cliente_partita_iva") or "",
        cliente_codice_fiscale=f.get("cliente_codice_fiscale") or "",
        descrizione=f.get("descrizione") or "", imponibile=f.get("imponibile"), iva=iva,
        totale=f["totale"] or 0, storna_numero=f.get("storna_numero"), storna_data=f.get("storna_data"),
        interna=("CA' BIANCA" in cliente.upper() or "CA BIANCA" in cliente.upper()),
        pdf_filename=_salva_pdf(anno, sez, prog, f["numero"], pdf),
        email_message_id=message_id, email_data=data_mail,
        ocr_testo=f.get("ocr_testo"), da_verificare=bool(problemi),
        note=("Da controllare: " + "; ".join(problemi)) if problemi else None,
    )
    db.session.add(fe)
    db.session.flush()
    return "nuova"


def _salva_pdf(anno, sez, prog, numero, pdf):
    nome = f"{anno}_{sez or '00'}_{prog:05d}.pdf" if prog is not None else \
        f"{anno}_{re.sub(r'[^0-9A-Za-z]+', '-', numero)}.pdf"
    percorso = os.path.join(_cartella_pdf(), nome)
    if not os.path.exists(percorso):
        with open(percorso, "wb") as fh:
            fh.write(pdf)
    return f"{CARTELLA_PDF}/{nome}"


# --------------------------------------------------------------------------- note di credito

def collega_note_di_credito() -> int:
    """Segna come stornate le fatture citate dalle note di credito."""
    n = 0
    for nc in FatturaEmessa.query.filter_by(tipo="nota_credito").all():
        if not nc.storna_numero:
            continue
        q = FatturaEmessa.query.filter(FatturaEmessa.numero == nc.storna_numero,
                                       FatturaEmessa.tipo == "fattura")
        q = q.filter(FatturaEmessa.data == nc.storna_data) if nc.storna_data else \
            q.filter(FatturaEmessa.anno == nc.anno)
        f = q.first()
        if not f or f.stornata_da_id == nc.id:
            continue
        f.stornata_da_id = nc.id
        if f.transaction_id and f.abbinata_da == "auto":
            # il bonifico va alla fattura riemessa al posto di questa
            _scollega(f)
        n += 1
    return n


# --------------------------------------------------------------------------- abbinamento

_PAROLE_VUOTE = {"SOCIETA", "AGRICOLA", "SRL", "SPA", "SOC", "AGR", "DEL", "DELLA", "PER",
                 "BONIFICO", "FAVORE", "FATTORIA", "BIANCA", "ESTATE", "SALDO", "ACCONTO",
                 "ISTITUTO", "COMPRENSIVO", "STATALE", "SCOLASTICO", "SCUOLA", "COOPERATIVA",
                 "SOCIALE", "ASSOCIAZIONE"}


def _parole(s):
    return {w for w in re.sub(r"[^A-Z ]", " ", (s or "").upper()).split()
            if len(w) > 2 and w not in _PAROLE_VUOTE}


def _testo_bonifico(bt):
    return " ".join(x or "" for x in (bt.counterpart_name, bt.remittance_info, bt.description))


def _transazioni_gia_fatturate():
    return db.session.query(FatturaEmessa.transaction_id).filter(
        FatturaEmessa.transaction_id.isnot(None))


def candidati(f: FatturaEmessa) -> list[dict]:
    """Bonifici in entrata dello stesso importo nella finestra della fattura, dal più probabile."""
    if not f.totale or f.totale <= 0:
        return []
    gia = {r[0] for r in _transazioni_gia_fatturate() if r[0] and r[0] != f.transaction_id}
    q = BankTransaction.query.filter(
        BankTransaction.direction == "C",
        BankTransaction.amount.between(f.totale - 0.01, f.totale + 0.01),
        BankTransaction.operation_date.between(f.data - timedelta(days=GIORNI_PRIMA),
                                               f.data + timedelta(days=GIORNI_DOPO)),
    )
    nomi = _parole(f.cliente)
    # In fattura il cliente è "COGNOME NOME": la prima parola significativa è il cognome
    # (o la parola principale della ragione sociale). Un solo nome di battesimo in comune
    # (MARCO, MARIA...) non basta per abbinare in automatico.
    prima = next((w for w in re.sub(r"[^A-Z ]", " ", (f.cliente or "").upper()).split()
                  if w in nomi), None)
    out = []
    for bt in q.all():
        if bt.matched_transaction_id:
            if bt.matched_transaction_id in gia:
                continue                                      # già incasso di un'altra fattura emessa
            tx = db.session.get(Transaction, bt.matched_transaction_id)
            if tx and (tx.invoice_id or tx.source not in ("banca", "manuale")):
                continue                                      # legato a una fattura SDI o alla cassa
        parole_bt = _parole(_testo_bonifico(bt))
        comuni = len(nomi & parole_bt)
        cognome = prima is not None and prima in parole_bt
        giorni = (bt.operation_date - f.data).days
        out.append({"bt": bt, "nome": comuni, "cognome": cognome, "giorni": giorni,
                    "sicuro": cognome or comuni >= 2,
                    "punteggio": comuni * 10 + (20 if cognome else 0) - abs(giorni) / 10})
    out.sort(key=lambda c: -c["punteggio"])
    return out


def da_abbinare(f: FatturaEmessa) -> bool:
    return (f.tipo == "fattura" and not f.stornata and not f.interna
            and not f.transaction_id and f.incasso != "altro")


def abbina_tutte() -> int:
    """Abbina in automatico le fatture con un bonifico sicuro (stesso importo e cognome del cliente).

    Si assegnano prima le coppie fattura-bonifico con il punteggio più alto, così una fattura
    vecchia non prende il bonifico che spetta a una più vicina.
    """
    coppie = []
    for f in FatturaEmessa.query.all():
        if da_abbinare(f):
            coppie += [(c["punteggio"], f.id, c["bt"].id) for c in candidati(f) if c["sicuro"]]
    coppie.sort(key=lambda c: (-c[0], c[1], c[2]))
    fatte, usati, n = set(), set(), 0
    for _, fid, btid in coppie:
        if fid in fatte or btid in usati:
            continue
        collega(db.session.get(FatturaEmessa, fid), db.session.get(BankTransaction, btid), "auto")
        db.session.flush()
        fatte.add(fid)
        usati.add(btid)
        n += 1
    return n


def _categoria(f):
    testo = f"{f.descrizione or ''} {f.cliente or ''}".upper()
    nomi = CATEGORIA_DEFAULT
    for pattern, cat, linea in CATEGORIE:
        if re.search(pattern, testo):
            nomi = (cat, linea)
            break
    cat = Category.query.filter_by(name=nomi[0], type="entrata").first()
    linea = RevenueStream.query.filter_by(name=nomi[1]).first()
    return (cat.id if cat else None), (linea.id if linea else None)


def collega(f: FatturaEmessa, bt: BankTransaction, da: str = "manuale") -> Transaction:
    """Collega la fattura al bonifico (creando l'entrata se il bonifico non ne ha una)."""
    if bt.status == "riconciliato" and bt.matched_transaction_id:
        tx = db.session.get(Transaction, bt.matched_transaction_id)
    else:
        cat_id, linea_id = _categoria(f)
        iva = f.iva if (f.iva is not None and not f.da_verificare) else 0
        netto = round(bt.amount - iva, 2)
        tx = Transaction(
            type="entrata", source="banca", official=True,
            amount=bt.amount, iva_amount=iva, net_amount=netto,
            iva_rate=round(iva / netto * 100) if iva and netto else 0,
            date=bt.operation_date,
            description=f"Fattura {f.numero} - {f.cliente}"[:500],
            category_id=cat_id, revenue_stream_id=linea_id,
            payment_status="pagato", payment_method="bonifico",
            payment_date=bt.operation_date, due_date=bt.operation_date,
            notes=f"{NOTA_CREATA} {f.numero} del {f.data.strftime('%d/%m/%Y')}"
                  + (f" (il bonifico era tra gli ignorati)" if bt.status == "ignorato" else ""),
        )
        db.session.add(tx)
        db.session.flush()
        bt.status = "riconciliato"
        bt.matched_transaction_id = tx.id
        bt.matched_by = "manuale" if da == "manuale" else "auto"
        bt.ignore_reason_id = None
    f.transaction_id = tx.id
    f.incasso = "banca"
    f.abbinata_da = da
    return tx


def _scollega(f: FatturaEmessa):
    """Toglie l'abbinamento; se l'entrata l'aveva creata l'abbinamento, la elimina
    e il bonifico torna tra i sospesi (non tra gli ignorati)."""
    tx = f.transaction
    f.transaction_id = None
    f.incasso = ""
    f.abbinata_da = None
    if tx and (tx.notes or "").startswith(NOTA_CREATA):
        for bt in BankTransaction.query.filter_by(matched_transaction_id=tx.id).all():
            bt.status = "non_riconciliato"
            bt.matched_transaction_id = None
            bt.matched_by = None
        db.session.delete(tx)


def scollega(f: FatturaEmessa):
    _scollega(f)


# --------------------------------------------------------------------------- numeri mancanti

def numeri_mancanti() -> dict:
    """{(anno, sezionale): [progressivi mancanti]} contando da 1 al numero più alto."""
    serie = {}
    for anno, sez, prog in db.session.query(FatturaEmessa.anno, FatturaEmessa.sezionale,
                                            FatturaEmessa.progressivo).all():
        if prog:
            serie.setdefault((anno, sez or ""), set()).add(prog)
    out = {}
    for k, nums in serie.items():
        manc = [i for i in range(1, max(nums) + 1) if i not in nums]
        if manc:
            out[k] = manc
    return dict(sorted(out.items()))


def etichetta(anno, sez, prog):
    return f"{prog}/{sez} ({anno})" if sez else f"{prog} ({anno})"


def _notifica(stats):
    try:
        from app.services.telegram_bot import send_telegram_message
        righe = []
        if stats["fatture"]:
            righe.append(f"Nuove fatture emesse: {stats['fatture']}"
                         + (f" (da controllare: {stats['da_verificare']})" if stats["da_verificare"] else ""))
            if stats["abbinate"]:
                righe.append(f"Abbinate ai bonifici: {stats['abbinate']}")
        mancanti = {etichetta(a, s, p) for (a, s), nums in numeri_mancanti().items() for p in nums}
        rec = Setting.query.get("fatture_emesse_mancanti_segnalati")
        segnalati = set(rec.value.split(",")) if rec and rec.value else set()
        nuovi = sorted(mancanti - segnalati)
        if nuovi:
            righe.append("Numeri mancanti nella numerazione: " + ", ".join(nuovi[:20]))
        if rec is None:
            rec = Setting(key="fatture_emesse_mancanti_segnalati")
            db.session.add(rec)
        valore = ""
        for m in sorted(mancanti):                           # il campo tiene 512 caratteri
            if len(valore) + len(m) + 1 > 512:
                break
            valore = f"{valore},{m}" if valore else m
        rec.value = valore
        db.session.commit()
        if righe:
            send_telegram_message("<b>Fatture emesse</b>\n" + "\n".join(righe))
    except Exception as e:
        logger.warning(f"Fatture emesse: notifica non inviata: {e}")
