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
    "allevamento_soglia_mangime_pasti": "6",
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
    """True se l'orario nominale del pasto è già passato rispetto ad adesso.
    Puramente basato sull'orario: usato per il display (es. righe sbiadite
    in Alimentazione), non garantisce che i dati siano completi su tutte
    le linee — per quello vedi pasto_completo()."""
    adesso = adesso or datetime.now()
    return _datetime_pasto(data_pasto, pasto) <= adesso


def _linee_attive():
    """Linee (1/2/3) con almeno un animale vivo secondo l'ultimo censimento
    del ciclo attivo. Una linea senza animali non ha bisogno di dati di
    consumo per considerare completo un pasto."""
    from app.routes.allevamento import _get_ciclo_attivo, _live_count, LINEA_PER_BOX
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        return {1, 2, 3}
    count = _live_count(ciclo)
    attive = {LINEA_PER_BOX[box] for box, vivi in count.items() if vivi > 0 and box in LINEA_PER_BOX}
    return attive or {1, 2, 3}


def pasto_completo(campo, data_pasto, pasto, linee_attive=None):
    """True se il pasto è avvenuto E tutte le linee con animali vivi hanno un
    valore per questo campo. Finché manca anche una sola linea attiva (es.
    stai ancora inserendo i dati linea per linea in Alimentazione), il
    pasto non va contato nei consumi: altrimenti la giacenza risulterebbe
    temporaneamente sottostimata (mancano quintali dalle linee non ancora
    inserite)."""
    if not pasto_avvenuto(data_pasto, pasto):
        return False
    linee_attive = linee_attive if linee_attive is not None else _linee_attive()
    valori = {
        r.linea: getattr(r, campo)
        for r in UsoPasto.query.filter_by(data=data_pasto, pasto=pasto).all()
    }
    return all(valori.get(linea) is not None for linea in linee_attive)


def _somma_consumo(campo, dal=None, al=None):
    """Somma un campo (mangime_qli/siero_qli) di UsoPasto tra due istanti
    (datetime), usando l'orario nominale di ciascun pasto per confrontarlo
    con dal/al: serve sia per far partire un periodo dall'ora esatta di una
    consegna invece che dall'inizio della sua giornata (un pasto delle
    07:00 non va attribuito a una consegna arrivata alle 11:00 dello
    stesso giorno), sia — tramite pasto_completo — per escludere i pasti
    non ancora avvenuti o non ancora inseriti su tutte le linee attive."""
    linee_attive = _linee_attive()
    completi = {}
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
        chiave = (riga.data, riga.pasto)
        if chiave not in completi:
            completi[chiave] = pasto_completo(campo, riga.data, riga.pasto, linee_attive)
        if not completi[chiave]:
            continue
        istante = _datetime_pasto(riga.data, riga.pasto)
        if dal is not None and istante < dal:
            continue
        if al is not None and istante > al:
            continue
        tot += valore
    return tot


def get_setting_float(key):
    s = Setting.query.get(key)
    val = s.value if s and s.value not in (None, "") else DEFAULTS.get(key)
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def get_setting_int(key):
    val = get_setting_float(key)
    return int(val) if val is not None else None


def set_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = str(value)
    else:
        db.session.add(Setting(key=key, value=str(value)))


def ultima_calibrazione(tipo, prima_di=None):
    """L'ultima ricalibrazione manuale di un certo tipo (es. 'mangime'),
    prima di un dato istante (o l'ultima in assoluto se prima_di è None)."""
    from app.models import CalibrazioneGiacenza
    q = CalibrazioneGiacenza.query.filter_by(tipo=tipo)
    if prima_di is not None:
        q = q.filter(CalibrazioneGiacenza.timestamp <= prima_di)
    return q.order_by(CalibrazioneGiacenza.timestamp.desc()).first()


def giacenza_mangime_a_data(data_limite=None):
    """Giacenza cumulativa mangime fino a una data esclusa (o su tutta la
    storia se data_limite è None). Se esiste una ricalibrazione manuale
    precedente al punto richiesto, riparte da quel valore invece che dalla
    somma dall'inizio dei tempi — altrimenti resta il comportamento
    originale (somma da sempre), per chi non l'ha mai usata."""
    limite_dt = datetime.combine(data_limite, dt_time(0, 0)) if data_limite is not None else None
    calibrazione = ultima_calibrazione("mangime", prima_di=limite_dt)
    baseline = calibrazione.valore_q if calibrazione else 0
    dal = calibrazione.timestamp if calibrazione else None

    tot_consegne = 0.0
    q_consegne = ConsegnaMangime.query
    if data_limite is not None:
        q_consegne = q_consegne.filter(ConsegnaMangime.data < data_limite)
    for c in q_consegne.all():
        istante = datetime.combine(c.data, c.ora or dt_time(0, 0))
        if dal is not None and istante < dal:
            continue
        if limite_dt is not None and istante >= limite_dt:
            continue
        tot_consegne += c.quantita_qli

    al = datetime.combine(data_limite - timedelta(days=1), dt_time(23, 59, 59)) if data_limite is not None else None
    usato = _somma_consumo("mangime_qli", dal=dal, al=al)
    return baseline + tot_consegne - usato


