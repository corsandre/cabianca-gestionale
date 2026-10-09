"""Spese Amazon pagate con carta: ordine dalla mail + categoria dal bot Telegram.

In banca un acquisto Amazon è solo "AMAZON* NH8CN5OR4 LUXEMBOURG": non dice cosa si è comprato.
1. Le mail di conferma d'ordine di Amazon vengono inoltrate (filtro Gmail) ad amministrazione@:
   leggi_mail_amazon() le legge in SOLA LETTURA e salva numero d'ordine, data, totale e articoli.
2. abbina_ordini() collega ogni addebito Amazon in sospeso all'ordine con lo stesso totale e data vicina.
3. chiedi_spese() manda nel gruppo Telegram della finanza un messaggio per ogni addebito Amazon nuovo,
   con gli articoli (se c'è l'ordine) e i pulsanti delle categorie. Premuto il pulsante, registra()
   crea l'uscita e riconcilia il movimento; rispondendo al messaggio si scrive cos'era
   (aggiungi_descrizione()).
Sull'account Amazon ci sono anche acquisti privati: contano solo gli ordini che trovano un addebito
sulla carta aziendale; gli altri vengono cancellati dopo 30 giorni (cancella_ordini_privati()).
"""

import email
import imaplib
import logging
import re
from datetime import date, datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html import unescape

import requests
from flask import current_app

from app import db
from app.models import (BankTransaction, Category, OrdineAmazon, RevenueStream, RichiestaSpesa,
                        Setting, Transaction)

logger = logging.getLogger(__name__)

AMAZON = re.compile(r"AMAZON|AMZN", re.IGNORECASE)
CARTELLE_ESCLUSE = ("TRASH", "JUNK", "DRAFTS", "SENT", "SPAM", "CESTINO")
NUMERO_ORDINE = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
_IMPORTO = r"(\d{1,3}(?:\.\d{3})*,\d{2})"
TOTALE = [re.compile(p, re.IGNORECASE) for p in (
    r"Totale\s+(?:dell['’]\s*)?ordine[^0-9€]{0,40}(?:EUR|€)?\s*" + _IMPORTO,
    r"Importo\s+totale[^0-9€]{0,40}(?:EUR|€)?\s*" + _IMPORTO,
    r"Totale[^0-9€\n]{0,25}(?:EUR|€)\s*" + _IMPORTO,
    r"Totale[^0-9€\n]{0,25}" + _IMPORTO + r"\s*€",
)]
CATEGORIE_BOT = ["Fattoria Didattica", "Attrezzature", "Manutenzione", "Materie prime", "Ristorazione",
                 "Servizi e abbonamenti"]
LINEA_DI = {"Fattoria Didattica": "Attivita didattiche", "Ristorazione": "Agriturismo", "Materie prime": "Agriturismo"}
GIORNI_ORDINE_PRIMA, GIORNI_ORDINE_DOPO = 2, 15   # l'addebito arriva alla spedizione


def e_amazon(bt) -> bool:
    return bt.direction == "D" and bool(AMAZON.search(f"{bt.counterpart_name or ''} {bt.description or ''}"))


# --------------------------------------------------------------------------- mail

def _dh(v):
    return " ".join(p.decode(c or "utf-8", "replace") if isinstance(p, bytes) else p
                    for p, c in decode_header(v or ""))


def _testo(msg) -> str:
    plain, html = [], []
    for parte in msg.walk():
        tipo = parte.get_content_type()
        if tipo not in ("text/plain", "text/html") or parte.get_filename():
            continue
        dati = parte.get_payload(decode=True) or b""
        t = dati.decode(parte.get_content_charset() or "utf-8", "replace")
        (plain if tipo == "text/plain" else html).append(t)
    if plain:
        return "\n".join(plain)
    t = re.sub(r"(?is)<(script|style).*?</\1>", " ", "\n".join(html))
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|td|li|h\d)>", "\n", t)
    return unescape(re.sub(r"<[^>]+>", " ", t))


