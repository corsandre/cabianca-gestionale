"""Routes per la riconciliazione bancaria."""

import uuid
import logging
from datetime import date
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from app import db
from app.models import (
    BankTransaction, AutoRule, Transaction, Category, Contact, RevenueStream,
)
from app.services.cbi_parser import parse_cbi_file
from app.services.reconciliation import (
    reconcile_batch, get_match_proposals, create_transaction_from_bank_manual,
)
from app.utils.decorators import write_required

logger = logging.getLogger(__name__)

bp = Blueprint("banca", __name__, url_prefix="/banca")


@bp.route("/")
@login_required
def index():
    """Dashboard banca: statistiche, upload, ultimi movimenti."""
    total = BankTransaction.query.count()
    riconciliati = BankTransaction.query.filter_by(status="riconciliato").count()
    sospesi = BankTransaction.query.filter_by(status="non_riconciliato").count()
    ignorati = BankTransaction.query.filter_by(status="ignorato").count()

    ultimi = BankTransaction.query.order_by(
        BankTransaction.operation_date.desc()
    ).limit(20).all()

    rules_count = AutoRule.query.filter_by(active=True).count()

    return render_template(
        "banca/index.html",
        total=total,
        riconciliati=riconciliati,
        sospesi=sospesi,
        ignorati=ignorati,
        ultimi=ultimi,
        rules_count=rules_count,
    )


@bp.route("/upload", methods=["POST"])
@login_required
@write_required
def upload():
    """Upload file CBI, parsing e riconciliazione."""
    file = request.files.get("file")
    if not file or not file.filename:
        flash("Seleziona un file CBI da caricare.", "warning")
        return redirect(url_for("banca.index"))

    try:
        content = file.read()
        transactions = parse_cbi_file(content)

        if not transactions:
            flash("Nessun movimento trovato nel file.", "warning")
            return redirect(url_for("banca.index"))

        batch_id = str(uuid.uuid4())[:8]
        imported = 0
        duplicates = 0

        for tx_data in transactions:
            # Deduplicazione
            existing = BankTransaction.query.filter_by(
                dedup_hash=tx_data["dedup_hash"]
            ).first()
            if existing:
                duplicates += 1
                continue

            bt = BankTransaction(
                operation_date=tx_data["operation_date"],
                value_date=tx_data["value_date"],
                amount=tx_data["amount"],
                direction=tx_data["direction"],
                causale_abi=tx_data["causale_abi"],
                causale_description=tx_data["causale_description"],
                counterpart_name=tx_data["counterpart_name"],
                counterpart_address=tx_data["counterpart_address"],
                ordinante_abi_cab=tx_data.get("ordinante_abi_cab", ""),
                remittance_info=tx_data["remittance_info"],
                reference_code=tx_data["reference_code"],
                raw_data=tx_data["raw_data"],
                dedup_hash=tx_data["dedup_hash"],
                import_batch_id=batch_id,
            )
            db.session.add(bt)
            imported += 1

        db.session.flush()

        # Riconcilia i nuovi movimenti
        new_transactions = BankTransaction.query.filter_by(
            import_batch_id=batch_id,
            status="non_riconciliato",
        ).all()

        stats = reconcile_batch(new_transactions)
        db.session.commit()

        # Notifica Telegram
        try:
            from app.services.telegram_bot import send_telegram_message
            msg = (
                f"<b>Import CBI completato</b>\n"
                f"Movimenti importati: {imported}\n"
                f"Duplicati ignorati: {duplicates}\n"
                f"Riconciliati automaticamente: {stats['matched']}\n"
                f"Sospesi: {stats['pending']}"
            )
            send_telegram_message(msg)
        except Exception:
            pass

        parts = [f"{imported} movimenti importati"]
        if duplicates:
            parts.append(f"{duplicates} duplicati ignorati")
        if stats["matched"]:
            parts.append(f"{stats['matched']} riconciliati")
        if stats["pending"]:
            parts.append(f"{stats['pending']} da riconciliare")

        flash(", ".join(parts) + ".", "success")

    except Exception as e:
        db.session.rollback()
        logger.error(f"Errore import CBI: {e}")
        flash(f"Errore durante l'importazione: {e}", "danger")

    return redirect(url_for("banca.index"))


