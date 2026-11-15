"""
Fatture del siero: righe lette, abbinamento alle consegne e controllo delle fatture nuove.

- leggi_fattura(f): legge le righe dal PDF della fattura (siero_fatture_pdf) e le salva in
  siero_fatture_righe, ogni carico con la sua parte di gasolio e di IVA.
- abbina(): collega ogni riga alla consegna registrata in Consegne: prima per numero di bolla
  (DDT = campo «Lotto», a pochi giorni di distanza), poi per data e quantità.
- controllo(ciclo): quello che la pagina Consegne mostra (riga di ogni consegna, differenze).
- controlla_nuove(): lavoro di ogni mattina: legge le fatture arrivate e manda un riepilogo su Telegram.

I fornitori di siero sono le partite IVA indicate in Impostazioni Soccida.
"""
import logging
import os
import subprocess
from datetime import date, timedelta

from app import db
from app.models import Ciclo, ConsegnaSiero, SdiInvoice, SieroFatturaRiga, SoccidaParametri
from app.services import siero_fatture_pdf as P

log = logging.getLogger(__name__)

GIORNI_BOLLA = 5            # una bolla si abbina per numero solo se la data è entro questi giorni
TOLLERANZA_T = 0.05         # differenza di tonnellate sotto la quale bolla e fattura «coincidono»
TOLLERANZA_DATA_T = 1.0     # senza numero di bolla: stesso giorno e differenza entro questa


def piva_fornitori():
    """Partite IVA dei fornitori di siero, da Impostazioni Soccida (tutti i cicli)."""
    out = set()
    for par in SoccidaParametri.query.all():
        out.update(p.strip() for p in (par.fornitori_siero_piva or "").split(",") if p.strip())
    return sorted(out)


def fatture_fornitori():
    piva = piva_fornitori()
    if not piva:
        return []
    return SdiInvoice.query.filter(SdiInvoice.sender_partita_iva.in_(piva), SdiInvoice.direction == "ricevuta").order_by(SdiInvoice.invoice_date).all()


def _testo_fattura(f):
    """Testo della copia PDF della fattura, o None se il file non c'è o non è un PDF leggibile."""
    percorso = f.xml_path or ""
    if not percorso or not os.path.exists(percorso):
        return None
    try:
        esito = subprocess.run(["pdftotext", "-layout", percorso, "-"], capture_output=True, text=True, timeout=60)
        return esito.stdout if esito.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def leggi_fattura(f):
    """Legge (o rilegge) le righe di una fattura e le salva. Ritorna il numero di carichi trovati,
    o None se il file della fattura non si può leggere (in quel caso non salva niente e si riproverà)."""
    testo = _testo_fattura(f)
    if testo is None:
        return None
    carichi, extra = P.righe_da_testo(testo)
    importi = P.importi_completi(carichi, extra, f.taxable_amount, f.total_amount)
    SieroFatturaRiga.query.filter_by(sdi_invoice_id=f.id).delete()
    for c, importo in zip(carichi, importi):
        db.session.add(SieroFatturaRiga(sdi_invoice_id=f.id, tipo="carico", ddt=c["ddt"], data=date.fromisoformat(c["data"]),
                                        tonnellate=c["tonnellate"], importo_netto=c["importo"], importo=importo))
    for e in extra:
        db.session.add(SieroFatturaRiga(sdi_invoice_id=f.id, tipo="extra", descrizione=e["descrizione"][:200], importo_netto=e["importo"]))
    if not carichi:
        db.session.add(SieroFatturaRiga(sdi_invoice_id=f.id, tipo="vuota", descrizione="Nessun carico riconosciuto nella fattura"))
    db.session.commit()
    return len(carichi)


def abbina():
    """Abbina le righe ancora libere alle consegne libere. Toglie prima gli abbinamenti a consegne
    che non esistono più. Ritorna quante righe ha abbinato."""
    esistenti = {c.id for c in ConsegnaSiero.query.with_entities(ConsegnaSiero.id)}
    for r in SieroFatturaRiga.query.filter(SieroFatturaRiga.consegna_id.isnot(None)):
        if r.consegna_id not in esistenti:
            r.consegna_id = r.come = None
    occupate = {r.consegna_id for r in SieroFatturaRiga.query.filter(SieroFatturaRiga.consegna_id.isnot(None))}
    libere = [r for r in SieroFatturaRiga.query.filter_by(tipo="carico", consegna_id=None).order_by(SieroFatturaRiga.data)]
    fatte = 0
    for passo in ("bolla", "data"):
        for r in libere:
            if r.consegna_id:
                continue
            vicine = ConsegnaSiero.query.filter(ConsegnaSiero.data >= r.data - timedelta(days=GIORNI_BOLLA),
                                                ConsegnaSiero.data <= r.data + timedelta(days=GIORNI_BOLLA)).all()
            candidate = [c for c in vicine if c.id not in occupate]
            if passo == "bolla":
                candidate = [c for c in candidate if (c.lotto or "").strip() == r.ddt]
            else:
                candidate = [c for c in candidate if c.data == r.data and abs(c.quantita_qli / 10 - r.tonnellate) <= TOLLERANZA_DATA_T]
            if candidate:
                scelta = min(candidate, key=lambda c: (abs((c.data - r.data).days), abs(c.quantita_qli / 10 - r.tonnellate)))
                r.consegna_id, r.come = scelta.id, passo
                occupate.add(scelta.id)
                fatte += 1
    db.session.commit()
    return fatte


