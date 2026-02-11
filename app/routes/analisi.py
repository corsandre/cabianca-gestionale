from datetime import date
from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func
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

    total_income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "entrata", *base_filters
    ).scalar()

    total_expense = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "uscita", *base_filters
    ).scalar()

    total_iva = db.session.query(func.coalesce(func.sum(Transaction.iva_amount), 0)).filter(
        *base_filters
    ).scalar()

    by_category_income = db.session.query(
        Category.name, Category.color, func.sum(Transaction.amount)
    ).join(Transaction, Transaction.category_id == Category.id).filter(
        Transaction.type == "entrata", *base_filters
    ).group_by(Category.id).order_by(func.sum(Transaction.amount).desc()).all()

    by_category_expense = db.session.query(
        Category.name, Category.color, func.sum(Transaction.amount)
    ).join(Transaction, Transaction.category_id == Category.id).filter(
        Transaction.type == "uscita", *base_filters
    ).group_by(Category.id).order_by(func.sum(Transaction.amount).desc()).all()

    by_stream = db.session.query(
        RevenueStream.name, RevenueStream.color, func.sum(Transaction.amount)
    ).join(Transaction, Transaction.revenue_stream_id == RevenueStream.id).filter(
        Transaction.type == "entrata", *base_filters
    ).group_by(RevenueStream.id).order_by(func.sum(Transaction.amount).desc()).all()

    by_method = db.session.query(
        Transaction.payment_method, func.sum(Transaction.amount)
    ).filter(
        Transaction.payment_method != None, Transaction.payment_method != "",
        *base_filters
    ).group_by(Transaction.payment_method).all()

    # Calcola importi non assegnati per ogni raggruppamento
    _unassigned_color = "#aaaaaa"
    _unassigned_label = "Non assegnato"

    cat_income_total = sum(r[2] for r in by_category_income)
    if float(total_income) - cat_income_total > 0.01:
        by_category_income = list(by_category_income) + [
            (_unassigned_label, _unassigned_color, float(total_income) - cat_income_total)
        ]

    cat_expense_total = sum(r[2] for r in by_category_expense)
    if float(total_expense) - cat_expense_total > 0.01:
        by_category_expense = list(by_category_expense) + [
            (_unassigned_label, _unassigned_color, float(total_expense) - cat_expense_total)
        ]

    stream_total = sum(r[2] for r in by_stream)
    if float(total_income) - stream_total > 0.01:
        by_stream = list(by_stream) + [
            (_unassigned_label, _unassigned_color, float(total_income) - stream_total)
        ]

    method_total = sum(r[1] for r in by_method)
    all_total = float(total_income) + float(total_expense)
    if all_total - method_total > 0.01:
        by_method = list(by_method) + [
            (_unassigned_label, all_total - method_total)
        ]

    return render_template("analisi/index.html",
        total_income=float(total_income), total_expense=float(total_expense),
        total_iva=float(total_iva), net=float(total_income) - float(total_expense),
        by_category_income=by_category_income, by_category_expense=by_category_expense,
        by_stream=by_stream, by_method=by_method,
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
