from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import Transaction, Category, RevenueStream, Contact, Tag
from app.utils.decorators import write_required

bp = Blueprint("movimenti", __name__, url_prefix="/movimenti")


@bp.route("/")
@login_required
def index():
    page = request.args.get("page", 1, type=int)
    pagination = Transaction.query.filter_by(source="manuale").order_by(
        Transaction.date.desc(), Transaction.id.desc()
    ).paginate(page=page, per_page=50)

    return render_template("movimenti/index.html", transactions=pagination.items, pagination=pagination)


@bp.route("/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def new():
    if request.method == "POST":
        return _save_transaction(None)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template("movimenti/form.html", t=None,
        categories=categories, streams=streams, contacts=contacts, tags=tags)


@bp.route("/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def edit(id):
    t = Transaction.query.get_or_404(id)
    if request.method == "POST":
        return _save_transaction(t)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    next_url = request.args.get("next")
    return render_template("movimenti/form.html", t=t,
        categories=categories, streams=streams, contacts=contacts, tags=tags, next_url=next_url)


@bp.route("/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def delete(id):
    t = Transaction.query.get_or_404(id)
    db.session.delete(t)
    db.session.commit()
    flash("Movimento eliminato.", "success")
    next_url = request.form.get("next") or request.args.get("next")
    return redirect(next_url or url_for("movimenti.index"))


def _save_transaction(t):
    try:
        is_new = t is None
        if is_new:
            t = Transaction(source="manuale", created_by=current_user.id)

        t.type = request.form.get("type", "uscita")
        t.official = request.form.get("official") == "1"

        # Parse amount safely
        amount_str = request.form.get("amount", "0").strip()
        t.amount = float(amount_str) if amount_str else 0

        iva_str = request.form.get("iva_rate", "0").strip()
        t.iva_rate = float(iva_str) if iva_str else 0

        if t.iva_rate > 0 and t.amount > 0:
            t.net_amount = round(t.amount / (1 + t.iva_rate / 100), 2)
            t.iva_amount = round(t.amount - t.net_amount, 2)
        else:
            t.net_amount = t.amount
            t.iva_amount = 0

        # Parse date safely
        date_str = request.form.get("date", "").strip()
        t.date = date.fromisoformat(date_str) if date_str else date.today()

        t.description = request.form.get("description", "").strip()

        # Foreign keys - convert empty strings to None
        contact_id = request.form.get("contact_id", "").strip()
        t.contact_id = int(contact_id) if contact_id else None

        category_id = request.form.get("category_id", "").strip()
        t.category_id = int(category_id) if category_id else None

        stream_id = request.form.get("revenue_stream_id", "").strip()
        t.revenue_stream_id = int(stream_id) if stream_id else None

        t.payment_method = request.form.get("payment_method", "")
        t.payment_status = request.form.get("payment_status", "pagato")

        # Parse optional dates
        due_str = request.form.get("due_date", "").strip()
        t.due_date = date.fromisoformat(due_str) if due_str else None

        pay_str = request.form.get("payment_date", "").strip()
        t.payment_date = date.fromisoformat(pay_str) if pay_str else None

        t.notes = request.form.get("notes", "").strip()

        # Tags
        tag_ids = request.form.getlist("tags")
        t.tags = Tag.query.filter(Tag.id.in_(tag_ids)).all() if tag_ids else []

        if is_new:
            db.session.add(t)
        db.session.commit()
        flash("Movimento salvato.", "success")

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving transaction: {e}")
        flash(f"Errore nel salvataggio: {e}", "danger")

    next_url = request.form.get("next") or request.args.get("next")
    return redirect(next_url or url_for("movimenti.index"))
