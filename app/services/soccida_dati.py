"""
Soccida: raccolta dei dati dal gestionale.

Questo modulo legge il database e prepara gli oggetti che servono al calcolo
(app/services/soccida.py): Contratto, Situazione e Scenario. Non contiene regole
del contratto: se cambia DA DOVE arriva un dato si tocca qui, se cambia COME si
fa il conto si tocca soccida.py.

Da dove arriva ogni dato
------------------------
- Mangime: bolle in Consegne (consegne_mangime). Giacenza di oggi: quella stimata
  dei silos (allevamento_scorte), o la giacenza finale comunicata se c'è.
- Consumo giornaliero di mangime: media della cucina (uso_pasti) negli ultimi
  GIORNI_MEDIA giorni completi.
- Siero: quantità dalle bolle (consegne_siero); importi dalle fatture SDI dei
  fornitori indicati in Impostazioni, totale con IVA. Le consegne successive
  all'ultima fattura sono «da fatturare», al prezzo dell'ultima fattura.
- Carichi al macello: spostamenti di tipo uscita, categorie fine ciclo e scarti.
- Capi presenti: conteggio per box (censimento ± morti e spostamenti) meno i
  suini di Fattoria Ca' Bianca ancora in stalla.
- Età media: ultimo censimento + giorni passati. Curva: curva di accrescimento.
- Contratto, scenario, anticipi: tabelle soccida_* (Impostazioni › Soccida).
"""
from datetime import date, timedelta

from app import db
from app.models import (
    BankTransaction, Censimento, Ciclo, ConsegnaMangime, ConsegnaSiero, CurvaAccrescimento, SdiInvoice,
    SoccidaAnticipo, SoccidaFattura, SoccidaParametri, SoccidaTabella, Spostamento, UsoPasto,
)
from app.services import soccida as S

GIORNI_MEDIA = 21                    # giorni su cui si calcolano i consumi «recenti»
GIORNI_AL_PRIMO_CARICO = 198         # previsione di partenza: primo carico dopo 198 giorni dall'inizio
GIORNI_ALL_ULTIMO_CARICO = 218       # e ultimo dopo 218 (cicli passati: 210–231 giorni)
CATEGORIE_VERONESI = ("fine_ciclo", "scarto_sottopeso")          # uscite che entrano nel conto
CATEGORIE_CABIANCA = ("agriturismo", "venduti_agriturismo")      # suini di Fattoria Ca' Bianca: esclusi
TIPI_NOTA_CREDITO = ("TD04", "nota_credito")


# ── Parametri del ciclo ─────────────────────────────────────────────────────

def parametri(ciclo, crea=True):
    """I parametri di soccida del ciclo. Alla prima richiesta li crea copiando quelli del ciclo
    precedente (contratto e tabella), con le previsioni di partenza per le date dei carichi."""
    par = SoccidaParametri.query.filter_by(ciclo_id=ciclo.id).first()
    if par or not crea:
        return par
    precedente = (SoccidaParametri.query.join(Ciclo, SoccidaParametri.ciclo_id == Ciclo.id)
                  .filter(Ciclo.data_inizio < ciclo.data_inizio).order_by(Ciclo.data_inizio.desc()).first())
    par = SoccidaParametri(ciclo_id=ciclo.id)
    if precedente:
        for campo in ("minimo_annuo", "posti", "prezzo_partenza", "premio_tabella_perc", "quota_scarti_perc",
                      "calo_scarti_perc", "resa_partenza_perc", "premio_extra_perc", "premi_perc", "resa_perc",
                      "morti_giorno", "capi_carico", "carichi_giorno", "fornitori_siero_piva", "anticipi_pagante"):
            setattr(par, campo, getattr(precedente, campo))
        par.giacenza_iniziale_kg = precedente.giacenza_finale_kg
        ciclo_prec = precedente.ciclo
        par.ultimo_giorno_pagato_prec = ciclo_prec.data_fine or precedente.ultimo_carico
        righe = [(r.indice, r.percentuale) for r in SoccidaTabella.query.filter_by(ciclo_id=precedente.ciclo_id)]
    else:
        righe = list(S.TABELLA_RAPPORTO)
    par.ultimo_giorno_pagato_prec = par.ultimo_giorno_pagato_prec or ciclo.data_inizio - timedelta(days=1)
    par.primo_carico = ciclo.data_inizio + timedelta(days=GIORNI_AL_PRIMO_CARICO)
    par.ultimo_carico = ciclo.data_inizio + timedelta(days=GIORNI_ALL_ULTIMO_CARICO)
    db.session.add(par)
    for indice, perc in righe:
        db.session.add(SoccidaTabella(ciclo_id=ciclo.id, indice=indice, percentuale=perc))
    db.session.commit()
    return par


