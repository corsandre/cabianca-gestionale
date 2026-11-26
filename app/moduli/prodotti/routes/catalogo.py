"""Materie prime e catalogo dei prodotti (con la scheda di ogni prodotto).

Le finestre di creazione/modifica salvano con POST JSON (vedi static/prodotti.js → prodPost) e
ricevono indietro l'oggetto salvato: così la stessa "nuova materia prima" si può creare anche da
dentro l'editor delle ricette senza lasciare la finestra.
"""
from flask import jsonify, redirect, render_template, request, url_for

from app import db
from app.moduli.prodotti.models import FormatoEtichetta, Lotto, MateriaPrima, Prodotto
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.comune import (
    adesso, crea_fornitore, dati_richiesta, errore, fornitori, nome_fornitore, numero, vero,
)
from app.moduli.prodotti.services.allergeni import ALLERGENI, NOMI_BREVI
from app.moduli.prodotti.services.lotti import proponi_sigla, pulisci_sigla
from app.utils.decorators import write_required

CATEGORIE = ["Confetture", "Mostarde", "Conserve e sottoli", "Sottaceti e agrodolci",
             "Passate e sughi", "Pasta fresca ripiena", "Salumi", "Farine", "Prodotti da forno",
             "Frutta secca e spezie", "Succhi", "Altro"]


# ---------------------------------------------------------------- materie prime

def materia_json(m):
    return {"id": m.id, "nome": m.nome, "nome_etichetta": m.nome_etichetta, "allergeni": m.allergeni_lista,
            "composta": m.composta or "", "unita": m.unita, "fornitore_id": m.fornitore_id,
            "fornitore_nome": m.fornitore_nome or "", "produzione_propria": bool(m.produzione_propria),
            "note": m.note or "", "attiva": bool(m.attiva)}


@bp.route("/materie-prime")
def materie_prime():
    q = (request.args.get("q") or "").strip()
    tutte = request.args.get("tutte") == "1"
    query = MateriaPrima.query
    if not tutte:
        query = query.filter_by(attiva=True)
    if q:
        query = query.filter(db.or_(MateriaPrima.nome.ilike(f"%{q}%"), MateriaPrima.nome_etichetta.ilike(f"%{q}%")))
    materie = query.order_by(MateriaPrima.nome).all()
    return render_template("prodotti/materie_prime.html", materie=materie, q=q, tutte=tutte,
                           fornitori=fornitori(), allergeni=ALLERGENI, nomi_allergeni=NOMI_BREVI,
                           materie_json=[materia_json(m) for m in materie])


@bp.route("/materie-prime/salva", methods=["POST"])
@write_required
def salva_materia():
    d = dati_richiesta()
    nome = (d.get("nome") or "").strip()
    if not nome:
        return errore("Il nome è obbligatorio.")
    m = db.session.get(MateriaPrima, int(d["id"])) if d.get("id") else MateriaPrima()
    if m is None:
        return errore("Materia prima non trovata.", 404)
    doppione = MateriaPrima.query.filter(db.func.lower(MateriaPrima.nome) == nome.lower(),
                                         MateriaPrima.id != (m.id or 0)).first()
    if doppione:
        return errore(f"Esiste già una materia prima chiamata «{doppione.nome}».")
    m.nome = nome
    m.nome_etichetta = (d.get("nome_etichetta") or "").strip() or nome.lower()
    m.allergeni_lista = d.get("allergeni") or []
    m.composta = (d.get("composta") or "").strip() or None
    m.unita = d.get("unita") or "g"
    m.produzione_propria = vero(d.get("produzione_propria"))
    if m.produzione_propria:
        m.fornitore_id, m.fornitore_nome = None, None
    elif (d.get("nuovo_fornitore") or "").strip():
        c = crea_fornitore(d["nuovo_fornitore"])
        m.fornitore_id, m.fornitore_nome = c.id, c.name
    else:
        m.fornitore_id = numero(d.get("fornitore_id"), intero=True)
        m.fornitore_nome = nome_fornitore(m.fornitore_id)
    m.note = (d.get("note") or "").strip() or None
    m.attiva = vero(d.get("attiva", True))
    db.session.add(m)
    db.session.commit()
    return jsonify(ok=True, materia=materia_json(m))


@bp.route("/fornitori/nuovo", methods=["POST"])
@write_required
def nuovo_fornitore():
    c = crea_fornitore(dati_richiesta().get("nome"))
    if not c:
        return errore("Scrivere il nome del fornitore.")
    return jsonify(ok=True, fornitore={"id": c.id, "nome": c.name})


# ---------------------------------------------------------------- prodotti

def prodotto_json(p):
    campi = ("id", "nome", "sottotitolo", "sigla", "categoria", "tipo_scadenza", "durata_giorni", "conservazione", "modalita_uso", "tracce", "prodotto_da",
             "lavorato_da", "dichiarazioni_extra", "ricetta_default_id", "note")
    out = {c: getattr(p, c) for c in campi}
    out.update(attivo=bool(p.attivo), da_verificare=bool(p.da_verificare), nome_completo=p.nome_completo)
    return out


@bp.route("/catalogo")
def catalogo():
    q = (request.args.get("q") or "").strip()
    tutti = request.args.get("tutti") == "1"
    query = Prodotto.query
    if not tutti:
        query = query.filter_by(attivo=True)
    if q:
        query = query.filter(db.or_(Prodotto.nome.ilike(f"%{q}%"), Prodotto.sigla.ilike(f"%{q}%"),
                                    Prodotto.categoria.ilike(f"%{q}%")))
    prodotti = query.order_by(Prodotto.categoria, Prodotto.nome).all()
    gruppi = {}
    for p in prodotti:
        gruppi.setdefault(p.categoria or "Senza categoria", []).append(p)
    ultimi = dict(db.session.query(Lotto.prodotto_id, db.func.max(Lotto.data_produzione))
                  .group_by(Lotto.prodotto_id).all())
    return render_template("prodotti/catalogo.html", gruppi=gruppi, q=q, tutti=tutti, ultimi=ultimi,
                           **_dati_modale_prodotto())


