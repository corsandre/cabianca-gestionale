import json
from collections import defaultdict
from datetime import date
from flask import Blueprint, render_template, request, flash, redirect, url_for, current_app
from flask_login import login_required
from app import db
from app.models import CashRegisterDaily, Transaction
from app.services.cloud_office import sync_cash_register, REPARTI
from app.utils.decorators import write_required

bp = Blueprint("cassa", __name__, url_prefix="/cassa")


def _parse_details(record):
    """Parse the JSON details field from a CashRegisterDaily record."""
    if not record.details:
        return []
    try:
        return json.loads(record.details)
    except (json.JSONDecodeError, TypeError):
        return []


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

    # Parse details for each record
    records_with_details = []
    for r in records:
        records_with_details.append({
            "record": r,
            "details": _parse_details(r),
        })

    # Compute monthly totals per reparto
    reparto_totals = defaultdict(lambda: {"net": 0.0, "iva": 0.0, "total": 0.0})
    for rwd in records_with_details:
        for d in rwd["details"]:
            name = d.get("reparto", "Altro")
            reparto_totals[name]["net"] += d.get("net", 0)
            reparto_totals[name]["iva"] += d.get("iva", 0)
            reparto_totals[name]["total"] += d.get("total", 0)

    # Round totals
    for name in reparto_totals:
        for key in ("net", "iva", "total"):
            reparto_totals[name][key] = round(reparto_totals[name][key], 2)

    # Sort reparto_totals by the REPARTI order
    reparto_order = [r["name"] for r in REPARTI]
    sorted_reparto_totals = []
    for name in reparto_order:
        if name in reparto_totals:
            sorted_reparto_totals.append({"name": name, **reparto_totals[name]})
    # Add any extra reparti not in the config
    for name, vals in reparto_totals.items():
        if name not in reparto_order:
            sorted_reparto_totals.append({"name": name, **vals})

    return render_template(
        "cassa/index.html",
        records=records_with_details,
        month=month,
        total=total,
        reparto_totals=sorted_reparto_totals,
    )


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
