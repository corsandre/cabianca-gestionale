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
from datetime import date, timedelta

from app.services.allevamento_conteggio import CAPANNONI, live_count

COLORI = ("blu", "nero", "rosso")
SEGNI = ("pallino", "riga", "s")
EMOJI = {"blu": "🔵", "nero": "⚫", "rosso": "🔴"}
HEX = {"blu": "#1565c0", "nero": "#212121", "rosso": "#c62828"}
NOME_SEGNO = {"pallino": "pallino", "riga": "riga", "s": "S"}
FEMMINILE = {"riga", "s"}                       # la riga, la S


def quantita(valore, unita):
    """'6,2 g', '11,07 kg', '2,45 ml', '0,032 g', '1,25 l': grammi/ml fino a 1000, poi kg/litri. None → '–'.
    Le dosi piccole hanno più decimali (sotto 1: 3, sotto 10: 2), così con dosaggi da 0,0125 g/kg non escono «0,0 g»."""
    if valore is None:
        return "–"
    grande = {"g": "kg", "ml": "l"}.get(unita, unita)
    if valore >= 1000:
        testo = f"{valore / 1000:,.2f} {grande}"
    else:
        dec = 3 if valore < 1 else 2 if valore < 10 else 1
        testo = f"{valore:,.{dec}f} {unita}"
    return testo.replace(",", "§").replace(".", ",").replace("§", ".")


def dose_a_capo(dose, peso, per_capo):
    """Dose giornaliera a capo: la dose stessa se è a capo (vaccini), altrimenti dose per kg × peso.
    None se manca la dose, o il peso per una dose per kg."""
    if not dose:
        return None
    if per_capo:
        return dose
    return dose * peso if peso else None


def base_dose(per_capo):
    """'capo' o 'kg', per le scritte «ml/capo», «g/kg»."""
    return "capo" if per_capo else "kg"


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
    if not box:
        return []
    usati = []
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id, box_numero=box).all():
        m = (t.colore, segno_di(t))
        if t.colore and not stato_trattamento(t)["completo"] and m not in usati:
            usati.append(m)
    return usati


def marcatore_suggerito(ciclo_id, box):
    """Primo segno libero nel box: pallino blu, nero, rosso, poi riga, poi S."""
    usati = marcatori_in_uso(ciclo_id, box)
    return next(((c, s) for s in SEGNI for c in COLORI if (c, s) not in usati), (None, None))


def normalizza_ambito(box, cap, caps=None):
    """(box, capannone_numero, capannoni) da salvare. Più capannoni → solo `capannoni` ("1,2,3", in ordine);
    un capannone solo scelto nell'elenco vale come quel capannone intero."""
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
    return sorted(caps_di(t)) == sorted(CAPANNONI)


def capi_e_peso(ciclo, boxes):
    """Capi presenti adesso nei box (ultimo censimento ± mortalità e spostamenti) e peso medio a capo
    dall'ultimo censimento di ogni box, pesato sui capi (None se manca)."""
    from app.models import Censimento, CensimentoBox
    conta = live_count(ciclo)
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
                        note=note, ml_per_kg=ml, per_capo=bool(med.per_capo),
                        giorni_somministrazione=gs, giorni_sospensione=gsosp,
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
    gruppi = {}
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id).order_by(Trattamento.data_inizio, Trattamento.id).all():
        s = stato_trattamento(t)
        if not s["da_ripetere"]:
            continue
        chiave = t.gruppo or f"t{t.id}"
        g = gruppi.setdefault(chiave, {"chiave": chiave, "animale": animale(t), "colore": t.colore,
                                       "segno": segno_di(t), "trattamenti": []})
        g["trattamenti"].append((t, s))
    for g in gruppi.values():
        g["riga"] = max(s["fatte"] for _, s in g["trattamenti"]) + 1
    return list(gruppi.values())


def giorni_saltati(ultima, oggi, mancano):
    """Giorni tra l'ultima dose e oggi senza dose registrata (es. ultima 20/11, oggi 22/11 → [21/11]),
    al massimo quanti ne stanno prima della dose di oggi (mancano = dosi ancora da fare)."""
    if not ultima or mancano < 2:
        return []
    giorni = [ultima + timedelta(days=i) for i in range(1, (oggi - ultima).days)]
    return giorni[:mancano - 1]


def registra_dosi(t, recupera=False, oggi=None):
    """Registra la dose di oggi (e, con recupera, anche quelle dei giorni saltati). Restituisce le date registrate."""
    from app import db
    from app.models import Somministrazione
    oggi = oggi or date.today()
    s = stato_trattamento(t)
    if s["completo"]:
        return []
    date_dosi = (s["saltati"] if recupera else []) + [oggi]
    date_dosi = date_dosi[:s["totali"] - s["fatte"]]
    for i, d in enumerate(date_dosi):
        db.session.add(Somministrazione(trattamento_id=t.id, numero_giorno=s["fatte"] + i + 1, data=d))
    return date_dosi


