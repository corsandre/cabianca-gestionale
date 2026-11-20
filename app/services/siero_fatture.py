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
GIORNI_A_MANO = 10          # per l'abbinamento a mano si propongono righe/consegne entro questi giorni
MANUALI = ("manuale", "scollegata")   # «come» delle righe decise a mano: l'abbinamento automatico non le tocca


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
    # le scelte fatte a mano (abbinata a mano, scollegata) restano anche se la fattura si rilegge
    a_mano = {(r.ddt, r.data): (r.consegna_id, r.come) for r in SieroFatturaRiga.query.filter(
        SieroFatturaRiga.sdi_invoice_id == f.id, SieroFatturaRiga.come.in_(MANUALI))}
    SieroFatturaRiga.query.filter_by(sdi_invoice_id=f.id).delete()
    for c, importo in zip(carichi, importi):
        r = SieroFatturaRiga(sdi_invoice_id=f.id, tipo="carico", ddt=c["ddt"], data=date.fromisoformat(c["data"]),
                             tonnellate=c["tonnellate"], importo_netto=c["importo"], importo=importo)
        r.consegna_id, r.come = a_mano.get((r.ddt, r.data), (None, None))
        db.session.add(r)
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
        if r.consegna_id not in esistenti:      # consegna cancellata: la riga torna libera (anche se era a mano)
            r.consegna_id = r.come = None
    occupate = {r.consegna_id for r in SieroFatturaRiga.query.filter(SieroFatturaRiga.consegna_id.isnot(None))}
    libere = [r for r in SieroFatturaRiga.query.filter_by(tipo="carico", consegna_id=None).order_by(SieroFatturaRiga.data)
              if r.come != "scollegata"]
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


# ── riepilogo per il riquadro espandibile di Consegne (3.3) ──────────────────────────────────────

def _eur_t(r):
    """€/t di una riga di fattura (con gasolio e IVA), None se non ha tonnellate."""
    return r.importo / r.tonnellate if r.tonnellate and r.importo is not None else None


def calcola_riepilogo(fatture, righe, consegne, per_consegna, senza, fino_al):
    """Numeri, fatture e discrepanze del ciclo. Senza database (si prova in tests/test_siero_fatture.py):
    fatture = SdiInvoice del ciclo; righe = {id fattura: [SieroFatturaRiga]}; consegne = [ConsegnaSiero del ciclo];
    per_consegna, senza, fino_al = come in controllo().

    Valori in euro: una quantità diversa vale la differenza di tonnellate al prezzo di quel carico; un carico in
    fattura senza consegna vale il suo importo; una consegna non fatturata (o ancora in attesa) vale le sue
    tonnellate al prezzo dell'ultima consegna fatturata (riga abbinata più recente)."""
    abbinate = sorted((v["riga"] for v in per_consegna.values() if _eur_t(v["riga"])), key=lambda r: (r.data, r.id))
    prezzo_ultima = _eur_t(abbinate[-1]) if abbinate else None
    ultima_data = abbinate[-1].data if abbinate else None

    discrepanze = []
    for cid, v in per_consegna.items():
        c, r = next((x for x in consegne if x.id == cid), None), v["riga"]
        if c is None or v["stato"] == "ok":
            continue
        valore = None
        if v["stato"] == "quantita" and _eur_t(r):
            valore = (r.tonnellate - c.quantita_qli / 10) * _eur_t(r)
        discrepanze.append({"tipo": v["stato"], "data": r.data, "riga": r, "consegna": c, "testo": v["testo"], "valore": valore})
    for r in senza:
        discrepanze.append({"tipo": "senza_consegna", "data": r.data, "riga": r, "consegna": None,
                            "testo": f"bolla {r.ddt}, {_t(r.tonnellate)} t: in fattura ma non in Consegne", "valore": r.importo})
    non_fatturate, in_attesa = [], []
    for c in consegne:
        if c.id in per_consegna:
            continue
        (non_fatturate if fino_al and c.data <= fino_al else in_attesa).append(c)
    for c in non_fatturate:
        discrepanze.append({"tipo": "non_fatturata", "data": c.data, "riga": None, "consegna": c,
                            "testo": f"{_t(c.quantita_qli / 10)} t in Consegne: non è in fattura",
                            "valore": c.quantita_qli / 10 * prezzo_ultima if prezzo_ultima else None})
    discrepanze.sort(key=lambda d: (d["data"] or date.min))

    # una riga per fattura, con i suoi carichi e l'esito
    elenco = []
    for f in fatture:
        rr = righe.get(f.id, [])
        carichi = [r for r in rr if r.tipo == "carico"]
        diff = sum(1 for r in carichi if r.consegna_id is None or per_consegna.get(r.consegna_id, {}).get("stato", "ok") != "ok")
        elenco.append({"fattura": f, "carichi": carichi, "extra": [r for r in rr if r.tipo == "extra"],
                       "vuota": any(r.tipo == "vuota" for r in rr), "letta": bool(rr),
                       "tonnellate": sum(r.tonnellate or 0 for r in carichi), "differenze": diff})

    # numeri: tonnellate e valore delle consegne fino all'ultimo giorno fatturato, contro le fatture
    righe_carico = [r for x in elenco for r in x["carichi"]]
    t_fatture = sum(r.tonnellate or 0 for r in righe_carico)
    eur_fatture = sum(r.importo or 0 for r in righe_carico)
    fatturabili = [c for c in consegne if fino_al and c.data <= fino_al]
    t_consegne = sum(c.quantita_qli / 10 for c in fatturabili)
    eur_consegne = 0.0
    for c in fatturabili:
        v = per_consegna.get(c.id)
        prezzo = _eur_t(v["riga"]) if v else prezzo_ultima
        eur_consegne += c.quantita_qli / 10 * (prezzo or 0)
    t_attesa = sum(c.quantita_qli / 10 for c in in_attesa)
    numeri = {
        "t_consegne": t_consegne, "t_fatture": t_fatture, "t_diff": t_fatture - t_consegne,
        "eur_consegne": eur_consegne, "eur_fatture": eur_fatture, "eur_diff": eur_fatture - eur_consegne,
        "imponibile": sum(f.taxable_amount or 0 for f in fatture), "totale": sum(f.total_amount or 0 for f in fatture),
        "extra": sum(r.importo_netto or 0 for x in elenco for r in x["extra"]),
        "eur_t_medio": eur_fatture / t_fatture if t_fatture else None,
        "prezzo_ultima": prezzo_ultima, "prezzo_ultima_data": ultima_data,
        "n_fatture": len(fatture), "n_carichi": len(righe_carico),
        "per_bolla": sum(1 for r in righe_carico if r.come == "bolla"),
        "per_data": sum(1 for r in righe_carico if r.come == "data"),
        "a_mano": sum(1 for r in righe_carico if r.come == "manuale"),
        "in_attesa": len(in_attesa), "t_attesa": t_attesa,
        "eur_attesa": t_attesa * prezzo_ultima if prezzo_ultima else None,
    }
    return {"numeri": numeri, "fatture": elenco, "discrepanze": discrepanze}