def leggi_ordine(oggetto: str, testo: str) -> dict | None:
    """Numero d'ordine, totale e articoli da una mail di conferma Amazon. None se non è un ordine."""
    numeri = NUMERO_ORDINE.findall(f"{oggetto}\n{testo}")
    if not numeri:
        return None
    totale = None
    for pat in TOTALE:
        m = pat.search(testo)
        if m:
            totale = float(m.group(1).replace(".", "").replace(",", "."))
            break
    if totale is None:
        return None
    articoli = ""
    m = re.search(r"(?:Ordinato|ordine)[^\"“]*[\"“](.+?)[\"”](.*)$", oggetto, re.IGNORECASE)
    if m:
        altri = re.search(r"e altri \d+ articol\w*", m.group(2), re.IGNORECASE)
        articoli = (m.group(1) + (" " + altri.group(0) if altri else "")).strip()
    if not articoli:
        righe = [r.strip() for r in testo.splitlines() if 15 < len(r.strip()) < 160]
        cand = [r for r in righe if not re.search(r"(?i)totale|ordine|spedizion|consegna|indirizzo|amazon|pagamento|iva|€|eur\b", r)]
        articoli = "; ".join(cand[:3])
    return {"numero": numeri[0], "totale": round(totale, 2), "articoli": articoli[:500]}


def leggi_mail_amazon(app=None) -> int:
    """Legge le conferme d'ordine Amazon arrivate in amministrazione@ (sola lettura)."""
    app = app or current_app._get_current_object()
    host, user, pwd = app.config.get("IMAP_HOST"), app.config.get("IMAP_USER"), app.config.get("IMAP_PASSWORD")
    if not (host and user and pwd):
        return 0
    nuovi = 0
    mail = imaplib.IMAP4_SSL(host, app.config.get("IMAP_PORT", 993))
    try:
        mail.login(user, pwd)
        typ, righe = mail.list()
        for r in righe or []:
            s = r.decode(errors="replace")
            nome = re.split(r' "[./]" ', s, maxsplit=1)[-1].strip()
            if "\\Noselect" in s or any(x in nome.upper() for x in CARTELLE_ESCLUSE):
                continue
            if mail.select(nome, readonly=True)[0] != "OK":
                continue
            typ, ids = mail.search(None, '(FROM "amazon")')
            if typ != "OK" or not ids or not ids[0]:
                continue
            for i in ids[0].split():
                typ, d = mail.fetch(i, "(BODY.PEEK[])")
                if typ != "OK":
                    continue
                msg = email.message_from_bytes(d[0][1])
                mid = (msg.get("Message-ID") or "").strip()[:300]
                if mid and OrdineAmazon.query.filter_by(email_message_id=mid).first():
                    continue
                o = leggi_ordine(_dh(msg.get("Subject")), _testo(msg))
                if not o or OrdineAmazon.query.filter_by(numero=o["numero"]).first():
                    continue
                try:
                    quando = parsedate_to_datetime(msg.get("Date")).date()
                except Exception:
                    quando = date.today()
                db.session.add(OrdineAmazon(numero=o["numero"], data=quando, totale=o["totale"],
                                            articoli=o["articoli"], email_message_id=mid))
                db.session.commit()
                nuovi += 1
    finally:
        try:
            mail.logout()
        except Exception:
            pass
    if nuovi:
        logger.info(f"Ordini Amazon letti dalle mail: {nuovi}")
    return nuovi


# --------------------------------------------------------------------------- abbinamento

def abbina_ordini() -> int:
    """Collega gli addebiti Amazon in sospeso all'ordine con lo stesso totale e data vicina."""
    n = 0
    usati = {o.bank_transaction_id for o in OrdineAmazon.query.filter(OrdineAmazon.bank_transaction_id.isnot(None))}
    for bt in BankTransaction.query.filter_by(status="non_riconciliato", direction="D").all():
        if not e_amazon(bt) or bt.id in usati:
            continue
        cand = OrdineAmazon.query.filter(
            OrdineAmazon.bank_transaction_id.is_(None),
            OrdineAmazon.totale.between(bt.amount - 0.01, bt.amount + 0.01),
            OrdineAmazon.data.between(bt.operation_date - timedelta(days=GIORNI_ORDINE_DOPO),
                                      bt.operation_date + timedelta(days=GIORNI_ORDINE_PRIMA)),
        ).all()
        if not cand:
            continue
        o = min(cand, key=lambda o: abs((bt.operation_date - o.data).days))
        o.bank_transaction_id = bt.id
        usati.add(bt.id)
        n += 1
    db.session.commit()
    return n