def controlla_dosi(date_dosi, totali, oggi=None):
    """Date delle dosi in ordine, dopo i controlli (almeno una, nessuna ripetuta, nessuna nel futuro, non più dei giorni previsti)."""
    oggi = oggi or date.today()
    date_dosi = sorted(date_dosi)
    if not date_dosi:
        raise ValueError("Deve restare almeno una dose: per togliere tutto elimina il trattamento.")
    if len(set(date_dosi)) != len(date_dosi):
        raise ValueError("Due dosi nello stesso giorno: controlla le date.")
    if date_dosi[-1] > oggi:
        raise ValueError("Una dose ha una data nel futuro.")
    if len(date_dosi) > totali:
        raise ValueError(f"Il trattamento prevede {totali} giorni: ci sono {len(date_dosi)} dosi.")
    return date_dosi


def modifica_dosi(t, date_dosi):
    """Sostituisce le dosi del trattamento con queste date (rinumerate in ordine di data)."""
    from app import db
    from app.models import Somministrazione
    date_dosi = controlla_dosi(date_dosi, t.giorni_somministrazione)
    righe = sorted(t.somministrazioni.all(), key=lambda x: x.id)
    for i, d in enumerate(date_dosi):
        if i < len(righe):
            righe[i].numero_giorno, righe[i].data = i + 1, d
        else:
            db.session.add(Somministrazione(trattamento_id=t.id, numero_giorno=i + 1, data=d))
    for r in righe[len(date_dosi):]:
        db.session.delete(r)
    return date_dosi


def riga_ordinale(n, segno=None):
    """Quale segno fare sulla schiena il giorno n: '2° pallino', '2ª riga', '2ª S'."""
    segno = segno or "pallino"
    return f"{n}{'ª' if segno in FEMMINILE else '°'} {NOME_SEGNO[segno]}"


def stato_trattamento(t):
    """Progresso di un corso di cura: quante dosi fatte, se ne manca una da
    fare oggi (è passato almeno un giorno dall'ultima), e — a corso finito —
    fino a quando resta in sospensione prima del macello."""
    somm = t.somministrazioni.all()  # già ordinate per numero_giorno (vedi relationship)
    fatte = len(somm)
    ultima = somm[-1] if somm else None
    completo = fatte >= t.giorni_somministrazione or t.chiuso_anticipatamente
    oggi = date.today()
    da_ripetere = (not completo) and ultima is not None and oggi > ultima.data
    data_fine_sospensione = None
    if completo and ultima and not t.deceduto:   # animale morto: nessuna sospensione prima del macello
        data_fine_sospensione = ultima.data + timedelta(days=t.giorni_sospensione)
    # dosi in ml o in g secondo il medicinale (polveri in broda = g): ml_per_kg è "unità per kg al giorno",
    # o "unità a capo al giorno" per i medicinali a dose fissa (vaccini, per_capo)
    dose_capo_ml = dose_a_capo(t.ml_per_kg, t.peso_medio_kg, t.per_capo)   # dose giornaliera a capo
    dose_totale_ml = dose_capo_ml * t.numero_animali if dose_capo_ml is not None else None   # di tutti i capi
    giorni_previsti = fatte if t.chiuso_anticipatamente else t.giorni_somministrazione
    return {
        "fatte": fatte,
        "totali": t.giorni_somministrazione,
        "completo": completo,
        "chiuso_anticipatamente": t.chiuso_anticipatamente,
        "deceduto": bool(t.deceduto),
        "da_ripetere": da_ripetere,
        # giorni senza dose tra l'ultima e oggi: chi registra la dose di oggi può aggiungere anche quelli
        "saltati": giorni_saltati(ultima.data, oggi, t.giorni_somministrazione - fatte) if da_ripetere else [],
        "date_dosi": [x.data for x in somm],
        "ultima_data": ultima.data if ultima else None,
        "prossima_data": (ultima.data + timedelta(days=1)) if ultima and not completo else None,
        "data_fine_sospensione": data_fine_sospensione,
        "in_sospensione": bool(data_fine_sospensione and oggi < data_fine_sospensione),
        "dose_capo_ml": dose_capo_ml,
        "dose_totale_ml": dose_totale_ml,
        "unita": t.medicinale.unita_dose if t.medicinale else "ml",
        "dose_trattamento": dose_totale_ml * giorni_previsti if dose_totale_ml is not None else None,
        "dose_finora": dose_totale_ml * fatte if dose_totale_ml is not None else None,
    }
