"""Ricettario: elenco, editor delle ricette (finestra con righe dinamiche) e anteprima dell'elenco ingredienti.

Versioni: una ricetta già usata in un lotto non si modifica (lo impedisce anche il database). Se la si
modifica dall'editor, il salvataggio crea in automatico la versione successiva e lo dice.
"""
from flask import jsonify, render_template, request

from app import db
from app.moduli.prodotti.models import Lotto, MateriaPrima, Prodotto, Ricetta, RicettaRiga
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.catalogo import materia_json
from app.moduli.prodotti.routes.comune import dati_richiesta, errore, fornitori, numero, utente, vero
from app.moduli.prodotti.services import ingredienti as ing
from app.moduli.prodotti.services.allergeni import ALLERGENI, descrivi
from app.utils.decorators import write_required

UNITA = ["g", "kg", "ml", "l", "pz"]


def ricetta_json(r):
    return {"id": r.id, "prodotto_id": r.prodotto_id, "versione": r.versione, "nome": r.nome or "",
            "resa_pezzi": r.resa_pezzi, "resa_kg": r.resa_kg, "procedimento": r.procedimento or "",
            "note_haccp": r.note_haccp or "", "attiva": bool(r.attiva), "usata": r.usata,
            "predefinita": r.prodotto.ricetta_default_id == r.id if r.prodotto else False,
            "righe": [{"materia_prima_id": x.materia_prima_id, "nome": x.materia_prima.nome,
                       "quantita": x.quantita, "unita": x.unita, "nota": x.nota or ""} for x in r.righe]}


def dati_editor():
    """Quello che serve alla finestra dell'editor (inclusa in più pagine)."""
    materie = MateriaPrima.query.filter_by(attiva=True).order_by(MateriaPrima.nome).all()
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome, Prodotto.peso_netto).all()
    return {"materie_json": [materia_json(m) for m in materie],
            "prodotti_scelta": [{"id": p.id, "nome": p.nome_completo} for p in prodotti],
            "unita_ricetta": UNITA, "allergeni": ALLERGENI, "fornitori": fornitori()}


@bp.route("/ricettario")
def ricettario():
    q = (request.args.get("q") or "").strip()
    query = Prodotto.query.join(Ricetta).distinct()
    if q:
        query = query.filter(Prodotto.nome.ilike(f"%{q}%"))
    prodotti = query.order_by(Prodotto.nome, Prodotto.peso_netto).all()
    usate = {r[0] for r in db.session.query(Lotto.ricetta_id).distinct()}
    senza = (Prodotto.query.filter_by(attivo=True)
             .filter(~Prodotto.id.in_(db.session.query(Ricetta.prodotto_id))).order_by(Prodotto.nome).all())
    return render_template("prodotti/ricettario.html", prodotti=prodotti, usate=usate, senza=senza, q=q,
                           descrivi_allergeni=descrivi, **dati_editor())


@bp.route("/ricette/<int:id>")
def ricetta_dati(id):
    r = db.session.get(Ricetta, id)
    if not r:
        return errore("Ricetta non trovata.", 404)
    return jsonify(ok=True, ricetta=ricetta_json(r))


@bp.route("/ricette/anteprima", methods=["POST"])
def anteprima_ingredienti():
    """Elenco ingredienti di legge per le righe in corso di scrittura (l'editor lo chiede mentre si digita)."""
    righe = []
    for x in (dati_richiesta().get("righe") or []):
        m = db.session.get(MateriaPrima, numero(x.get("materia_prima_id"), intero=True) or 0)
        if m:
            righe.append(m.come_riga_ricetta(numero(x.get("quantita")), x.get("unita")))
    testo = ing.testo_ingredienti(righe)
    allergeni = ing.allergeni_presenti(righe)
    return jsonify(ok=True, testo=testo, html=ing.testo_html(testo), allergeni=allergeni,
                   allergeni_testo=descrivi(allergeni), percentuali=ing.percentuali(righe))


@bp.route("/ricette/salva", methods=["POST"])
@write_required
def salva_ricetta():
    d = dati_richiesta()
    prodotto = db.session.get(Prodotto, numero(d.get("prodotto_id"), intero=True) or 0)
    if not prodotto:
        return errore("Scegliere il prodotto.")
    righe = []
    for i, x in enumerate(d.get("righe") or []):
        mp_id, q = numero(x.get("materia_prima_id"), intero=True), numero(x.get("quantita"))
        if not mp_id and not q:
            continue                                   # riga vuota lasciata in fondo
        if not mp_id or not db.session.get(MateriaPrima, mp_id):
            return errore(f"Riga {i + 1}: scegliere una materia prima dall'elenco (o crearla con «＋»).")
        if not q or q <= 0:
            return errore(f"Riga {i + 1}: quantità mancante.")
        righe.append(RicettaRiga(materia_prima_id=mp_id, quantita=q, unita=x.get("unita") or "g",
                                 ordine=i, nota=(x.get("nota") or "").strip() or None))
    if not righe:
        return errore("La ricetta deve avere almeno un ingrediente.")

    esistente = db.session.get(Ricetta, int(d["id"])) if d.get("id") else None
    nuova_versione = esistente is None or esistente.usata or vero(d.get("nuova_versione"))
    if nuova_versione:
        ultima = db.session.query(db.func.max(Ricetta.versione)).filter_by(prodotto_id=prodotto.id).scalar() or 0
        r = Ricetta(prodotto_id=prodotto.id, versione=ultima + 1, creato_da=utente())
    else:
        r = esistente
        if r.prodotto_id != prodotto.id:
            return errore("Una ricetta non si sposta su un altro prodotto: crearne una nuova.")
        r.righe.clear()
        db.session.flush()
    r.nome = (d.get("nome") or "").strip() or None
    r.resa_pezzi = numero(d.get("resa_pezzi"), intero=True)
    r.resa_kg = numero(d.get("resa_kg"))
    r.procedimento = (d.get("procedimento") or "").strip() or None
    r.note_haccp = (d.get("note_haccp") or "").strip() or None
    r.attiva = True
    r.righe.extend(righe)
    db.session.add(r)
    db.session.flush()
    # la prima ricetta di un prodotto, o quella indicata, diventa la predefinita per i nuovi lotti
    if vero(d.get("predefinita")) or not prodotto.ricetta_default_id or (
            esistente is not None and prodotto.ricetta_default_id == esistente.id):
        prodotto.ricetta_default_id = r.id
    db.session.commit()
    messaggio = None
    if esistente is not None and r.id != esistente.id:
        messaggio = (f"La v{esistente.versione} è già usata in un lotto e resta com'è: "
                     f"salvata come nuova versione v{r.versione}.")
    return jsonify(ok=True, ricetta=ricetta_json(r), messaggio=messaggio)


@bp.route("/ricette/<int:id>/attiva", methods=["POST"])
@write_required
def attiva_ricetta(id):
    r = db.session.get(Ricetta, id)
    if not r:
        return errore("Ricetta non trovata.", 404)
    r.attiva = vero(dati_richiesta().get("attiva"))
    db.session.commit()
    return jsonify(ok=True, attiva=r.attiva)