# --------------------------------------------------------------------------- bot

def _categorie():
    out = []
    for nome in CATEGORIE_BOT:
        c = Category.query.filter_by(name=nome).first()
        if c:
            out.append(c)
    return out


def _attiva_dal():
    """Il bot chiede solo per i movimenti importati da quando la funzione è attiva
    (gli arretrati restano nei sospesi e nel controllo di fine mese)."""
    rec = Setting.query.get("spese_bot_attivo_dal")
    if rec is None:
        rec = Setting(key="spese_bot_attivo_dal", value=datetime.utcnow().isoformat(timespec="seconds"))
        db.session.add(rec)
        db.session.commit()
    return datetime.fromisoformat(rec.value)


def _euro(v):
    return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def testo_richiesta(bt, ordine=None, esito=None) -> str:
    righe = ["🛒 <b>Spesa Amazon da registrare</b>",
             f"€ {_euro(bt.amount)} · {bt.operation_date.strftime('%d/%m/%Y')} · {(bt.counterpart_name or '')[:40]}"]
    if ordine:
        righe.append(f"Ordine {ordine.numero}: {ordine.articoli or '(articoli non letti)'}")
    else:
        righe.append("Ordine non trovato nelle mail.")
    righe.append(esito or ("Scegli la categoria." + ("" if ordine else " Poi rispondi a questo messaggio scrivendo cos'era.")))
    return "\n".join(righe)


def _tastiera(rid):
    cat = _categorie()
    righe = [[{"text": c.name, "callback_data": f"spesa:{rid}:{c.id}"} for c in cat[i:i + 2]] for i in range(0, len(cat), 2)]
    righe.append([{"text": "Lo faccio dal gestionale", "callback_data": f"spesa:{rid}:manuale"}])
    return {"inline_keyboard": righe}


def chiedi_spese(app=None, arretrati: int = 0) -> int:
    """Manda sul gruppo della finanza una domanda per ogni addebito Amazon nuovo e in sospeso.
    Con arretrati=N manda anche i N addebiti più vecchi importati prima dell'attivazione."""
    app = app or current_app._get_current_object()
    token, chat = app.config.get("TELEGRAM_BOT_TOKEN"), app.config.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return 0
    dal = _attiva_dal()
    gia = {r.bank_transaction_id for r in RichiestaSpesa.query.all()}
    q = BankTransaction.query.filter(BankTransaction.status == "non_riconciliato", BankTransaction.direction == "D")
    nuovi = [bt for bt in q.filter(BankTransaction.created_at >= dal).all() if e_amazon(bt) and bt.id not in gia]
    vecchi = [bt for bt in q.filter(BankTransaction.created_at < dal).order_by(BankTransaction.operation_date).all()
              if e_amazon(bt) and bt.id not in gia][:arretrati]
    n = 0
    for bt in nuovi + vecchi:
        r = RichiestaSpesa(bank_transaction_id=bt.id, chat_id=str(chat))
        db.session.add(r)
        db.session.flush()
        ordine = OrdineAmazon.query.filter_by(bank_transaction_id=bt.id).first()
        try:
            resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={
                "chat_id": chat, "text": testo_richiesta(bt, ordine), "parse_mode": "HTML",
                "reply_markup": _tastiera(r.id)}, timeout=15)
            r.message_id = resp.json().get("result", {}).get("message_id")
        except Exception as e:
            logger.warning(f"Spese: domanda Telegram non inviata per il movimento {bt.id}: {e}")
            db.session.rollback()
            continue
        db.session.commit()
        n += 1
    return n