@bp.route("/movimenti")
@login_required
def movimenti():
    """Lista completa movimenti bancari con filtri."""
    status_filter = request.args.get("status", "")
    direction_filter = request.args.get("direction", "")
    month = request.args.get("month", date.today().strftime("%Y-%m"))

    try:
        year, mo = map(int, month.split("-"))
    except ValueError:
        year, mo = date.today().year, date.today().month

    query = BankTransaction.query.filter(
        db.extract("year", BankTransaction.operation_date) == year,
        db.extract("month", BankTransaction.operation_date) == mo,
    )

    if status_filter:
        query = query.filter(BankTransaction.status == status_filter)
    if direction_filter:
        query = query.filter(BankTransaction.direction == direction_filter)

    movimenti_list = query.order_by(BankTransaction.operation_date.desc()).all()

    return render_template(
        "banca/movimenti.html",
        movimenti=movimenti_list,
        month=month,
        status_filter=status_filter,
        direction_filter=direction_filter,
    )


@bp.route("/sospesi")
@login_required
def sospesi():
    """Movimenti da riconciliare con proposte di abbinamento."""
    pending = BankTransaction.query.filter_by(
        status="non_riconciliato"
    ).order_by(BankTransaction.operation_date.desc()).all()

    # Genera proposte per ogni movimento
    items = []
    for bt in pending:
        proposals = get_match_proposals(bt)
        items.append({"bt": bt, "proposals": proposals})

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    revenue_streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()

    return render_template(
        "banca/sospesi.html",
        items=items,
        categories=categories,
        contacts=contacts,
        revenue_streams=revenue_streams,
    )


@bp.route("/riconcilia/<int:id>", methods=["POST"])
@login_required
@write_required
def riconcilia(id):
    """Conferma abbinamento di un movimento a una transazione."""
    bt = BankTransaction.query.get_or_404(id)
    tx_id = request.form.get("transaction_id", type=int)

    if not tx_id:
        flash("Seleziona una transazione da abbinare.", "warning")
        return redirect(url_for("banca.sospesi"))

    tx = Transaction.query.get_or_404(tx_id)

    bt.status = "riconciliato"
    bt.matched_transaction_id = tx.id
    bt.matched_by = "manuale"

    # Aggiorna stato pagamento se fattura SDI
    if tx.source == "sdi" and tx.payment_status in ("da_pagare", "parziale"):
        tx.payment_status = "pagato"
        tx.payment_date = bt.operation_date

    db.session.commit()
    flash(f"Movimento riconciliato con '{tx.description[:50]}'.", "success")
    return redirect(url_for("banca.sospesi"))


@bp.route("/ignora/<int:id>", methods=["POST"])
@login_required
@write_required
def ignora(id):
    """Ignora un movimento bancario."""
    bt = BankTransaction.query.get_or_404(id)
    bt.status = "ignorato"
    db.session.commit()
    flash("Movimento ignorato.", "info")
    return redirect(url_for("banca.sospesi"))


@bp.route("/crea-movimento/<int:id>", methods=["POST"])
@login_required
@write_required
def crea_movimento(id):
    """Crea una transazione in prima nota da un movimento bancario."""
    bt = BankTransaction.query.get_or_404(id)

    category_id = request.form.get("category_id", type=int) or None
    contact_id = request.form.get("contact_id", type=int) or None
    revenue_stream_id = request.form.get("revenue_stream_id", type=int) or None
    description = request.form.get("description", "").strip() or None

    tx = create_transaction_from_bank_manual(
        bt,
        category_id=category_id,
        contact_id=contact_id,
        revenue_stream_id=revenue_stream_id,
        description=description,
    )
    db.session.commit()

    flash(f"Transazione creata e movimento riconciliato.", "success")
    return redirect(url_for("banca.sospesi"))


# === REGOLE ===

@bp.route("/regole")
@login_required
def regole():
    """Lista regole automatiche."""
    rules = AutoRule.query.order_by(AutoRule.priority.desc(), AutoRule.name).all()
    return render_template("banca/regole.html", rules=rules, mode="list")


