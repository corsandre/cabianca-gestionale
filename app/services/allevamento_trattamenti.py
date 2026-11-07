"""Trattamenti: più medicinali per lo stesso animale e marcatore (colore + segno).

- Più medicinali: ogni medicinale resta un Trattamento a sé (con i suoi giorni di somministrazione e di
  sospensione), quelli dati insieme allo stesso animale/gruppo di animali hanno lo stesso `gruppo`.
- Marcatore: colore (blu, nero, rosso) e forma del segno (pallino, riga, S), cioè 9 segni diversi per
  riconoscere gli animali trattati nello stesso box (dal 02/11/2026; prima c'era solo il colore e un
  trattamento senza segno vale come pallino). Il segno si ripete sulla schiena per ogni giorno di
  trattamento: il promemoria dice quale fare (es. «2ª S»). Per un nuovo trattamento si propone il primo
  segno non ancora usato nel box.
- Ambito: un box, un capannone intero, oppure più capannoni insieme (`capannoni` = "1,2,3"; tutti e 7 =
  tutto l'allevamento), es. vaccinazioni o trattamenti nella broda (dal 07/11/2026).
"""
import uuid

COLORI = ("blu", "nero", "rosso")
SEGNI = ("pallino", "riga", "s")
EMOJI = {"blu": "🔵", "nero": "⚫", "rosso": "🔴"}
HEX = {"blu": "#1565c0", "nero": "#212121", "rosso": "#c62828"}
NOME_SEGNO = {"pallino": "pallino", "riga": "riga", "s": "S"}
FEMMINILE = {"riga", "s"}                       # la riga, la S


def segno_di(t):
    return (t.segno or "pallino") if t.colore else None


def testo_marcatore(colore, segno):
    """'pallino blu', 'riga rossa', 'S nera' (accordo del colore con il segno)."""
    if not colore:
        return ""
    segno = segno or "pallino"
    col = colore if colore == "blu" or segno not in FEMMINILE else colore[:-1] + "a"
    return f"{NOME_SEGNO[segno]} {col}"


def marcatori_in_uso(ciclo_id, box):
    """(colore, segno) dei trattamenti ancora in corso nel box."""
    from app.models import Trattamento
    from app.routes.allevamento import _stato_trattamento
    if not box:
        return []
    usati = []
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id, box_numero=box).all():
        m = (t.colore, segno_di(t))
        if t.colore and not _stato_trattamento(t)["completo"] and m not in usati:
            usati.append(m)
    return usati


def marcatore_suggerito(ciclo_id, box):
    """Primo segno libero nel box: pallino blu, nero, rosso, poi riga, poi S."""
    usati = marcatori_in_uso(ciclo_id, box)
    return next(((c, s) for s in SEGNI for c in COLORI if (c, s) not in usati), (None, None))


def normalizza_ambito(box, cap, caps=None):
    """(box, capannone_numero, capannoni) da salvare. Più capannoni → solo `capannoni` ("1,2,3", in ordine);
    un capannone solo scelto nell'elenco vale come quel capannone intero."""
    from app.routes.allevamento import CAPANNONI
    if isinstance(caps, str):
        caps = caps.split(",")
    caps = sorted({int(c) for c in caps or [] if str(c).strip()})
    if any(c not in CAPANNONI for c in caps):
        raise ValueError("Capannone non valido.")
    if len(caps) > 1:
        return None, None, ",".join(map(str, caps))
    if caps:
        return None, caps[0], None
    if not box and not cap:
        raise ValueError("Seleziona un box, un capannone o più capannoni.")
    return box, cap, None


def caps_di(t):
    """Capannoni coperti da un trattamento a più capannoni ([] se box o capannone singolo)."""
    return [int(c) for c in t.capannoni.split(",")] if t.capannoni else []


def tutto_allevamento(t):
    from app.routes.allevamento import CAPANNONI
    return sorted(caps_di(t)) == sorted(CAPANNONI)


