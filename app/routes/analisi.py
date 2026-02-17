import json
from datetime import date
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload
from app import db
from app.models import Transaction, Category, RevenueStream

bp = Blueprint("analisi", __name__, url_prefix="/analisi")


def _official_filter(filter_type):
    if filter_type == "ufficiali":
        return [Transaction.official == True]
    elif filter_type == "extra":
        return [Transaction.official == False]
    return []


@bp.route("/")
@login_required
def index():
    today = date.today()
    date_from = request.args.get("date_from", today.replace(month=1, day=1).isoformat())
    date_to = request.args.get("date_to", today.isoformat())
    filter_type = request.args.get("filter_type", "tutti")

    base_filters = [Transaction.date.between(date_from, date_to)] + _official_filter(filter_type)

    # Fetch all transactions in period with eager loading
    transactions = Transaction.query.options(
        joinedload(Transaction.category),
        joinedload(Transaction.revenue_stream),
        joinedload(Transaction.contact),
    ).filter(*base_filters).order_by(Transaction.date.desc()).all()

    # Build JSON-serializable transaction list for JS
    tx_data = [{
        'id': t.id,
        'date': t.date.isoformat(),
        'description': t.description or '',
        'type': t.type,
        'source': t.source,
        'amount': float(t.amount),
        'iva_amount': float(t.iva_amount or 0),
        'category_id': t.category_id,
        'category_name': t.category.name if t.category else None,
        'category_color': t.category.color if t.category else None,
        'stream_id': t.revenue_stream_id,
        'stream_name': t.revenue_stream.name if t.revenue_stream else None,
        'stream_color': t.revenue_stream.color if t.revenue_stream else None,
        'contact_name': t.contact.name if t.contact else None,
        'payment_status': t.payment_status,
        'official': t.official,
    } for t in transactions]

    return render_template("analisi/index.html",
        tx_json=json.dumps(tx_data),
        date_from=date_from, date_to=date_to, filter_type=filter_type,
    )


@bp.route("/esporta")
@login_required
def export():
    from app.services.export import generate_csv
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    filter_type = request.args.get("filter_type", "tutti")

    query = Transaction.query.filter(Transaction.date.between(date_from, date_to))
    if filter_type == "ufficiali":
        query = query.filter(Transaction.official == True)
    elif filter_type == "extra":
        query = query.filter(Transaction.official == False)

    transactions = query.order_by(Transaction.date).all()
    return generate_csv(transactions)
