"""Recupero delle linee non lette dai consumi per box registrati dall'impianto.

Quando una linea non si legge dallo schermo (EM2000 su un'altra pagina, tabella illeggibile, servizio
riavviato a pasto in corso...) nel gestionale resta la stima gialla. L'impianto però salva i consumi di
ogni box in "fotografie" (su EM2000 CONS-GIO.CSV: a mezzanotte e quando l'operatore apre le giacenze):
ogni fotografia è il consumo dalla precedente. Per una linea:

    consumo della linea nell'intervallo = somma dei suoi box
    linea mancante = consumo della linea − pasti già registrati della stessa linea nell'intervallo

Regole, per non scrivere mai un dato sbagliato:
- solo in modalità automatica, solo pasti già avvenuti degli ultimi GIORNI_RECUPERO giorni;
- in un intervallo, per una linea, deve mancare UN solo pasto (con due non si sa come dividere);
- nessun pasto della linea a cavallo di una fotografia: il pasto deve iniziare dopo la fotografia
  precedente e finire prima di quella che chiude l'intervallo (DURATA_PASTO_MIN di margine);
- i consumi per box del PC sono un po' più bassi di quanto dosato (25/10: −1,3% e −0,7%: residui nella
  vasca e nei tubi): si correggono con il rapporto misurato sulle altre linee dello stesso intervallo,
  che hanno tutti i pasti registrati; se non ce ne sono si usa FATTORE_RISERVA;
- il risultato deve somigliare a un pasto vero (totale tra metà e una volta e mezza il pasto
  registrato più vicino della stessa linea), altrimenti non si scrive niente.
Gli orari delle fotografie sono quelli dell'orologio del PC: si portano all'ora reale con lo scarto
misurato dai controlli di quel momento (il 25/10 il PC era rimasto all'ora legale per mezza giornata).
"""
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from app import db

log = logging.getLogger("impianto")

GIORNI_RECUPERO = 3
DURATA_PASTO_MIN = 80          # un pasto intero dura ~60-70 minuti
FATTORE_RISERVA = 0.99         # consumo dei box / dosato, se non si può misurare
COMPONENTI_PC = {1: "acqua", 2: "farina", 3: "farina", 4: "farina", 5: "siero"}


def linee_mancanti(ciclo, oggi=None, adesso=None):
    """[(data, pasto, linea)] di pasti già avvenuti degli ultimi giorni con la linea ancora stimata."""
    from app.models import UsoPasto
    from app.services.allevamento_scorte import pasto_avvenuto, _linee_attive
    oggi = oggi or date.today()
    adesso = adesso or datetime.now()
    attive = _linee_attive()
    righe = {(u.data, u.pasto, u.linea): u for u in UsoPasto.query.filter(
        UsoPasto.ciclo_id == ciclo.id, UsoPasto.data >= oggi - timedelta(days=GIORNI_RECUPERO)).all()}
    out = []
    for g in range(GIORNI_RECUPERO, -1, -1):
        d = oggi - timedelta(days=g)
        if d < ciclo.data_inizio:
            continue
        for pasto in (1, 2, 3):
            if not pasto_avvenuto(d, pasto, adesso - timedelta(minutes=DURATA_PASTO_MIN)):
                continue
            for linea in sorted(attive):
                u = righe.get((d, pasto, linea))
                if u is None or u.stimato:
                    out.append((d, pasto, linea))
    return out


def _scarto_al(istante_pc):
    """Secondi da aggiungere a un orario del PC per avere l'ora reale, in quel momento."""
    from app.models import ImpiantoControllo
    ultimo = ImpiantoControllo.query.filter(ImpiantoControllo.scarto_orologio_s.isnot(None)).order_by(
        ImpiantoControllo.istante.desc()).first()
    if ultimo is None:
        return 0
    stima = istante_pc + timedelta(seconds=ultimo.scarto_orologio_s)
    vicino = ImpiantoControllo.query.filter(
        ImpiantoControllo.scarto_orologio_s.isnot(None),
        ImpiantoControllo.istante.between(stima - timedelta(hours=3), stima + timedelta(hours=3))).order_by(
        db.func.abs(db.func.julianday(ImpiantoControllo.istante) - db.func.julianday(stima))).first()
    return (vicino or ultimo).scarto_orologio_s


def _intervalli(righe):
    """[(inizio, fine, {linea: {comp: q}})] in ora reale, uno per fotografia (dalla precedente)."""
    from app.routes.allevamento import LINEA_PER_BOX
    per_foto = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for istante, box, comp, kg in righe:
        if box in LINEA_PER_BOX and comp in COMPONENTI_PC:
            per_foto[istante][LINEA_PER_BOX[box]][COMPONENTI_PC[comp]] += kg / 100
    foto = sorted(per_foto)
    reali = {f: f + timedelta(seconds=_scarto_al(f)) for f in foto}
    return [(reali[a], reali[b], per_foto[b]) for a, b in zip(foto, foto[1:])]