def giacenza_mangime():
    return giacenza_mangime_a_data(None)


def _ultimo_consumo_pasto(campo):
    """Totale sulle 3 linee dell'ultimo pasto già avvenuto per cui esiste un
    valore di questo campo (reale o stimato). Con poca storia disponibile,
    una media tra giorni diversi pesa troppo un giorno vecchio non più
    rappresentativo: per la sola proiezione di esaurimento è meglio
    assumere che i pasti successivi restino sugli ultimi valori registrati,
    senza variazioni."""
    righe = UsoPasto.query.filter(getattr(UsoPasto, campo).isnot(None)).order_by(
        UsoPasto.data.desc(), UsoPasto.pasto.desc()
    ).all()
    linee_attive = _linee_attive()
    for r in righe:
        if not pasto_completo(campo, r.data, r.pasto, linee_attive):
            continue
        tot = db.session.query(db.func.sum(getattr(UsoPasto, campo))).filter(
            UsoPasto.data == r.data, UsoPasto.pasto == r.pasto
        ).scalar() or 0
        return tot
    return 0


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


def _primo_pasto_futuro(adesso):
    """Il primo pasto (data, numero) non ancora avvenuto rispetto ad adesso."""
    data = adesso.date()
    for pasto in (1, 2, 3):
        if _datetime_pasto(data, pasto) > adesso:
            return data, pasto
    return data + timedelta(days=1), 1


def _pasto_successivo(data, pasto):
    if pasto < 3:
        return data, pasto + 1
    return data + timedelta(days=1), 1


GIORNI_SETTIMANA = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def _testo_giorno(data):
    """'oggi'/'domani'/'dopodomani' o 'gio 18/09', senza dipendere dal
    locale di sistema per i nomi dei giorni."""
    delta = (data - date.today()).days
    if delta == 0:
        return "oggi"
    if delta == 1:
        return "domani"
    if delta == 2:
        return "dopodomani"
    return f"{GIORNI_SETTIMANA[data.weekday()]} {data.strftime('%d/%m')}"


def _testo_residuo(pasti_residui):
    if pasti_residui < 3:
        return "1 pasto residuo" if pasti_residui == 1 else f"{pasti_residui} pasti residui"
    giorni, resto = divmod(pasti_residui, 3)
    testo = "1 giorno" if giorni == 1 else f"{giorni} giorni"
    if resto:
        testo += " e " + ("1 pasto" if resto == 1 else f"{resto} pasti")
    return testo


def stima_esaurimento(giacenza, consumo_ultimo_pasto, adesso=None):
    """Simula in avanti pasto per pasto, ripetendo il consumo dell'ultimo
    pasto registrato (senza assumere variazioni), partendo dal primo pasto
    non ancora avvenuto, finché la giacenza si esaurisce. Ritorna None se
    non c'è ancora nessun dato utile, {"esaurito": True} se la giacenza è
    già a zero, altrimenti il pasto e l'istante di esaurimento con lo
    scarto (mancano/avanzano) rispetto a quel consumo."""
    if giacenza is None:
        return None
    if giacenza <= 0:
        return {"esaurito": True, "testo": "Esaurito"}
    if not consumo_ultimo_pasto or consumo_ultimo_pasto <= 0:
        return None
    adesso = adesso or datetime.now()
    data, pasto = _primo_pasto_futuro(adesso)
    resto = giacenza
    for n in range(1, 201):  # limite di sicurezza, ~66 giorni
        if resto <= consumo_ultimo_pasto:
            scarto = resto - consumo_ultimo_pasto
            return {
                "esaurito": False,
                "pasti_residui": n,
                "testo": _testo_residuo(n),
                "data": data, "pasto": pasto,
                "istante": _datetime_pasto(data, pasto),
                "giorno_testo": _testo_giorno(data),
                "mancano": -scarto if scarto < 0 else None,
                "avanzano": scarto if scarto >= 0 else None,
            }
        resto -= consumo_ultimo_pasto
        data, pasto = _pasto_successivo(data, pasto)
    return None


def colore_livello_pasti(stima, soglia_pasti):
    """Semaforo scorta basato sui pasti residui stimati (non sui quintali):
    così la soglia segue automaticamente l'aumento del consumo invece di
    restare un numero fisso sempre meno rappresentativo col crescere degli
    animali. Rosso sotto soglia, giallo entro 2x soglia, verde oltre."""
    if stima is None or soglia_pasti is None:
        return None
    if stima.get("esaurito"):
        return "rosso"
    pasti_residui = stima.get("pasti_residui")
    if pasti_residui is None:
        return None
    if pasti_residui <= soglia_pasti:
        return "rosso"
    if pasti_residui <= soglia_pasti * 2:
        return "giallo"
    return "verde"