@bp.route("/regole/nuova", methods=["GET", "POST"])
@login_required
@write_required
def regola_nuova():
    """Crea una nuova regola."""
    if request.method == "POST":
        rule = AutoRule(
            name=request.form.get("name", "").strip(),
            active=True,
            priority=request.form.get("priority", 0, type=int),
            applies_to=request.form.get("applies_to", "tutti"),
            match_description=request.form.get("match_description", "").strip() or None,
            match_counterpart=request.form.get("match_counterpart", "").strip() or None,
            match_partita_iva=request.form.get("match_partita_iva", "").strip() or None,
            match_causale_abi=request.form.get("match_causale_abi", "").strip() or None,
            match_amount_min=request.form.get("match_amount_min", type=float) or None,
            match_amount_max=request.form.get("match_amount_max", type=float) or None,
            match_direction=request.form.get("match_direction", "").strip() or None,
            action_category_id=request.form.get("action_category_id", type=int) or None,
            action_contact_id=request.form.get("action_contact_id", type=int) or None,
            action_revenue_stream_id=request.form.get("action_revenue_stream_id", type=int) or None,
            action_description=request.form.get("action_description", "").strip() or None,
            action_auto_create="action_auto_create" in request.form,
        )

        if not rule.name:
            flash("Il nome della regola e' obbligatorio.", "warning")
        else:
            db.session.add(rule)
            db.session.commit()
            flash(f"Regola '{rule.name}' creata.", "success")
            return redirect(url_for("banca.regole"))

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    revenue_streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()

    return render_template(
        "banca/regole.html",
        mode="new",
        rule=None,
        categories=categories,
        contacts=contacts,
        revenue_streams=revenue_streams,
    )


@bp.route("/regole/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def regola_modifica(id):
    """Modifica una regola esistente."""
    rule = AutoRule.query.get_or_404(id)

    if request.method == "POST":
        rule.name = request.form.get("name", "").strip()
        rule.priority = request.form.get("priority", 0, type=int)
        rule.applies_to = request.form.get("applies_to", "tutti")
        rule.match_description = request.form.get("match_description", "").strip() or None
        rule.match_counterpart = request.form.get("match_counterpart", "").strip() or None
        rule.match_partita_iva = request.form.get("match_partita_iva", "").strip() or None
        rule.match_causale_abi = request.form.get("match_causale_abi", "").strip() or None
        rule.match_amount_min = request.form.get("match_amount_min", type=float) or None
        rule.match_amount_max = request.form.get("match_amount_max", type=float) or None
        rule.match_direction = request.form.get("match_direction", "").strip() or None
        rule.action_category_id = request.form.get("action_category_id", type=int) or None
        rule.action_contact_id = request.form.get("action_contact_id", type=int) or None
        rule.action_revenue_stream_id = request.form.get("action_revenue_stream_id", type=int) or None
        rule.action_description = request.form.get("action_description", "").strip() or None
        rule.action_auto_create = "action_auto_create" in request.form

        if not rule.name:
            flash("Il nome della regola e' obbligatorio.", "warning")
        else:
            db.session.commit()
            flash(f"Regola '{rule.name}' aggiornata.", "success")
            return redirect(url_for("banca.regole"))

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    revenue_streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()

    return render_template(
        "banca/regole.html",
        mode="edit",
        rule=rule,
        categories=categories,
        contacts=contacts,
        revenue_streams=revenue_streams,
    )


@bp.route("/regole/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def regola_elimina(id):
    """Elimina una regola."""
    rule = AutoRule.query.get_or_404(id)
    name = rule.name
    db.session.delete(rule)
    db.session.commit()
    flash(f"Regola '{name}' eliminata.", "success")
    return redirect(url_for("banca.regole"))


@bp.route("/regole/<int:id>/toggle", methods=["POST"])
@login_required
@write_required
def regola_toggle(id):
    """Attiva/disattiva una regola."""
    rule = AutoRule.query.get_or_404(id)
    rule.active = not rule.active
    db.session.commit()
    stato = "attivata" if rule.active else "disattivata"
    flash(f"Regola '{rule.name}' {stato}.", "info")
    return redirect(url_for("banca.regole"))
