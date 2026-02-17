import os
import logging

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import SdiInvoice, Transaction, BankTransaction
from app.services.sdi_importer import import_sdi_xml
from app.utils.decorators import write_required

logger = logging.getLogger(__name__)

bp = Blueprint("fatture", __name__, url_prefix="/fatture")


@bp.route("/")
@login_required
def index():
    direction = request.args.get("direction", "")
    search = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    invoice_type = request.args.get("tipo", "")

    banca_filter = request.args.getlist("banca")

    query = SdiInvoice.query
    if direction:
        query = query.filter_by(direction=direction)
    if invoice_type:
        query = query.filter_by(invoice_type=invoice_type)
    if date_from:
        query = query.filter(SdiInvoice.invoice_date >= date_from)
    if date_to:
        query = query.filter(SdiInvoice.invoice_date <= date_to)
    if search:
        query = query.filter(
            db.or_(
                SdiInvoice.sender_name.ilike(f"%{search}%"),
                SdiInvoice.invoice_number.ilike(f"%{search}%"),
                SdiInvoice.sender_partita_iva.ilike(f"%{search}%"),
            )
        )

    # Filtro stato banca (multi-select)
    if banca_filter:
        # Subquery: fatture riconciliate (hanno Transaction con BankTransaction match)
        riconciliato_sq = db.session.query(Transaction.invoice_id).join(
            BankTransaction, BankTransaction.matched_transaction_id == Transaction.id
        ).filter(Transaction.invoice_id.isnot(None)).subquery()
        # Subquery: fatture pagate in contanti
        contanti_sq = db.session.query(Transaction.invoice_id).filter(
            Transaction.payment_method == "contanti",
            Transaction.payment_status == "pagato",
            Transaction.invoice_id.isnot(None),
        ).subquery()

        conditions = []
        if "riconciliato" in banca_filter:
            conditions.append(SdiInvoice.id.in_(db.select(riconciliato_sq)))
        if "contanti" in banca_filter:
            conditions.append(
                db.and_(
                    SdiInvoice.id.in_(db.select(contanti_sq)),
                    ~SdiInvoice.id.in_(db.select(riconciliato_sq)),
                )
            )
        if "vuoto" in banca_filter:
            conditions.append(
                db.and_(
                    ~SdiInvoice.id.in_(db.select(riconciliato_sq)),
                    ~SdiInvoice.id.in_(db.select(contanti_sq)),
                )
            )
        query = query.filter(db.or_(*conditions))

    total_count = query.count()
    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(SdiInvoice.invoice_date.desc()).paginate(page=page, per_page=50)

    # Pre-carica stato riconciliazione per ogni fattura
    invoice_ids = [inv.id for inv in pagination.items]
    # Trova le transazioni associate e il loro stato di riconciliazione bancaria
    bank_status = {}
    if invoice_ids:
        results = db.session.query(
            Transaction.invoice_id,
            BankTransaction.id,
            BankTransaction.status,
            Transaction.payment_method,
            Transaction.payment_status,
        ).outerjoin(
            BankTransaction, BankTransaction.matched_transaction_id == Transaction.id
        ).filter(
            Transaction.invoice_id.in_(invoice_ids)
        ).all()
        cash_paid = set()
        for inv_id, bt_id, bt_status, pay_method, pay_status in results:
            if bt_id:
                bank_status[inv_id] = "riconciliato"
            elif inv_id not in bank_status:
                bank_status[inv_id] = None
            if pay_method == "contanti" and pay_status == "pagato":
                cash_paid.add(inv_id)
    else:
        cash_paid = set()

    # Tipi fattura distinti per il filtro
    invoice_types = [r[0] for r in db.session.query(SdiInvoice.invoice_type).distinct().order_by(SdiInvoice.invoice_type).all() if r[0]]

    return render_template("fatture/index.html", invoices=pagination.items,
                          pagination=pagination, bank_status=bank_status,
                          cash_paid=cash_paid, total_count=total_count,
                          invoice_types=invoice_types)


@bp.route("/upload", methods=["GET", "POST"])
@login_required
@write_required
def upload():
    if request.method == "POST":
        files = request.files.getlist("xml_files")
        if not files or not files[0].filename:
            flash("Seleziona almeno un file XML.", "warning")
            return redirect(url_for("fatture.upload"))

        imported = 0
        skipped = 0
        for file in files:
            if not file.filename.lower().endswith(".xml"):
                skipped += 1
                continue
            result = import_sdi_xml(file.read(), file.filename, uploaded_by=current_user.id)
            if result["status"] == "imported":
                imported += 1
            else:
                skipped += 1

        db.session.commit()
        if imported:
            flash(f"{imported} fatture importate con successo.", "success")
        if skipped:
            flash(f"{skipped} file ignorati (errori o duplicati).", "warning")
        return redirect(url_for("fatture.index"))

    return render_template("fatture/upload.html")


@bp.route("/controlla-email", methods=["POST"])
@login_required
@write_required
def check_email():
    from app.services.email_fetcher import fetch_sdi_emails
    stats = fetch_sdi_emails(current_app._get_current_object())
    if stats["imported"]:
        flash(f"{stats['imported']} fatture importate da email.", "success")
    if stats["duplicates"]:
        flash(f"{stats['duplicates']} duplicati ignorati.", "info")
    if stats["errors"]:
        flash(f"{stats['errors']} errori durante l'importazione.", "warning")
    if not stats["imported"] and not stats["duplicates"] and not stats["errors"]:
        flash("Nessuna nuova fattura trovata nelle email.", "info")
    return redirect(url_for("fatture.index"))


@bp.route("/<int:id>")
@login_required
def detail(id):
    invoice = SdiInvoice.query.get_or_404(id)
    transactions = Transaction.query.filter_by(invoice_id=id).all()
    return render_template("fatture/detail.html", invoice=invoice, transactions=transactions)


@bp.route("/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def delete(id):
    invoice = SdiInvoice.query.get_or_404(id)
    Transaction.query.filter_by(invoice_id=id).delete()
    db.session.delete(invoice)
    db.session.commit()
    flash("Fattura e movimenti collegati eliminati.", "success")
    return redirect(url_for("fatture.index"))
