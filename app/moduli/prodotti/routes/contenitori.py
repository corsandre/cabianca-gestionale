"""Contenitori (vasetti, bottiglie, buste…): peso standard e fogli di etichetta adatti (dalla 2.0.0).

Il prodotto è generico: il contenitore si sceglie nella ricetta (contenitori compatibili, con pesi propri se
diversi) e nel lotto (quanti pezzi di ognuno). Le etichette di una confezione propongono solo i fogli adatti
al suo contenitore. Un contenitore non si cancella: si spegne (i lotti ne conservano comunque la copia).
"""
from flask import jsonify, render_template

from app import db
from app.moduli.prodotti.models import Contenitore, FormatoEtichetta, RicettaContenitore
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.comune import dati_richiesta, errore, numero, vero
from app.utils.decorators import write_required

UNITA_CONTENITORE = ["g", "ml", "kg", "l"]


def contenitore_json(c):
    return {"id": c.id, "nome": c.nome, "peso_netto": c.peso_netto, "unita": c.unita, "peso_testo": c.peso_testo,
            "formato_predefinito_id": c.formato_predefinito_id, "attivo": bool(c.attivo), "note": c.note or "",
            "ordine": c.ordine, "formati": [str(f.id) for f in c.formati]}


def contenitori_attivi():
    return Contenitore.query.filter_by(attivo=True).order_by(Contenitore.ordine, Contenitore.nome).all()


@bp.route("/contenitori")
def contenitori():
    elenco = Contenitore.query.order_by(Contenitore.attivo.desc(), Contenitore.ordine, Contenitore.nome).all()
    uso = dict(db.session.query(RicettaContenitore.contenitore_id, db.func.count(RicettaContenitore.id))
               .group_by(RicettaContenitore.contenitore_id))
    formati = FormatoEtichetta.query.filter_by(attivo=True).order_by(FormatoEtichetta.id).all()
    return render_template("prodotti/contenitori.html", contenitori=elenco, uso=uso, formati=formati,
                           unita=UNITA_CONTENITORE, contenitori_json=[contenitore_json(c) for c in elenco])


@bp.route("/contenitori/salva", methods=["POST"])
@write_required
def salva_contenitore():
    d = dati_richiesta()
    nome = (d.get("nome") or "").strip()
    if not nome:
        return errore("Il nome è obbligatorio.")
    c = db.session.get(Contenitore, int(d["id"])) if d.get("id") else Contenitore()
    if c is None:
        return errore("Contenitore non trovato.", 404)
    doppione = Contenitore.query.filter(db.func.lower(Contenitore.nome) == nome.lower(),
                                        Contenitore.id != (c.id or 0)).first()
    if doppione:
        return errore(f"Esiste già un contenitore chiamato «{doppione.nome}».")
    ids = [numero(x, intero=True) for x in (d.get("formati") or [])]
    formati = [f for f in (db.session.get(FormatoEtichetta, i) for i in ids if i) if f]
    predefinito = numero(d.get("formato_predefinito_id"), intero=True)
    if predefinito and predefinito not in [f.id for f in formati]:
        f = db.session.get(FormatoEtichetta, predefinito)
        if f:
            formati.append(f)
    if not formati:
        return errore("Scegliere almeno un foglio di etichette adatto.")
    c.nome = nome
    c.peso_netto = numero(d.get("peso_netto"))
    c.unita = d.get("unita") if d.get("unita") in UNITA_CONTENITORE else "g"
    c.formati = formati
    c.formato_predefinito_id = predefinito or formati[0].id
    c.ordine = numero(d.get("ordine"), intero=True) or 0
    c.attivo = vero(d.get("attivo", True))
    c.note = (d.get("note") or "").strip() or None
    db.session.add(c)
    db.session.commit()
    return jsonify(ok=True, contenitore=contenitore_json(c))