def tabella(ciclo):
    return tuple((r.indice, r.percentuale) for r in
                 SoccidaTabella.query.filter_by(ciclo_id=ciclo.id).order_by(SoccidaTabella.indice))


def contratto(ciclo, par):
    return S.Contratto(
        minimo_annuo=par.minimo_annuo, prezzo_partenza=par.prezzo_partenza, premio_tabella_perc=par.premio_tabella_perc,
        quota_scarti_perc=par.quota_scarti_perc, calo_scarti_perc=par.calo_scarti_perc,
        resa_partenza_perc=par.resa_partenza_perc, tabella=tabella(ciclo) or S.TABELLA_RAPPORTO,
    )


def scenario(par, carichi=()):
    """Lo scenario standard salvato. La resa prevista diventa quella vera appena c'è un riscontro."""
    reale = S.resa_media(carichi)
    return S.Scenario(
        primo_carico=par.primo_carico, ultimo_carico=par.ultimo_carico, date_confermate=bool(par.date_confermate),
        peso_extra_kg=par.peso_extra_kg, resa_perc=round(reale * 100, 2) if reale else par.resa_perc,
        morti_giorno=par.morti_giorno, premi_perc=par.premi_perc, premio_extra_perc=par.premio_extra_perc,
        capi_carico=par.capi_carico, carichi_giorno=par.carichi_giorno,
    )


# ── Mangime ─────────────────────────────────────────────────────────────────

def mangime_bolle_kg(ciclo):
    q = db.session.query(db.func.sum(ConsegnaMangime.quantita_qli)).filter_by(ciclo_id=ciclo.id).scalar()
    return (q or 0.0) * 100


def consumo_cucina(ciclo, campo, dal=None, al=None):
    """Somma di un campo della cucina (mangime_qli / siero_qli) nel ciclo, in quintali."""
    q = db.session.query(db.func.sum(getattr(UsoPasto, campo))).filter(UsoPasto.ciclo_id == ciclo.id)
    if dal:
        q = q.filter(UsoPasto.data >= dal)
    if al:
        q = q.filter(UsoPasto.data <= al)
    return q.scalar() or 0.0


def consumo_mangime_giorno_kg(ciclo, oggi):
    """Media giornaliera della cucina negli ultimi GIORNI_MEDIA giorni completi (oggi escluso)."""
    dal, al = oggi - timedelta(days=GIORNI_MEDIA), oggi - timedelta(days=1)
    giorni = db.session.query(db.func.count(db.distinct(UsoPasto.data))).filter(
        UsoPasto.ciclo_id == ciclo.id, UsoPasto.data >= dal, UsoPasto.data <= al, UsoPasto.mangime_qli > 0).scalar()
    return consumo_cucina(ciclo, "mangime_qli", dal, al) * 100 / giorni if giorni else 0.0


def giacenza_oggi_kg(par, ciclo=None):
    """Mangime nei silos: la giacenza finale comunicata, se c'è, altrimenti quella stimata (per un ciclo chiuso
    quella della stalla al giorno dopo la fine: stima, da sostituire con la giacenza finale comunicata)."""
    if par.giacenza_finale_kg is not None:
        return par.giacenza_finale_kg, True
    from app.services.allevamento_scorte import giacenza_mangime, giacenza_mangime_a_data
    if ciclo is not None and ciclo.chiuso and ciclo.data_fine:
        return max(0.0, giacenza_mangime_a_data(ciclo.data_fine + timedelta(days=1)) * 100), False
    return max(0.0, giacenza_mangime() * 100), False


