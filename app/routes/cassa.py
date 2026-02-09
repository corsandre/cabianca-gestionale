from datetime import date, timedelta
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required
from app import db
from app.models import CashRegisterDaily, Transaction
from app.services.cloud_office import sync_cash_register
from app.utils.decorators import write_required

bp = Blueprint("cassa", __name__, url_prefix="/cassa")


@bp.route("/")
@login_required
def index():
    month = request.args.get("month", date.today().strftime("%Y-%m"))
    try:
        year, mo = map(int, month.split("-"))
    except ValueError:
        year, mo = date.today().year, date.today().month

    records = CashRegisterDaily.query.filter(
        db.extract("year", CashRegisterDaily.date) == year,
        db.extract("month", CashRegisterDaily.date) == mo,
    ).order_by(CashRegisterDaily.date.desc()).all()

    total = sum(r.total_amount for r in records)

    return render_template("cassa/index.html", records=records, month=month, total=total)


@bp.route("/sync", methods=["POST"])
@login_required
@write_required
def sync():
    try:
        count = sync_cash_register()
        flash(f"Sincronizzazione completata: {count} giorni aggiornati.", "success")
    except Exception as e:
        flash(f"Errore di sincronizzazione: {e}", "danger")
    return redirect(url_for("cassa.index"))
