from datetime import date, timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required
from app import db
from app.models import Transaction, Category, RevenueStream, Tag

bp = Blueprint("prima_nota", __name__, url_prefix="/prima-nota")


@bp.route("/")
@login_required
def index():
    # Filters
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    tipo = request.args.get("tipo", "")  # entrata/uscita
    fonte = request.args.get("fonte", "")  # sdi/cassa/manuale
    ufficiale = request.args.get("ufficiale", "")  # si/no
    cat_id = request.args.get("categoria", "", type=str)
    stream_id = request.args.get("flusso", "", type=str)
    search = request.args.get("q", "").strip()

    query = Transaction.query

    if date_from:
        query = query.filter(Transaction.date >= date_from)
    if date_to:
        query = query.filter(Transaction.date <= date_to)
    if tipo:
        query = query.filter(Transaction.type == tipo)
    if fonte:
        query = query.filter(Transaction.source == fonte)
    if ufficiale == "si":
        query = query.filter(Transaction.official == True)
    elif ufficiale == "no":
        query = query.filter(Transaction.official == False)
    if cat_id:
        query = query.filter(Transaction.category_id == int(cat_id))
    if stream_id:
        query = query.filter(Transaction.revenue_stream_id == int(stream_id))
    if search:
        query = query.filter(Transaction.description.ilike(f"%{search}%"))

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Transaction.date.desc(), Transaction.id.desc()).paginate(page=page, per_page=50)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()

    return render_template("prima_nota/index.html",
        transactions=pagination.items, pagination=pagination,
        categories=categories, streams=streams,
    )
