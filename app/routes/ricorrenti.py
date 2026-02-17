from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import RecurringExpense, Transaction, Category, RevenueStream, Contact
from app.services.recurring_generator import generate_for_template
from app.utils.decorators import write_required

bp = Blueprint("ricorrenti", __name__, url_prefix="/ricorrenti")

FREQ_LABELS = {
    "mensile": "Mensile",
    "bimestrale": "Bimestrale",
    "trimestrale": "Trimestrale",
    "semestrale": "Semestrale",
    "annuale": "Annuale",
    "custom": "Personalizzata",
}


@bp.route("/")
@login_required
def index():
    filtro = request.args.get("filtro", "attivi")
    if filtro == "tutti":
        templates = RecurringExpense.query.order_by(RecurringExpense.name).all()
    elif filtro == "disattivati":
        templates = RecurringExpense.query.filter_by(active=False).order_by(RecurringExpense.name).all()
    else:
        templates = RecurringExpense.query.filter_by(active=True).order_by(RecurringExpense.name).all()

    return render_template("ricorrenti/index.html",
        templates=templates, filtro=filtro, freq_labels=FREQ_LABELS)


@bp.route("/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def new():
    if request.method == "POST":
        return _save_template(None)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    return render_template("ricorrenti/form.html", tpl=None,
        categories=categories, streams=streams, contacts=contacts, freq_labels=FREQ_LABELS)


@bp.route("/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def edit(id):
    tpl = RecurringExpense.query.get_or_404(id)
    if request.method == "POST":
        return _save_template(tpl)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    return render_template("ricorrenti/form.html", tpl=tpl,
        categories=categories, streams=streams, contacts=contacts, freq_labels=FREQ_LABELS)


@bp.route("/<int:id>/toggle", methods=["POST"])
@login_required
@write_required
def toggle(id):
    tpl = RecurringExpense.query.get_or_404(id)
    tpl.active = not tpl.active
    db.session.commit()
    stato = "attivato" if tpl.active else "disattivato"
    flash(f"Template \"{tpl.name}\" {stato}.", "success")
    return redirect(url_for("ricorrenti.index"))


@bp.route("/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def delete(id):
    tpl = RecurringExpense.query.get_or_404(id)
    tpl.active = False
    db.session.commit()
    flash(f"Template \"{tpl.name}\" disattivato.", "success")
    return redirect(url_for("ricorrenti.index"))


@bp.route("/<int:id>/genera", methods=["POST"])
@login_required
@write_required
def generate(id):
    tpl = RecurringExpense.query.get_or_404(id)
    count = generate_for_template(tpl)
    if count:
        flash(f"{count} transazioni generate per \"{tpl.name}\".", "success")
    else:
        flash(f"Nessuna nuova transazione da generare per \"{tpl.name}\".", "info")
    return redirect(url_for("ricorrenti.index"))


@bp.route("/<int:id>/transazioni")
@login_required
def transactions(id):
    tpl = RecurringExpense.query.get_or_404(id)
    txns = Transaction.query.filter_by(recurring_expense_id=id).order_by(
        Transaction.date.desc()
    ).all()
    return render_template("ricorrenti/transactions.html", tpl=tpl, transactions=txns)


def _save_template(tpl):
    try:
        is_new = tpl is None
        if is_new:
            tpl = RecurringExpense(created_by=current_user.id)

        tpl.name = request.form.get("name", "").strip()
        tpl.type = request.form.get("type", "uscita")
        tpl.frequency = request.form.get("frequency", "mensile")

        custom_days = request.form.get("custom_days", "").strip()
        tpl.custom_days = int(custom_days) if custom_days else None

        gen_months = request.form.get("generation_months", "3").strip()
        tpl.generation_months = int(gen_months) if gen_months else 3

        start_str = request.form.get("start_date", "").strip()
        tpl.start_date = date.fromisoformat(start_str) if start_str else date.today()

        end_str = request.form.get("end_date", "").strip()
        tpl.end_date = date.fromisoformat(end_str) if end_str else None

        tpl.description = request.form.get("description", "").strip()

        amount_str = request.form.get("amount", "0").strip()
        tpl.amount = float(amount_str) if amount_str else 0

        iva_str = request.form.get("iva_rate", "0").strip()
        tpl.iva_rate = float(iva_str) if iva_str else 0

        contact_id = request.form.get("contact_id", "").strip()
        tpl.contact_id = int(contact_id) if contact_id else None

        category_id = request.form.get("category_id", "").strip()
        tpl.category_id = int(category_id) if category_id else None

        stream_id = request.form.get("revenue_stream_id", "").strip()
        tpl.revenue_stream_id = int(stream_id) if stream_id else None

        tpl.payment_method = request.form.get("payment_method", "")
        tpl.payment_status = request.form.get("payment_status", "da_pagare")

        due_offset = request.form.get("due_days_offset", "0").strip()
        tpl.due_days_offset = int(due_offset) if due_offset else 0

        tpl.official = request.form.get("official") == "1"
        tpl.notes = request.form.get("notes", "").strip()

        if is_new:
            db.session.add(tpl)
            db.session.flush()  # get id before generating

        db.session.commit()

        # Genera subito se richiesto (solo in creazione)
        if is_new and request.form.get("generate_now") == "1":
            count = generate_for_template(tpl)
            if count:
                flash(f"Template creato e {count} transazioni generate.", "success")
            else:
                flash("Template creato. Nessuna transazione da generare al momento.", "success")
        else:
            flash("Template salvato.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Errore nel salvataggio: {e}", "danger")

    return redirect(url_for("ricorrenti.index"))
