"""Contatori scorte siero/mangime.

La giacenza non è mai salvata: si ricava sempre da consegne - consumi, così
non può disallinearsi dai dati che l'utente inserisce in Consegne e
Alimentazione.

- Mangime: un unico contatore cumulativo su tutta la storia (i 3 silos non si
  svuotano al cambio ciclo, l'avanzo passa al ciclo successivo).
- Siero: la cisterna viene sempre svuotata e lavata prima del carico
  successivo, quindi ogni consegna apre un "periodo" che si chiude quando ne
  arriva una nuova (o quando l'utente segnala manualmente "cisterna vuota").
  Questo permette di confrontare il consumo reale pesato in cucina durante il
  periodo con la quantità dichiarata alla consegna (mai pesata all'arrivo).

Un pasto del giorno corrente viene inserito automaticamente come "stimato"
(copiato dal pasto precedente) anche se non è ancora avvenuto: questi valori
vanno esclusi dai consumi finché l'orario configurato del pasto non è
passato, altrimenti la giacenza risulterebbe scalata in anticipo (anche
negativa) per pasti che devono ancora avvenire.
"""
from datetime import date, datetime, timedelta, time as dt_time
from app import db
from app.models import Setting, ConsegnaSiero, ConsegnaMangime, UsoPasto

DEFAULTS = {
    "allevamento_capacita_mangime_q": "400",
    "allevamento_soglia_mangime_q": "40",
    "allevamento_capacita_siero_q": "150",
    "allevamento_soglia_siero_q": "20",
    "allevamento_soglia_scarto_siero_q": "5",
}

ORARIO_KEYS = {
    1: "allevamento_orario_pasto_1",
    2: "allevamento_orario_pasto_2",
    3: "allevamento_orario_pasto_3",
}
DEFAULT_ORARI = {1: "07:00", 2: "12:00", 3: "18:00"}


def orario_pasto_str(pasto):
    """Valore configurato (o di default) come stringa HH:MM, per i form."""
    key = ORARIO_KEYS.get(pasto)
    s = Setting.query.get(key) if key else None
    return (s.value if s and s.value else DEFAULT_ORARI.get(pasto)) or ""


def orario_pasto(pasto):
    val = orario_pasto_str(pasto)
    if not val:
        return None
    try:
        h, m = val.split(":")
        return dt_time(int(h), int(m))
    except (ValueError, AttributeError):
        return None


def _datetime_pasto(data_pasto, pasto):
    """Istante nominale in cui un pasto avviene, secondo l'orario configurato."""
    return datetime.combine(data_pasto, orario_pasto(pasto) or dt_time(0, 0))


def pasto_avvenuto(data_pasto, pasto, adesso=None):
    """True se l'orario nominale del pasto è già passato rispetto ad adesso."""
    adesso = adesso or datetime.now()
    return _datetime_pasto(data_pasto, pasto) <= adesso


def _somma_consumo(campo, dal=None, al=None):
    """Somma un campo (mangime_qli/siero_qli) di UsoPasto tra due istanti
    (datetime), usando l'orario nominale di ciascun pasto per confrontarlo
    con dal/al: serve sia per escludere i pasti non ancora avvenuti (il cui
    istante nominale è nel futuro), sia per far partire un periodo dall'ora
    esatta di una consegna invece che dall'inizio della sua giornata (un
    pasto delle 07:00 non va attribuito a una consegna arrivata alle 11:00
    dello stesso giorno)."""
    adesso = datetime.now()
    q = UsoPasto.query
    if dal is not None:
        q = q.filter(UsoPasto.data >= dal.date())
    if al is not None:
        q = q.filter(UsoPasto.data <= al.date())
    tot = 0.0
    for riga in q.all():
        valore = getattr(riga, campo)
        if not valore:
            continue
        istante = _datetime_pasto(riga.data, riga.pasto)
        if istante > adesso:
            continue  # non ancora avvenuto
        if dal is not None and istante < dal:
            continue
        if al is not None and istante > al:
            continue
        tot += valore
    return tot


def _consumo_medio(campo, giorni=7):
    """Media giornaliera calcolata solo sui giorni completi (esclude oggi,
    sempre parziale) che hanno almeno un dato registrato in Alimentazione,
    negli ultimi `giorni`. I giorni precedenti all'inizio del tracciamento
    (nessuna riga inserita) non entrano né a numeratore né a denominatore,
    altrimenti diluirebbero la media facendola sembrare più bassa di quella
    reale."""
    da = date.today() - timedelta(days=giorni)
    righe = UsoPasto.query.filter(UsoPasto.data >= da, UsoPasto.data < date.today()).all()
    per_giorno = {}
    for r in righe:
        per_giorno.setdefault(r.data, 0.0)
        valore = getattr(r, campo)
        if valore:
            per_giorno[r.data] += valore
    if not per_giorno:
        return 0
    return sum(per_giorno.values()) / len(per_giorno)


def get_setting_float(key):
    s = Setting.query.get(key)
    val = s.value if s and s.value not in (None, "") else DEFAULTS.get(key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def set_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))


def giacenza_mangime_a_data(data_limite=None):
    """Giacenza cumulativa mangime (tutti i cicli) fino a una data esclusa,
    o su tutta la storia se data_limite è None."""
    q_consegne = db.session.query(db.func.sum(ConsegnaMangime.quantita_qli))
    al = None
    if data_limite is not None:
        q_consegne = q_consegne.filter(ConsegnaMangime.data < data_limite)
        al = datetime.combine(data_limite - timedelta(days=1), dt_time(23, 59, 59))
    consegnato = q_consegne.scalar() or 0
    usato = _somma_consumo("mangime_qli", al=al)
    return consegnato - usato


