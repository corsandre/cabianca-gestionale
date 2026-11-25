"""Richiamo: «in quali lotti è finito il lotto X dello zucchero del fornitore Y?» (rintracciabilità in avanti).

Si cerca per materia prima, lotto del fornitore (anche parziale), fornitore e periodo di produzione.
Il risultato elenca i lotti di prodotto coinvolti con gli ingredienti che corrispondono; si possono
segnare «ritirati» in blocco (il motivo resta nel registro e nello storico) ed esportare in PDF.
"""
from flask import jsonify, render_template, request

from app import db
from app.moduli.prodotti.models import Lotto, LottoIngrediente, MateriaPrima
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.comune import adesso, dati_richiesta, errore, fornitori, utente
from app.utils.decorators import write_required

CAMPI = ("materia", "lotto", "fornitore", "dal", "al")


def cerca(f):
    """Lista di (lotto, [righe ingredienti che corrispondono]) dal più recente; None se non c'è nessun criterio."""
    if not any(f[c] for c in ("materia", "lotto", "fornitore")):
        return None
    q = LottoIngrediente.query.join(Lotto)
    if f["materia"]:
        q = q.filter(LottoIngrediente.materia_prima_id == int(f["materia"]))
    if f["lotto"]:
        q = q.filter(LottoIngrediente.lotto_fornitore.ilike(f"%{f['lotto']}%"))
    if f["fornitore"]:
        q = q.filter(LottoIngrediente.fornitore_id == int(f["fornitore"]))
    if f["dal"]:
        q = q.filter(Lotto.data_produzione >= f["dal"])
    if f["al"]:
        q = q.filter(Lotto.data_produzione <= f["al"])
    gruppi = {}
    for r in q.order_by(Lotto.data_produzione.desc(), Lotto.id.desc()).all():
        gruppi.setdefault(r.lotto_id, (r.lotto, []))[1].append(r)
    return list(gruppi.values())


def descrivi(f):
    parti = []
    if f["materia"]:
        m = db.session.get(MateriaPrima, int(f["materia"]))
        parti.append(f"materia prima {m.nome if m else '?'}")
    if f["lotto"]:
        parti.append(f"lotto fornitore contenente «{f['lotto']}»")
    if f["fornitore"]:
        from app.models import Contact
        c = db.session.get(Contact, int(f["fornitore"]))
        parti.append(f"fornitore {c.name if c else '?'}")
    if f["dal"] or f["al"]:
        parti.append(f"prodotti dal {f['dal'] or 'inizio'} al {f['al'] or 'oggi'}")
    return ", ".join(parti)


@bp.route("/richiamo")
def richiamo():
    f = {c: (request.args.get(c) or "").strip() for c in CAMPI}
    risultati = cerca(f)
    pezzi = sum(l.pezzi_prodotti or 0 for l, _ in risultati) if risultati else 0
    return render_template("prodotti/richiamo.html", f=f, risultati=risultati, pezzi=pezzi, criteri=descrivi(f),
                           materie=MateriaPrima.query.order_by(MateriaPrima.nome).all(), fornitori=fornitori(),
                           stati=Lotto.STATI)


@bp.route("/richiamo/ritira", methods=["POST"])
@write_required
def ritira_lotti():
    d = dati_richiesta()
    motivo = (d.get("motivo") or "").strip()
    if not motivo:
        return errore("Indicare il motivo del ritiro (resta nel registro).")
    ids = [int(i) for i in d.get("ids") or []]
    if not ids:
        return errore("Nessun lotto selezionato.")
    lotti = Lotto.query.filter(Lotto.id.in_(ids)).all()
    for l in lotti:
        l.stato, l.stato_motivo = "ritirato", motivo
        l.modificato_da, l.modificato_il = utente(), adesso()
    db.session.commit()
    return jsonify(ok=True, n=len(lotti))


@bp.route("/richiamo/esporta.pdf")
def esporta_richiamo():
    from app.moduli.prodotti.routes.esporta import pdf_da_modello
    f = {c: (request.args.get(c) or "").strip() for c in CAMPI}
    risultati = cerca(f) or []
    return pdf_da_modello("prodotti/stampe/richiamo.html", "richiamo.pdf", orizzontale=True,
                          titolo="Ricerca per richiamo", sottotitolo=descrivi(f) or "nessun criterio",
                          risultati=risultati, stati=Lotto.STATI,
                          pezzi=sum(l.pezzi_prodotti or 0 for l, _ in risultati))