def _perc_capacita(giacenza_q, capacita_q):
    if giacenza_q is None or not capacita_q:
        return None
    return max(0, min(100, round(giacenza_q / capacita_q * 100, 1)))


def stato_mangime():
    giacenza = giacenza_mangime()
    capacita = get_setting_float("allevamento_capacita_mangime_q")
    soglia_pasti = get_setting_int("allevamento_soglia_mangime_pasti")
    ultimo_pasto = _ultimo_consumo_pasto("mangime_qli")
    stima = stima_esaurimento(giacenza, ultimo_pasto)

    barra_testo = None
    if giacenza is not None and capacita:
        barra_testo = f"{giacenza:.1f} di {capacita:.0f} q"

    consumo_giorno_stimato = ultimo_pasto * 3 if ultimo_pasto else None

    soglia_testo = None
    if soglia_pasti:
        soglia_testo = f"Soglia riordino: {_testo_residuo(soglia_pasti)}"
        if ultimo_pasto:
            soglia_testo += f" (≈ {soglia_pasti * ultimo_pasto:.1f} q)"

    calibrazione = ultima_calibrazione("mangime")
    calibrazione_testo = None
    if calibrazione:
        calibrazione_testo = (
            f"Ultima ricalibrazione: {calibrazione.timestamp.strftime('%d/%m/%Y %H:%M')} "
            f"({calibrazione.valore_q:.1f} q)"
        )

    return {
        "giacenza": giacenza, "capacita": capacita,
        "soglia_pasti": soglia_pasti, "soglia_testo": soglia_testo,
        "consumo_ultimo_pasto": ultimo_pasto, "consumo_giorno_stimato": consumo_giorno_stimato,
        "stima": stima,
        "colore": colore_livello_pasti(stima, soglia_pasti),
        "perc": _perc_capacita(giacenza, capacita),
        "barra_testo": barra_testo,
        "calibrazione_testo": calibrazione_testo,
    }


def stato_siero():
    """Il siero non ha una soglia di riordino in quintali: si ordina per più
    giorni (es. il lunedì per coprire fino al lunedì successivo), non
    quando la giacenza scende sotto un tot. Niente semaforo né soglia qui.
    La barra mostra l'avanzamento del carico corrente (usato/consegnato):
    più utile di una capacità cisterna configurata a mano, perché usa il
    dato vero della consegna in corso."""
    info = giacenza_siero()
    ultimo_pasto = _ultimo_consumo_pasto("siero_qli")
    giacenza = info["giacenza"] if info else None
    usato = info["usato"] if info else None
    consegna = info["consegna"] if info else None
    perc = _perc_capacita(usato, consegna.quantita_qli) if consegna else None
    barra_testo = f"{usato:.1f} di {consegna.quantita_qli:.0f} q" if consegna else None
    return {
        "consegna": consegna,
        "usato": usato,
        "giacenza": giacenza, "capacita": None, "soglia": None,
        "stima": stima_esaurimento(giacenza, ultimo_pasto),
        "colore": None,
        "perc": perc,
        "barra_testo": barra_testo,
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


def _punti_curva_accrescimento():
    from app.models import CurvaAccrescimento
    righe = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    return [(r.eta_giorni, r.peso_kg) for r in righe]


def peso_da_giorni(giorni):
    """Interpola la curva età→peso per stimare il peso dai giorni di vita.
    Fuori dagli estremi della curva, mantiene il valore del punto più vicino
    (nessuna estrapolazione oltre i dati noti)."""
    punti = _punti_curva_accrescimento()
    if not punti or giorni is None:
        return None
    if giorni <= punti[0][0]:
        return punti[0][1]
    if giorni >= punti[-1][0]:
        return punti[-1][1]
    for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
        if x0 <= giorni <= x1:
            if x1 == x0:
                return y0
            return y0 + (y1 - y0) * (giorni - x0) / (x1 - x0)
    return None


def giorni_da_peso(peso):
    """Funzione inversa: stima i giorni di vita dal peso, interpolando
    sull'asse peso (la curva è monotona crescente)."""
    punti = _punti_curva_accrescimento()
    if not punti or peso is None:
        return None
    if peso <= punti[0][1]:
        return punti[0][0]
    if peso >= punti[-1][1]:
        return punti[-1][0]
    for (x0, y0), (x1, y1) in zip(punti, punti[1:]):
        if y0 <= peso <= y1:
            if y1 == y0:
                return x0
            return round(x0 + (x1 - x0) * (peso - y0) / (y1 - y0))
    return None


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