# ── Siero ───────────────────────────────────────────────────────────────────

def _piva_siero(par):
    return [p.strip() for p in (par.fornitori_siero_piva or "").split(",") if p.strip()]


def fatture_siero(ciclo, par):
    """Fatture di siero del ciclo: quelle dei fornitori indicati, dopo l'ultimo giorno pagato del ciclo
    precedente e fino alla fine di questo, salvo assegnazione fatta a mano (SoccidaFattura)."""
    piva = _piva_siero(par)
    if not piva:
        return []
    a_mano = {f.sdi_invoice_id: f.ciclo_id for f in SoccidaFattura.query.all()}
    successivo = Ciclo.query.filter(Ciclo.data_inizio > ciclo.data_inizio).order_by(Ciclo.data_inizio).first()
    par_succ = parametri(successivo, crea=False) if successivo else None
    fine = (par_succ.ultimo_giorno_pagato_prec if par_succ and par_succ.ultimo_giorno_pagato_prec else None) or ciclo.data_fine
    out = []
    for f in SdiInvoice.query.filter(SdiInvoice.sender_partita_iva.in_(piva), SdiInvoice.direction == "ricevuta").order_by(SdiInvoice.invoice_date):
        if f.id in a_mano:
            if a_mano[f.id] == ciclo.id:
                out.append(f)
            continue
        if f.invoice_date and f.invoice_date > par.ultimo_giorno_pagato_prec and (fine is None or f.invoice_date <= _fine_mese(fine)):
            out.append(f)
    return out


def _fine_mese(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _importo(f):
    segno = -1 if (f.invoice_type or "") in TIPI_NOTA_CREDITO else 1
    return segno * (f.total_amount or 0.0)


def siero(ciclo, par, oggi):
    """Riassunto del siero del ciclo:
    fatturato_eur (totale fatture, IVA compresa), da_fatturare_t (bolle dopo l'ultima fattura),
    prezzo_t (€/t dell'ultima fattura: totale / tonnellate consegnate in quel mese), giorno_t (media recente)."""
    fatture = fatture_siero(ciclo, par)
    fatturato = sum(_importo(f) for f in fatture)
    ultima = max((f for f in fatture if _importo(f) > 0), key=lambda f: f.invoice_date, default=None)
    consegne = ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id)
    q_dopo = consegne.filter(ConsegnaSiero.data > ultima.invoice_date) if ultima else consegne
    da_fatturare_t = sum(c.quantita_qli for c in q_dopo.all()) / 10
    prezzo = 0.0
    if ultima:
        inizio_mese = ultima.invoice_date.replace(day=1)
        t_mese = sum(c.quantita_qli for c in ConsegnaSiero.query.filter(
            ConsegnaSiero.data >= inizio_mese, ConsegnaSiero.data <= ultima.invoice_date).all()) / 10
        prezzo = _importo(ultima) / t_mese if t_mese else 0.0
    dal = oggi - timedelta(days=GIORNI_MEDIA)
    recenti = sum(c.quantita_qli for c in consegne.filter(ConsegnaSiero.data >= dal, ConsegnaSiero.data < oggi).all()) / 10
    return {"fatture": fatture, "fatturato_eur": fatturato, "ultima": ultima, "da_fatturare_t": da_fatturare_t,
            "prezzo_t": prezzo, "giorno_t": recenti / GIORNI_MEDIA}


# ── Animali ─────────────────────────────────────────────────────────────────

def uscite(ciclo):
    return Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="uscita").order_by(Spostamento.data, Spostamento.id).all()


def entrate(ciclo):
    return Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="entrata").order_by(Spostamento.data, Spostamento.id).all()


def carico_da_spostamento(s):
    """Uno spostamento in uscita verso Veronesi come Carico del calcolo."""
    return S.Carico(capi=s.quantita, peso_vivo_kg=s.peso_medio_kg, scarto=s.categoria_uscita == "scarto_sottopeso",
                    capi_riscontrati=s.capi_riscontrati, peso_morto_kg=s.peso_morto_kg)


def carichi(ciclo):
    return tuple(carico_da_spostamento(s) for s in uscite(ciclo) if s.categoria_uscita in CATEGORIE_VERONESI)