def stato_riga(r, consegna):
    """Esito del confronto tra una riga di fattura e la sua consegna: (codice, testo)."""
    diff = consegna.quantita_qli / 10 - r.tonnellate
    if abs(diff) > TOLLERANZA_T:
        return "quantita", f"{_t(consegna.quantita_qli / 10)} t in bolla, {_t(r.tonnellate)} t in fattura"
    if (consegna.lotto or "").strip() != r.ddt:
        qui = f"bolla {consegna.lotto.strip()} in Consegne" if (consegna.lotto or "").strip() else "in Consegne manca il numero di bolla"
        return "bolla", f"{qui}, {r.ddt} in fattura"
    return "ok", "coincide"


def _t(v):
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def controllo(ciclo):
    """Per la pagina Consegne: abbina quello che si può e ritorna
    {"per_consegna": {id: {"riga", "stato", "testo"}}, "senza_consegna": [righe], "fatturato_fino_al": data o None,
     "differenze": n, "letta_qualcosa": bool}. Le consegne dopo «fatturato_fino_al» sono in attesa della fattura."""
    abbina()
    righe = SieroFatturaRiga.query.filter_by(tipo="carico").order_by(SieroFatturaRiga.data).all()
    per_consegna, senza = {}, []
    consegne = {c.id: c for c in ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id)} if ciclo else {}
    # le righe senza consegna si segnalano solo per le fatture che contano in questo ciclo (Impostazioni Soccida)
    del_ciclo = set()
    if ciclo:
        from app.services import soccida_dati as D
        par = D.parametri(ciclo, crea=False)
        del_ciclo = {f.id for f in D.fatture_siero(ciclo, par)} if par else set()
    for r in righe:
        if r.consegna_id in consegne:
            stato, testo = stato_riga(r, consegne[r.consegna_id])
            per_consegna[r.consegna_id] = {"riga": r, "stato": stato, "testo": testo}
        elif r.consegna_id is None and r.sdi_invoice_id in del_ciclo:
            senza.append(r)
    fino_al = max((r.data for r in righe if r.sdi_invoice_id in del_ciclo), default=None)
    differenze = sum(1 for v in per_consegna.values() if v["stato"] != "ok") + len(senza) + sum(
        1 for c in consegne.values() if fino_al and c.data <= fino_al and c.id not in per_consegna)
    return {"per_consegna": per_consegna, "senza_consegna": senza, "fatturato_fino_al": fino_al,
            "differenze": differenze, "letta_qualcosa": bool(righe)}


def da_leggere():
    """Fatture dei fornitori di siero non ancora lette."""
    lette = {r.sdi_invoice_id for r in SieroFatturaRiga.query.with_entities(SieroFatturaRiga.sdi_invoice_id).distinct()}
    return [f for f in fatture_fornitori() if f.id not in lette]


GIORNI_AVVISO = 60          # si avvisa su Telegram solo per le fatture recenti: le vecchie si leggono in silenzio


def controlla_nuove(avvisa=True):
    """Lavoro di ogni mattina: legge le fatture di siero arrivate, le abbina alle consegne e manda un
    riepilogo su Telegram (canale finanza) per quelle degli ultimi GIORNI_AVVISO giorni.
    Ritorna la lista delle fatture lette."""
    nuove = []
    for f in da_leggere():
        n = leggi_fattura(f)
        if n is None:
            log.warning("Fattura di siero %s: file non leggibile, riprovo al prossimo controllo", f.invoice_number)
            continue
        nuove.append((f, n))
    if not nuove:
        return []
    abbina()
    if avvisa:
        from app.services.telegram_bot import send_telegram_message
        for f, n in nuove:
            if f.invoice_date and (date.today() - f.invoice_date).days <= GIORNI_AVVISO:
                send_telegram_message(messaggio_fattura(f, n), canale="finanza")
    return [f for f, _ in nuove]


def messaggio_fattura(f, n_carichi):
    """Testo del messaggio per una fattura di siero appena letta."""
    def eur(v):
        return f"{v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".") + " €"
    righe = SieroFatturaRiga.query.filter_by(sdi_invoice_id=f.id, tipo="carico").all()
    testo = [f"🧾 <b>Nuova fattura di siero</b>: {f.sender_name}, n. {f.invoice_number} del {f.invoice_date.strftime('%d/%m/%Y')}",
             f"Totale {eur(f.total_amount or 0)} con IVA"]
    if not n_carichi or not righe:
        testo.append("Non ho riconosciuto nessun carico: controllala a mano.")
        return "\n".join(testo)
    testo.append(f"{n_carichi} carichi, {_t(sum(r.tonnellate for r in righe))} t")
    problemi = []
    for r in righe:
        if not r.consegna_id:
            problemi.append(f"• {r.data.strftime('%d/%m')} bolla {r.ddt}, {_t(r.tonnellate)} t: non c'è in Consegne")
        else:
            stato, dettaglio = stato_riga(r, r.consegna)
            if stato != "ok":
                problemi.append(f"• {r.data.strftime('%d/%m')} bolla {r.ddt}: {dettaglio}")
    primo, ultimo = min(r.data for r in righe), max(r.data for r in righe)
    mancanti = [c for c in ConsegnaSiero.query.filter(ConsegnaSiero.data >= primo, ConsegnaSiero.data <= ultimo).all()
                if not SieroFatturaRiga.query.filter_by(consegna_id=c.id).first()]
    for c in mancanti:
        problemi.append(f"• {c.data.strftime('%d/%m')} consegna di {_t(c.quantita_qli / 10)} t: non è in fattura")
    testo.append("Tutto coincide con le consegne registrate." if not problemi else f"{len(problemi)} differenze con le consegne:")
    testo += problemi[:15]
    if len(problemi) > 15:
        testo.append(f"… e altre {len(problemi) - 15}: vedi Allevamento › Consegne.")
    return "\n".join(testo)
