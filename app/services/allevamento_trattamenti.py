"""Trattamenti: più medicinali per lo stesso animale e colore del marcatore.

- Più medicinali: ogni medicinale resta un Trattamento a sé (con i suoi giorni di somministrazione e di
  sospensione), quelli dati insieme allo stesso animale/gruppo di animali hanno lo stesso `gruppo`.
- Colore del marcatore (blu, nero, rosso): serve a riconoscere gli animali trattati nello stesso box.
  Sulla schiena si fa una riga per ogni giorno di trattamento (di solito al massimo 3): il promemoria
  dice quale riga fare. Per un nuovo trattamento si propone un colore non ancora usato nel box.
"""
import uuid

COLORI = ("blu", "nero", "rosso")
EMOJI = {"blu": "🔵", "nero": "⚫", "rosso": "🔴"}


def colori_in_uso(ciclo_id, box):
    """Colori dei trattamenti ancora in corso nel box."""
    from app.models import Trattamento
    from app.routes.allevamento import _stato_trattamento
    if not box:
        return []
    usati = []
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id, box_numero=box).all():
        if t.colore and not _stato_trattamento(t)["completo"] and t.colore not in usati:
            usati.append(t.colore)
    return usati


def colore_suggerito(ciclo_id, box):
    usati = colori_in_uso(ciclo_id, box)
    return next((c for c in COLORI if c not in usati), None)


def crea_trattamenti(ciclo_id, medicinali, box, cap, qty, peso, data_inizio, operatore, note, colore,
                     registrato_da="web"):
    """medicinali: [(Medicinale, ml_per_kg, giorni_somministrazione, giorni_sospensione)].
    Crea un Trattamento per medicinale (stesso gruppo se più d'uno) con la prima dose del giorno di inizio."""
    from app import db
    from app.models import Trattamento, Somministrazione
    if not medicinali:
        raise ValueError("Scegli almeno un medicinale.")
    if colore not in (None, "") + COLORI:
        raise ValueError("Colore del marcatore non valido.")
    gruppo = uuid.uuid4().hex if len(medicinali) > 1 else None
    creati = []
    for med, ml, gs, gsosp in medicinali:
        t = Trattamento(ciclo_id=ciclo_id, medicinale_id=med.id, box_numero=box, capannone_numero=cap,
                        numero_animali=qty, peso_medio_kg=peso, data_inizio=data_inizio, operatore=operatore,
                        note=note, ml_per_kg=ml, giorni_somministrazione=gs, giorni_sospensione=gsosp,
                        registrato_da=registrato_da, gruppo=gruppo, colore=colore or None)
        db.session.add(t)
        db.session.flush()
        db.session.add(Somministrazione(trattamento_id=t.id, numero_giorno=1, data=data_inizio))
        creati.append(t)
    return creati


def ambito(t):
    return f"box {t.box_numero}" if t.box_numero else f"CAP {t.capannone_numero} (tutto)"


def animale(t):
    """'box 30, maiale 🔵 blu' / 'box 30' / 'CAP 4 (tutto)'"""
    if t.colore:
        return f"{ambito(t)}, maiale {EMOJI.get(t.colore, '')} {t.colore}"
    return ambito(t)


def da_ripetere_per_animale(ciclo_id):
    """Trattamenti con una dose da fare oggi, raggruppati per animale (stesso gruppo, o da soli):
    [{"chiave", "animale", "colore", "trattamenti": [(t, stato)], "riga": n}] — riga = la riga da fare
    sulla schiena (la dose successiva)."""
    from app.models import Trattamento
    from app.routes.allevamento import _stato_trattamento
    gruppi = {}
    for t in Trattamento.query.filter_by(ciclo_id=ciclo_id).order_by(Trattamento.data_inizio, Trattamento.id).all():
        s = _stato_trattamento(t)
        if not s["da_ripetere"]:
            continue
        chiave = t.gruppo or f"t{t.id}"
        g = gruppi.setdefault(chiave, {"chiave": chiave, "animale": animale(t), "colore": t.colore, "trattamenti": []})
        g["trattamenti"].append((t, s))
    for g in gruppi.values():
        g["riga"] = max(s["fatte"] for _, s in g["trattamenti"]) + 1
    return list(gruppi.values())


def riga_ordinale(n):
    return f"{n}ª riga"