def cabianca_in_stalla(ciclo, par):
    """Suini di Fattoria Ca' Bianca ancora in stalla: quelli del ciclo meno quelli già usciti."""
    usciti = sum(s.quantita for s in uscite(ciclo) if s.categoria_uscita in CATEGORIE_CABIANCA)
    return max(0, (par.suini_cabianca or 0) - usciti)


def capi_presenti(ciclo, par):
    """Capi di Veronesi in stalla oggi (conteggio per box meno i suini di Fattoria Ca' Bianca)."""
    from app.services.allevamento_conteggio import live_count as _live_count
    return max(0, sum(_live_count(ciclo).values()) - cabianca_in_stalla(ciclo, par))


def eta_media_giorni(ciclo, oggi):
    """Età media dei capi oggi, sulla scala della curva di accrescimento: quella dell'ultimo
    censimento con le età, più i giorni passati. None se nessun censimento ha le età."""
    for cens in Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(Censimento.data.desc(), Censimento.id.desc()):
        righe = [(b.quantita, b.giorni_vita) for b in cens.conteggi if b.giorni_vita is not None and b.quantita]
        capi = sum(q for q, _ in righe)
        if capi:
            return sum(q * g for q, g in righe) / capi + (oggi - cens.data).days, cens
    return None, None


def curva():
    return tuple((c.eta_giorni, c.peso_kg) for c in CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni))


# ── Anticipi ────────────────────────────────────────────────────────────────

def anticipi(ciclo):
    return SoccidaAnticipo.query.filter_by(ciclo_id=ciclo.id).order_by(SoccidaAnticipo.data).all()


def anticipi_da_banca(ciclo, par):
    """Bonifici in entrata del pagante indicato in Impostazioni, nel periodo del ciclo e non ancora
    registrati come anticipi: la pagina li propone, l'utente li conferma."""
    testo = (par.anticipi_pagante or "").strip()
    if not testo:
        return []
    gia = {a.bank_transaction_id for a in SoccidaAnticipo.query.filter(SoccidaAnticipo.bank_transaction_id.isnot(None))}
    q = BankTransaction.query.filter(
        BankTransaction.direction == "C", BankTransaction.counterpart_name.ilike(f"%{testo}%"),
        BankTransaction.operation_date >= ciclo.data_inizio)
    if ciclo.data_fine:
        q = q.filter(BankTransaction.operation_date <= ciclo.data_fine)
    return [t for t in q.order_by(BankTransaction.operation_date).all() if t.id not in gia]


# ── Tutto insieme ───────────────────────────────────────────────────────────

def situazione(ciclo, par, oggi=None):
    """La Situazione del ciclo a oggi per il calcolo, più i dettagli che servono alla scheda
    (da dove viene ogni numero). Ritorna (Situazione, dettagli)."""
    oggi = oggi or date.today()
    giac, giac_comunicata = giacenza_oggi_kg(par, ciclo)
    sie = siero(ciclo, par, oggi)
    eta, cens = eta_media_giorni(ciclo, oggi)
    car = carichi(ciclo)
    sit = S.Situazione(
        oggi=oggi, ultimo_giorno_pagato_prec=par.ultimo_giorno_pagato_prec,
        mangime_bolle_kg=mangime_bolle_kg(ciclo), giacenza_iniziale_kg=par.giacenza_iniziale_kg or 0.0,
        giacenza_oggi_kg=giac, consumo_mangime_giorno_kg=consumo_mangime_giorno_kg(ciclo, oggi),
        carichi=car, capi_presenti=capi_presenti(ciclo, par), eta_media_giorni=eta or 0.0, curva=curva(),
        siero_fatturato_eur=sie["fatturato_eur"], siero_da_fatturare_t=sie["da_fatturare_t"],
        siero_prezzo_t=sie["prezzo_t"], siero_giorno_t=sie["giorno_t"],
        anticipi_eur=sum(a.importo for a in anticipi(ciclo)),
    )
    dettagli = {"siero": sie, "giacenza_comunicata": giac_comunicata, "censimento_eta": cens,
                "cabianca_in_stalla": cabianca_in_stalla(ciclo, par)}
    return sit, dettagli