def giacenza_mangime():
    return giacenza_mangime_a_data(None)


def consumo_medio_mangime(giorni=7):
    return _consumo_medio("mangime_qli", giorni)


def consegna_siero_aperta():
    return ConsegnaSiero.query.filter_by(data_esaurimento=None).order_by(
        ConsegnaSiero.data.desc(), ConsegnaSiero.id.desc()
    ).first()


def giacenza_siero():
    """None se non c'è nessuna consegna aperta (cisterna vuota, in attesa di carico)."""
    c = consegna_siero_aperta()
    if not c:
        return None
    dal = datetime.combine(c.data, c.ora or dt_time(0, 0))
    usato = _somma_consumo("siero_qli", dal=dal)
    return {"consegna": c, "usato": usato, "giacenza": c.quantita_qli - usato}


def consumo_medio_siero(giorni=7):
    return _consumo_medio("siero_qli", giorni)


def _proiezione(giacenza_q, consumo_medio_giorno, soglia_q):
    """Ritorna (giorni_residui|None, data_stimata_esaurimento|None, in_allerta)."""
    if giacenza_q is None:
        return None, None, False
    in_allerta = soglia_q is not None and giacenza_q <= soglia_q
    if giacenza_q <= 0:
        return 0, date.today(), True
    if not consumo_medio_giorno or consumo_medio_giorno <= 0:
        return None, None, in_allerta
    giorni = giacenza_q / consumo_medio_giorno
    return round(giorni, 1), date.today() + timedelta(days=round(giorni)), in_allerta


def _perc_capacita(giacenza_q, capacita_q):
    if giacenza_q is None or not capacita_q:
        return None
    return max(0, min(100, round(giacenza_q / capacita_q * 100, 1)))


def stato_mangime():
    giacenza = giacenza_mangime()
    capacita = get_setting_float("allevamento_capacita_mangime_q")
    soglia = get_setting_float("allevamento_soglia_mangime_q")
    consumo_medio = consumo_medio_mangime()
    giorni, data_stimata, in_allerta = _proiezione(giacenza, consumo_medio, soglia)
    return {
        "giacenza": giacenza, "capacita": capacita, "soglia": soglia,
        "consumo_medio": consumo_medio, "giorni_residui": giorni,
        "data_stimata": data_stimata, "in_allerta": in_allerta,
        "perc": _perc_capacita(giacenza, capacita),
    }


def stato_siero():
    info = giacenza_siero()
    capacita = get_setting_float("allevamento_capacita_siero_q")
    soglia = get_setting_float("allevamento_soglia_siero_q")
    consumo_medio = consumo_medio_siero()
    giacenza = info["giacenza"] if info else None
    giorni, data_stimata, in_allerta = _proiezione(giacenza, consumo_medio, soglia)
    return {
        "consegna": info["consegna"] if info else None,
        "usato": info["usato"] if info else None,
        "giacenza": giacenza, "capacita": capacita, "soglia": soglia,
        "consumo_medio": consumo_medio, "giorni_residui": giorni,
        "data_stimata": data_stimata, "in_allerta": in_allerta,
        "perc": _perc_capacita(giacenza, capacita),
    }


def chiudi_consegne_siero_precedenti(data_chiusura, ora_chiusura=None, escludi_id=None):
    """Chiude le consegne siero ancora aperte il cui inizio periodo è
    precedente all'istante di chiusura: usato alla registrazione di una
    nuova consegna, dato che la cisterna viene sempre svuotata prima del
    carico successivo. Registra anche l'ora esatta, altrimenti l'intera
    giornata di chiusura resterebbe attribuita al carico vecchio anche se
    il consumo dopo quell'ora appartiene già al carico nuovo."""
    istante_chiusura = datetime.combine(data_chiusura, ora_chiusura or dt_time(0, 0))
    q = ConsegnaSiero.query.filter(ConsegnaSiero.data_esaurimento.is_(None))
    if escludi_id is not None:
        q = q.filter(ConsegnaSiero.id != escludi_id)
    for c in q.all():
        inizio = datetime.combine(c.data, c.ora or dt_time(0, 0))
        if inizio < istante_chiusura:
            c.data_esaurimento = data_chiusura
            c.ora_esaurimento = ora_chiusura


def scarto_consegna_siero(consegna, soglia_q=None):
    """Per una consegna chiusa, confronta il consumo reale pesato in cucina
    nel periodo con la quantità dichiarata (non pesata) alla consegna."""
    if not consegna.data_esaurimento:
        return None
    dal = datetime.combine(consegna.data, consegna.ora or dt_time(0, 0))
    al = datetime.combine(consegna.data_esaurimento, consegna.ora_esaurimento or dt_time(23, 59, 59))
    consumo = _somma_consumo("siero_qli", dal=dal, al=al)
    scarto = consumo - consegna.quantita_qli
    scarto_pct = (scarto / consegna.quantita_qli * 100) if consegna.quantita_qli else None
    in_allerta = soglia_q is not None and abs(scarto) >= soglia_q
    return {"consumo": consumo, "scarto": scarto, "scarto_pct": scarto_pct, "in_allerta": in_allerta}
