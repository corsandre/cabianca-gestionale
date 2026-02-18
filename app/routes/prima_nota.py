from datetime import date, timedelta
from flask import Blueprint, render_template, request
from flask_login import login_required
from app import db
from app.models import Transaction, Category, RevenueStream, Tag, BankTransaction

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
    elif not date_from:
        # Default: show up to 30 days in the future (user can override with filters)
        default_horizon = date.today() + timedelta(days=30)
        query = query.filter(Transaction.date <= default_horizon)
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

    # Filtro stato banca (multi-select)
    banca_filter = request.args.getlist("banca")
    if banca_filter:
        # Subquery: transaction IDs riconciliati
        riconciliato_sq = db.session.query(
            BankTransaction.matched_transaction_id
        ).filter(
            BankTransaction.matched_transaction_id.isnot(None)
        ).subquery()

        conditions = []
        if "riconciliato" in banca_filter:
            conditions.append(Transaction.id.in_(db.select(riconciliato_sq)))
        if "contanti" in banca_filter:
            conditions.append(
                db.and_(
                    Transaction.payment_method == "contanti",
                    Transaction.payment_status == "pagato",
                    ~Transaction.id.in_(db.select(riconciliato_sq)),
                )
            )
        if "in_attesa" in banca_filter:
            conditions.append(
                db.and_(
                    ~Transaction.id.in_(db.select(riconciliato_sq)),
                    db.or_(
                        Transaction.payment_method != "contanti",
                        Transaction.payment_method.is_(None),
                        Transaction.payment_status != "pagato",
                        Transaction.payment_status.is_(None),
                    ),
                )
            )
        query = query.filter(db.or_(*conditions))

    total_count = query.count()
    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(Transaction.date.desc(), Transaction.id.desc()).paginate(page=page, per_page=50)

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()

    return render_template("prima_nota/index.html",
        transactions=pagination.items, pagination=pagination,
        total_count=total_count,
        categories=categories, streams=streams,
    )
