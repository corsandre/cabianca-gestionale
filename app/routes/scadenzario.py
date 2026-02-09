from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import Transaction
from app.utils.decorators import write_required

bp = Blueprint("scadenzario", __name__, url_prefix="/scadenzario")


@bp.route("/")
@login_required
def index():
    today = date.today()
    status = request.args.get("status", "aperte")

    query = Transaction.query.filter(Transaction.due_date != None)

    if status == "aperte":
        query = query.filter(Transaction.payment_status.in_(["da_pagare", "parziale"]))
    elif status == "scadute":
        query = query.filter(
            Transaction.payment_status.in_(["da_pagare", "parziale"]),
            Transaction.due_date < today,
        )

    deadlines = query.order_by(Transaction.due_date.asc()).all()
    return render_template("scadenzario/index.html", deadlines=deadlines, today=today)


@bp.route("/<int:id>/segna-pagato", methods=["POST"])
@login_required
@write_required
def mark_paid(id):
    t = Transaction.query.get_or_404(id)
    t.payment_status = "pagato"
    t.payment_date = date.today()
    db.session.commit()
    flash("Segnato come pagato.", "success")
    return redirect(url_for("scadenzario.index"))