def _pasti_nell_intervallo(inizio, fine, linea, righe_uso):
    """(pasti dentro l'intervallo, True se un pasto della linea è a cavallo di un estremo)."""
    from app.services.allevamento_scorte import _datetime_pasto
    dentro, a_cavallo = [], False
    margine = timedelta(minutes=DURATA_PASTO_MIN)
    giorni = {inizio.date() - timedelta(days=1) + timedelta(days=i) for i in range((fine - inizio).days + 3)}
    for d in sorted(giorni):
        for pasto in (1, 2, 3):
            t = _datetime_pasto(d, pasto)
            if inizio <= t and t + margine <= fine:
                dentro.append((d, pasto))
            elif (inizio - margine < t < inizio) or (fine - margine < t <= fine):
                if (d, pasto, linea) in righe_uso:
                    a_cavallo = True
    return dentro, a_cavallo


def recupera(lettore, ciclo, oggi=None, adesso=None):
    """Recupera le linee mancanti che si possono ricavare. Restituisce [(data, pasto, linea, valori)]."""
    from app.models import UsoPasto
    from app.services.allevamento_pasti import registra_pasto, dopo_modifica_carichi_siero
    from .registrazione import normalizza_siero
    oggi = oggi or date.today()
    mancanti = set(linee_mancanti(ciclo, oggi, adesso))
    if not mancanti:
        return []
    dal = min(d for d, _, _ in mancanti) - timedelta(days=1)
    intervalli = _intervalli(lettore.consumi_per_box(dal))
    righe_uso = {(u.data, u.pasto, u.linea): u for u in UsoPasto.query.filter(
        UsoPasto.ciclo_id == ciclo.id, UsoPasto.data >= dal - timedelta(days=1)).all()}
    recuperate = []
    for inizio, fine, consumi in intervalli:
        # rapporto consumo dei box / dosato, dalle linee con tutti i pasti dell'intervallo registrati
        fattori, da_fare = [], []
        for linea in (1, 2, 3):
            if linea not in consumi:
                continue
            pasti, a_cavallo = _pasti_nell_intervallo(inizio, fine, linea, righe_uso)
            if a_cavallo or not pasti:
                continue
            mancano = [p for p in pasti if (p[0], p[1], linea) in mancanti]
            noti = [righe_uso[(d, p, linea)] for d, p in pasti
                    if (d, p, linea) in righe_uso and not righe_uso[(d, p, linea)].stimato]
            dosato = sum((u.mangime_qli or 0) + (u.siero_qli or 0) + (u.acqua_qli or 0) for u in noti)
            box = sum(consumi[linea].values())
            if not mancano and dosato > 0 and len(noti) == len(pasti):
                fattori.append(box / dosato)
            elif len(mancano) == 1 and len(noti) == len(pasti) - 1:
                da_fare.append((linea, mancano[0], noti))
        fattore = sum(fattori) / len(fattori) if fattori else FATTORE_RISERVA
        if not 0.9 <= fattore <= 1.05:
            log.info("recupero: rapporto box/dosato %.3f fuori misura (%s-%s), uso %.2f", fattore, inizio, fine,
                     FATTORE_RISERVA)
            fattore = FATTORE_RISERVA
        for linea, (d, pasto), noti in da_fare:
            c = consumi[linea]
            valori = {
                "farina": round(c.get("farina", 0) / fattore - sum(u.mangime_qli or 0 for u in noti), 2),
                "siero": round(c.get("siero", 0) / fattore - sum(u.siero_qli or 0 for u in noti), 2),
                "acqua": round(c.get("acqua", 0) / fattore - sum(u.acqua_qli or 0 for u in noti), 2),
            }
            if valori["farina"] < -0.2 or valori["acqua"] < -0.2 or valori["siero"] < -0.2:
                log.info("recupero: linea %s pasto %s del %s negativa %s, saltata", linea, pasto, d, valori)
                continue
            valori = {k: max(0.0, v) for k, v in valori.items()}
            valori = normalizza_siero(valori)
            totale = sum(valori.values())
            vicino = min(noti, key=lambda u: abs((u.data - d).days * 3 + u.pasto - pasto)) if noti else None
            riferimento = ((vicino.mangime_qli or 0) + (vicino.siero_qli or 0) + (vicino.acqua_qli or 0)) if vicino else None
            if riferimento and not 0.5 * riferimento <= totale <= 1.5 * riferimento:
                log.info("recupero: linea %s pasto %s del %s fuori misura (%.2f q contro %.2f q), saltata",
                         linea, pasto, d, totale, riferimento)
                continue
            riga = registra_pasto(ciclo_id=ciclo.id, data=d, pasto=pasto, linea=linea, mangime_qli=valori["farina"],
                                  siero_qli=valori["siero"], acqua_qli=valori["acqua"])
            riga.fonte = "impianto"
            riga.note = (f"Recuperata dai consumi per box del PC ({inizio:%d/%m %H:%M} → {fine:%d/%m %H:%M}, "
                         f"meno gli altri pasti della linea; consumi dei box / dosato {fattore:.3f}): linea non letta "
                         f"dallo schermo")
            righe_uso[(d, pasto, linea)] = riga
            mancanti.discard((d, pasto, linea))
            recuperate.append((d, pasto, linea, valori))
    if recuperate:
        db.session.commit()
        dopo_modifica_carichi_siero()
    return recuperate
