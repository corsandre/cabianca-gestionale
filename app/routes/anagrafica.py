from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import Contact
from app.utils.decorators import write_required

bp = Blueprint("anagrafica", __name__, url_prefix="/anagrafica")

CONTACT_TYPES = [
    ("cliente_privato", "Cliente privato"),
    ("cliente_b2b", "Cliente B2B"),
    ("scuola_ente", "Scuola / Ente"),
    ("fornitore", "Fornitore"),
]


@bp.route("/")
@login_required
def index():
    tipo = request.args.get("tipo", "")
    search = request.args.get("q", "").strip()

    query = Contact.query.filter_by(active=True)
    if tipo:
        query = query.filter_by(type=tipo)
    if search:
        query = query.filter(
            db.or_(
                Contact.name.ilike(f"%{search}%"),
                Contact.partita_iva.ilike(f"%{search}%"),
                Contact.ragione_sociale.ilike(f"%{search}%"),
            )
        )

    contacts = query.order_by(Contact.name).all()
    return render_template("anagrafica/index.html", contacts=contacts, contact_types=CONTACT_TYPES)


@bp.route("/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def new():
    if request.method == "POST":
        return _save_contact(None)
    return render_template("anagrafica/form.html", c=None, contact_types=CONTACT_TYPES)


@bp.route("/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def edit(id):
    c = Contact.query.get_or_404(id)
    if request.method == "POST":
        return _save_contact(c)
    return render_template("anagrafica/form.html", c=c, contact_types=CONTACT_TYPES)


@bp.route("/<int:id>")
@login_required
def detail(id):
    c = Contact.query.get_or_404(id)
    from app.models import Transaction
    transactions = Transaction.query.filter_by(contact_id=id).order_by(Transaction.date.desc()).limit(50).all()
    return render_template("anagrafica/detail.html", c=c, transactions=transactions)


@bp.route("/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def delete(id):
    c = Contact.query.get_or_404(id)
    c.active = False
    db.session.commit()
    flash("Contatto disattivato.", "success")
    return redirect(url_for("anagrafica.index"))


def _save_contact(c):
    is_new = c is None
    if is_new:
        c = Contact()

    c.type = request.form.get("type", "fornitore")
    c.name = request.form.get("name", "").strip()
    c.ragione_sociale = request.form.get("ragione_sociale", "").strip()
    c.partita_iva = request.form.get("partita_iva", "").strip()
    c.codice_fiscale = request.form.get("codice_fiscale", "").strip()
    c.codice_sdi = request.form.get("codice_sdi", "").strip()
    c.pec = request.form.get("pec", "").strip()
    c.email = request.form.get("email", "").strip()
    c.phone = request.form.get("phone", "").strip()
    c.address = request.form.get("address", "").strip()
    c.city = request.form.get("city", "").strip()
    c.province = request.form.get("province", "").strip()
    c.cap = request.form.get("cap", "").strip()
    c.notes = request.form.get("notes", "").strip()

    if is_new:
        db.session.add(c)
    db.session.commit()
    flash("Contatto salvato.", "success")
    return redirect(url_for("anagrafica.detail", id=c.id))