def capi_e_peso(ciclo, boxes):
    """Capi presenti adesso nei box (ultimo censimento ± mortalità e spostamenti) e peso medio a capo
    dall'ultimo censimento di ogni box, pesato sui capi (None se manca)."""
    from app.models import Censimento, CensimentoBox
    from app.routes.allevamento import _live_count
    conta = _live_count(ciclo)
    capi = sum(conta.get(b, 0) for b in boxes)
    tot_peso = capi_con_peso = 0
    for b in boxes:
        riga = (CensimentoBox.query.join(Censimento)
                .filter(Censimento.ciclo_id == ciclo.id, CensimentoBox.box_numero == b,
                        CensimentoBox.peso_stimato_kg.isnot(None))
                .order_by(Censimento.data.desc(), Censimento.id.desc()).first())
        if riga and conta.get(b, 0):
            tot_peso += riga.peso_stimato_kg * conta[b]
            capi_con_peso += conta[b]
    return capi, (round(tot_peso / capi_con_peso, 1) if capi_con_peso else None)


def crea_trattamenti(ciclo_id, medicinali, box, cap, qty, peso, data_inizio, operatore, note, colore,
                     registrato_da="web", segno=None, capannoni=None):
    """medicinali: [(Medicinale, ml_per_kg, giorni_somministrazione, giorni_sospensione)].
    Crea un Trattamento per medicinale (stesso gruppo se più d'uno) con la prima dose del giorno di inizio."""
    from app import db
    from app.models import Trattamento, Somministrazione
    if not medicinali:
        raise ValueError("Scegli almeno un medicinale.")
    box, cap, capannoni = normalizza_ambito(box, cap, capannoni)
    if colore not in (None, "") + COLORI:
        raise ValueError("Colore del marcatore non valido.")
    if segno not in (None, "") + SEGNI:
        raise ValueError("Segno del marcatore non valido.")
    segno = (segno or "pallino") if colore else None
    gruppo = uuid.uuid4().hex if len(medicinali) > 1 else None
    creati = []
    for med, ml, gs, gsosp in medicinali:
        t = Trattamento(ciclo_id=ciclo_id, medicinale_id=med.id, box_numero=box, capannone_numero=cap,
                        capannoni=capannoni,
                        numero_animali=qty, peso_medio_kg=peso, data_inizio=data_inizio, operatore=operatore,
                        note=note, ml_per_kg=ml, giorni_somministrazione=gs, giorni_sospensione=gsosp,
                        registrato_da=registrato_da, gruppo=gruppo, colore=colore or None, segno=segno)
        db.session.add(t)
        db.session.flush()
        db.session.add(Somministrazione(trattamento_id=t.id, numero_giorno=1, data=data_inizio))
        creati.append(t)
    return creati


def ambito(t):
    """'box 30' / 'CAP 4 (tutto)' / 'CAP 1, 2, 3' / 'tutto l'allevamento'"""
    if t.box_numero:
        return f"box {t.box_numero}"
    if t.capannoni:
        return "tutto l'allevamento" if tutto_allevamento(t) else "CAP " + ", ".join(map(str, caps_di(t)))
    return f"CAP {t.capannone_numero} (tutto)"


def animale(t):
    """'box 30, maiale con 🔵 S blu' / 'box 30' / 'CAP 4 (tutto)'"""
    if t.colore:
        return f"{ambito(t)}, maiale con {EMOJI.get(t.colore, '')} {testo_marcatore(t.colore, segno_di(t))}"
    return ambito(t)


def da_ripetere_per_animale(ciclo_id):
    """Trattamenti con una dose da fare oggi, raggruppati per animale (stesso gruppo, o da soli):
    [{"chiave", "animale", "colore", "segno", "trattamenti": [(t, stato)], "riga": n}] — riga = il numero del
    segno da fare sulla schiena (la dose successiva)."""
    from app.models import Trattamento
    from app.routes.allevamento import _stato_trattamento
    gruppi = {}
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id).order_by(Trattamento.data_inizio, Trattamento.id).all():
        s = _stato_trattamento(t)
        if not s["da_ripetere"]:
            continue
        chiave = t.gruppo or f"t{t.id}"
        g = gruppi.setdefault(chiave, {"chiave": chiave, "animale": animale(t), "colore": t.colore,
                                       "segno": segno_di(t), "trattamenti": []})
        g["trattamenti"].append((t, s))
    for g in gruppi.values():
        g["riga"] = max(s["fatte"] for _, s in g["trattamenti"]) + 1
    return list(gruppi.values())


def riga_ordinale(n, segno=None):
    """Quale segno fare sulla schiena il giorno n: '2° pallino', '2ª riga', '2ª S'."""
    segno = segno or "pallino"
    return f"{n}{'ª' if segno in FEMMINILE else '°'} {NOME_SEGNO[segno]}"