def riepilogo(ciclo, ctrl):
    """calcola_riepilogo() con i dati del database; ctrl = risultato di controllo(ciclo).
    Aggiunge le candidate per l'abbinamento a mano di ogni discrepanza."""
    from app.services import soccida_dati as D
    par = D.parametri(ciclo, crea=False)
    fatture = D.fatture_siero(ciclo, par) if par else []
    righe = {}
    for r in SieroFatturaRiga.query.filter(SieroFatturaRiga.sdi_invoice_id.in_([f.id for f in fatture])).order_by(SieroFatturaRiga.data):
        righe.setdefault(r.sdi_invoice_id, []).append(r)
    consegne = ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).order_by(ConsegnaSiero.data).all()
    out = calcola_riepilogo(fatture, righe, consegne, ctrl["per_consegna"], ctrl["senza_consegna"], ctrl["fatturato_fino_al"])
    occupate = {r.consegna_id for r in SieroFatturaRiga.query.filter(SieroFatturaRiga.consegna_id.isnot(None))}
    libere_righe = [r for x in out["fatture"] for r in x["carichi"] if r.consegna_id is None]
    for d in out["discrepanze"]:
        vicino = lambda x: abs((x.data - d["data"]).days) <= GIORNI_A_MANO
        if d["tipo"] == "senza_consegna":
            d["candidate"] = [c for c in consegne if c.id not in occupate and vicino(c)]
        elif d["tipo"] == "non_fatturata":
            d["candidate"] = [r for r in libere_righe if vicino(r)]
    for x in out["fatture"]:
        x["pdf"] = bool(x["fattura"].xml_path and os.path.exists(x["fattura"].xml_path))
    return out


def abbina_manuale(riga_id, consegna_id):
    """Collega a mano una riga di fattura a una consegna (entrambe libere)."""
    r = db.session.get(SieroFatturaRiga, riga_id)
    c = db.session.get(ConsegnaSiero, consegna_id)
    if not r or r.tipo != "carico" or not c:
        raise ValueError("Riga di fattura o consegna non trovata.")
    if r.consegna_id:
        raise ValueError("Questa riga di fattura è già abbinata: prima scollegala.")
    if SieroFatturaRiga.query.filter_by(consegna_id=c.id).first():
        raise ValueError("Questa consegna è già abbinata a un'altra riga di fattura.")
    r.consegna_id, r.come = c.id, "manuale"
    db.session.commit()
    return r


def scollega(riga_id):
    """Toglie l'abbinamento di una riga; resta libera e l'abbinamento automatico non la riprende."""
    r = db.session.get(SieroFatturaRiga, riga_id)
    if not r or r.tipo != "carico":
        raise ValueError("Riga di fattura non trovata.")
    r.consegna_id, r.come = None, "scollegata"
    db.session.commit()
    return r


def scrivi_bolla(riga_id):
    """Copia il numero di bolla della fattura nel campo «Lotto» della consegna abbinata."""
    r = db.session.get(SieroFatturaRiga, riga_id)
    if not r or not r.consegna_id or not r.ddt:
        raise ValueError("Riga senza consegna o senza numero di bolla.")
    r.consegna.lotto = r.ddt
    db.session.commit()
    return r


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