def _contenitori_attivi():
    from app.moduli.prodotti.routes.contenitori import contenitori_attivi
    return contenitori_attivi()


def _dati_modale_prodotto():
    from app.moduli.prodotti.models import Impostazione
    return {"categorie": CATEGORIE,
            "formati": FormatoEtichetta.query.filter_by(attivo=True).order_by(FormatoEtichetta.id).all(),
            "contenitori_attivi": _contenitori_attivi(),
            "tipi_scadenza": Prodotto.TIPI_SCADENZA,
            "produttore_predefinito": Impostazione.leggi("produttore", "")}


@bp.route("/catalogo/<int:id>")
def scheda_prodotto(id):
    p = db.session.get(Prodotto, id)
    if not p:
        return redirect(url_for("prodotti.catalogo"))
    from app.moduli.prodotti.routes.ricette import dati_editor     # qui per evitare un import circolare
    lotti = Lotto.query.filter_by(prodotto_id=id).order_by(Lotto.data_produzione.desc(), Lotto.id.desc()).all()
    return render_template("prodotti/prodotto.html", p=p, lotti=lotti, prodotto_json=prodotto_json(p),
                           **_dati_modale_prodotto(), **dati_editor())


@bp.route("/catalogo/sigla")
def proponi_sigla_api():
    """Sigla proposta per un nome (la finestra la chiede mentre si scrive il nome)."""
    return jsonify(sigla=proponi_sigla(request.args.get("nome", "")))


@bp.route("/catalogo/salva", methods=["POST"])
@write_required
def salva_prodotto():
    d = dati_richiesta()
    nome = (d.get("nome") or "").strip()
    sigla = pulisci_sigla(d.get("sigla") or proponi_sigla(nome))
    if not nome:
        return errore("Il nome è obbligatorio.")
    if not sigla:
        return errore("La sigla è obbligatoria (lettere o cifre, finisce nel codice lotto).")
    p = db.session.get(Prodotto, int(d["id"])) if d.get("id") else Prodotto()
    if p is None:
        return errore("Prodotto non trovato.", 404)
    for campo in ("sottotitolo", "categoria", "conservazione", "modalita_uso", "tracce", "prodotto_da",
                  "lavorato_da", "dichiarazioni_extra", "note"):
        setattr(p, campo, (d.get(campo) or "").strip() or None)
    p.nome, p.sigla = nome, sigla             # peso e formato: dalla 2.0.0 sono del contenitore (lotto)
    p.tipo_scadenza = d.get("tipo_scadenza") if d.get("tipo_scadenza") in Prodotto.TIPI_SCADENZA else "tmc"
    p.durata_giorni = numero(d.get("durata_giorni"), intero=True)
    if d.get("ricetta_default_id") is not None:
        p.ricetta_default_id = numero(d.get("ricetta_default_id"), intero=True)
    p.attivo = vero(d.get("attivo", True))
    if "da_verificare" in d:
        p.da_verificare = vero(d.get("da_verificare"))
    if not p.prodotto_da:
        from app.moduli.prodotti.models import Impostazione
        p.prodotto_da = Impostazione.leggi("produttore")
    p.modificato_il = adesso()
    db.session.add(p)
    db.session.commit()
    return jsonify(ok=True, prodotto=prodotto_json(p), url=url_for("prodotti.scheda_prodotto", id=p.id))


@bp.route("/catalogo/<int:id>/elimina", methods=["POST"])
@write_required
def elimina_prodotto(id):
    """Solo l'amministratore: cancella un prodotto e le sue ricette. Se ha lotti no: il libro lotti deve
    restare collegato al prodotto. Si eliminano prima i lotti, oppure si disattiva il prodotto."""
    from flask_login import current_user
    from app.moduli.prodotti.models import Lotto, Ricetta, RicettaContenitore, RicettaRiga
    if current_user.role != "admin":                       # JSON, non la pagina 403 di admin_required
        return errore("Solo l'amministratore può eliminare un prodotto.", 403)
    p = db.session.get(Prodotto, id)
    if not p:
        return errore("Prodotto non trovato.", 404)
    n_lotti = Lotto.query.filter_by(prodotto_id=id).count()
    if n_lotti:
        return errore(f"{p.nome_completo} ha {n_lotti} lott{'o' if n_lotti == 1 else 'i'} nel libro lotti: "
                      "eliminare prima i lotti, oppure disattivare il prodotto (Modifica → Attivo).")
    nome = p.nome_completo
    ricette = [r.id for r in Ricetta.query.filter_by(prodotto_id=id)]
    if ricette:
        RicettaContenitore.query.filter(RicettaContenitore.ricetta_id.in_(ricette)).delete(synchronize_session=False)
        RicettaRiga.query.filter(RicettaRiga.ricetta_id.in_(ricette)).delete(synchronize_session=False)
        Ricetta.query.filter(Ricetta.id.in_(ricette)).delete(synchronize_session=False)
    Prodotto.query.filter_by(id=id).delete(synchronize_session=False)
    db.session.commit()
    db.session.expunge_all()
    return jsonify(ok=True, nome=nome, url=url_for("prodotti.catalogo"))