def registra(rid: int, scelta: str, utente: str) -> str:
    """Pulsante premuto sul bot. Ritorna il nuovo testo del messaggio."""
    from app.services.reconciliation import create_transaction_from_bank_manual
    r = db.session.get(RichiestaSpesa, rid)
    if r is None:
        return "Richiesta non trovata."
    bt = db.session.get(BankTransaction, r.bank_transaction_id)
    ordine = OrdineAmazon.query.filter_by(bank_transaction_id=bt.id).first()
    if bt.status != "non_riconciliato":
        r.stato = "registrata" if r.stato == "inviata" else r.stato
        db.session.commit()
        return testo_richiesta(bt, ordine, "✅ Già registrata dal gestionale.")
    if scelta == "manuale":
        r.stato = "manuale"
        r.risposto_da = utente
        db.session.commit()
        return testo_richiesta(bt, ordine, f"↪️ {utente}: la registra dal gestionale.")
    cat = db.session.get(Category, int(scelta))
    linea = RevenueStream.query.filter_by(name=LINEA_DI.get(cat.name, "Generale")).first()
    descr = f"Amazon: {ordine.articoli}" if ordine and ordine.articoli else f"Amazon {bt.operation_date.strftime('%d/%m/%Y')}"
    tx = create_transaction_from_bank_manual(bt, category_id=cat.id, revenue_stream_id=linea.id if linea else None,
                                             description=descr[:500])
    tx.payment_method = "carta"
    tx.notes = f"Registrata dal bot Telegram da {utente}" + (f" (ordine Amazon {ordine.numero})" if ordine else "")
    r.stato, r.transaction_id, r.risposto_da = "registrata", tx.id, utente
    db.session.commit()
    seguito = "" if ordine else " Rispondi a questo messaggio per scrivere cos'era."
    return testo_richiesta(bt, ordine, f"✅ Registrata come <b>{cat.name}</b> da {utente}.{seguito}")


def aggiungi_descrizione(chat_id, message_id, testo: str, utente: str) -> str | None:
    """Risposta scritta a un messaggio del bot: diventa la descrizione della spesa."""
    r = RichiestaSpesa.query.filter_by(chat_id=str(chat_id), message_id=message_id).first()
    if r is None:
        return None
    if not r.transaction_id:
        return "Prima scegli la categoria con i pulsanti."
    tx = db.session.get(Transaction, r.transaction_id)
    tx.description = f"Amazon: {testo.strip()}"[:500]
    tx.notes = (tx.notes or "") + f" · descrizione di {utente}"
    db.session.commit()
    return f"✏️ Descrizione salvata: {testo.strip()[:80]}"


def arretrati_senza_domanda() -> int:
    gia = {r.bank_transaction_id for r in RichiestaSpesa.query.all()}
    return sum(1 for bt in da_descrivere() if bt.id not in gia)


def da_descrivere():
    """Addebiti Amazon ancora in sospeso (per il controllo di fine mese)."""
    return [bt for bt in BankTransaction.query.filter_by(status="non_riconciliato", direction="D").all() if e_amazon(bt)]


GIORNI_ORDINI_PRIVATI = 30


def cancella_ordini_privati() -> int:
    """Sull'account Amazon ci sono anche acquisti privati, pagati con un'altra carta: non avranno mai
    un addebito sul conto aziendale. Dopo 30 giorni senza addebito l'ordine viene cancellato,
    così nel gestionale non resta traccia degli acquisti personali."""
    limite = date.today() - timedelta(days=GIORNI_ORDINI_PRIVATI)
    n = OrdineAmazon.query.filter(OrdineAmazon.bank_transaction_id.is_(None), OrdineAmazon.data < limite).delete()
    db.session.commit()
    return n


def giro(app=None) -> dict:
    """Ciclo completo: mail, abbinamento, domande sul bot, pulizia degli ordini privati."""
    app = app or current_app._get_current_object()
    out = {"ordini": 0, "abbinati": 0, "domande": 0}
    try:
        out["ordini"] = leggi_mail_amazon(app)
    except Exception as e:
        logger.warning(f"Spese: lettura mail Amazon non riuscita: {e}")
    out["abbinati"] = abbina_ordini()
    out["domande"] = chiedi_spese(app)
    out["privati_cancellati"] = cancella_ordini_privati()
    return out
