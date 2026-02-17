"""Routes per la riconciliazione bancaria."""

import uuid
import logging
from datetime import date
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from sqlalchemy import func
from app import db
from app.models import (
    BankTransaction, BankBalance, AutoRule, Transaction, Category, Contact, RevenueStream,
    IgnoreReason,
)
from app.services.cbi_parser import parse_cbi_file
from app.services.reconciliation import (
    reconcile_batch, get_match_proposals, create_transaction_from_bank_manual,
    get_available_transactions, create_transaction_from_rule,
)
from app.services.rules_engine import apply_specific_rules
from app.utils.decorators import write_required

logger = logging.getLogger(__name__)

bp = Blueprint("banca", __name__, url_prefix="/banca")


@bp.route("/")
@login_required
def index():
    """Dashboard banca: statistiche, upload, ultimi movimenti, saldi."""
    total = BankTransaction.query.count()
    riconciliati = BankTransaction.query.filter_by(status="riconciliato").count()
    sospesi = BankTransaction.query.filter_by(status="non_riconciliato").count()
    ignorati = BankTransaction.query.filter_by(status="ignorato").count()

    ultimi = BankTransaction.query.order_by(
        BankTransaction.operation_date.desc()
    ).limit(20).all()

    rules_count = AutoRule.query.filter_by(active=True).count()

    # Saldo banca: ultimo saldo chiusura da CBI (saldo reale estratto conto)
    ultimo_saldo = BankBalance.query.filter_by(
        balance_type="chiusura"
    ).order_by(BankBalance.date.desc()).first()

    saldo_banca = ultimo_saldo.balance if ultimo_saldo else None
    saldo_banca_data = ultimo_saldo.date if ultimo_saldo else None

    # Saldo contabile: primo saldo apertura + tutti i movimenti bancari processati
    # (riconciliati + ignorati). Se tutto e' riconciliato correttamente,
    # saldo_contabile == saldo_banca. La differenza aiuta a trovare errori.
    primo_saldo = BankBalance.query.filter_by(
        balance_type="apertura"
    ).order_by(BankBalance.date.asc()).first()

    saldo_contabile = None
    if primo_saldo:
        # Movimenti processati (riconciliati o ignorati) dal primo saldo in poi
        crediti = db.session.query(
            func.coalesce(func.sum(BankTransaction.amount), 0)
        ).filter(
            BankTransaction.operation_date >= primo_saldo.date,
            BankTransaction.direction == "C",
            BankTransaction.status.in_(["riconciliato", "ignorato"]),
        ).scalar()
        debiti = db.session.query(
            func.coalesce(func.sum(BankTransaction.amount), 0)
        ).filter(
            BankTransaction.operation_date >= primo_saldo.date,
            BankTransaction.direction == "D",
            BankTransaction.status.in_(["riconciliato", "ignorato"]),
        ).scalar()
        saldo_contabile = primo_saldo.balance + float(crediti) - float(debiti)

    # Storico saldi CBI (solo chiusura, piu' leggibile)
    storico_saldi = BankBalance.query.filter_by(
        balance_type="chiusura"
    ).order_by(BankBalance.date.desc()).limit(30).all()

    return render_template(
        "banca/index.html",
        total=total,
        riconciliati=riconciliati,
        sospesi=sospesi,
        ignorati=ignorati,
        ultimi=ultimi,
        rules_count=rules_count,
        saldo_banca=saldo_banca,
        saldo_banca_data=saldo_banca_data,
        saldo_contabile=saldo_contabile,
        storico_saldi=storico_saldi,
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
        result = parse_cbi_file(content)
        transactions = result["transactions"]
        cbi_balances = result["balances"]

        if not transactions and not cbi_balances:
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
                description=tx_data.get("description", ""),
                reference_code=tx_data["reference_code"],
                raw_data=tx_data["raw_data"],
                dedup_hash=tx_data["dedup_hash"],
                import_batch_id=batch_id,
            )
            db.session.add(bt)
            imported += 1

        # Salva saldi estratti da record 61/64
        balances_saved = 0
        for bal in cbi_balances:
            existing = BankBalance.query.filter_by(
                date=bal["date"], balance_type=bal["type"], source="cbi"
            ).first()
            if not existing:
                db.session.add(BankBalance(
                    date=bal["date"],
                    balance=bal["balance"],
                    balance_type=bal["type"],
                    source="cbi",
                ))
                balances_saved += 1

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
    """Lista completa movimenti bancari con filtri estesi."""
    status_filter = request.args.get("status", "")
    direction_filter = request.args.get("direction", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    search = request.args.get("q", "").strip()
    amount_min = request.args.get("amount_min", "", type=str)
    amount_max = request.args.get("amount_max", "", type=str)
    causale_filter = request.args.get("causale", "")

    query = BankTransaction.query

    # Filtro date (default: mese corrente)
    if date_from:
        try:
            df = date.fromisoformat(date_from)
            query = query.filter(BankTransaction.operation_date >= df)
        except ValueError:
            pass
    else:
        # Default: primo giorno del mese corrente
        df = date.today().replace(day=1)
        date_from = df.isoformat()
        query = query.filter(BankTransaction.operation_date >= df)

    if date_to:
        try:
            dt = date.fromisoformat(date_to)
            query = query.filter(BankTransaction.operation_date <= dt)
        except ValueError:
            pass

    if status_filter:
        query = query.filter(BankTransaction.status == status_filter)
    if direction_filter:
        query = query.filter(BankTransaction.direction == direction_filter)

    # Ricerca testo
    if search:
        like_q = f"%{search}%"
        query = query.filter(db.or_(
            BankTransaction.counterpart_name.ilike(like_q),
            BankTransaction.remittance_info.ilike(like_q),
            BankTransaction.causale_description.ilike(like_q),
            BankTransaction.description.ilike(like_q),
        ))

    # Range importo
    if amount_min:
        try:
            query = query.filter(BankTransaction.amount >= float(amount_min))
        except ValueError:
            pass
    if amount_max:
        try:
            query = query.filter(BankTransaction.amount <= float(amount_max))
        except ValueError:
            pass

    # Causale ABI
    if causale_filter:
        query = query.filter(BankTransaction.causale_abi == causale_filter)

    movimenti_list = query.order_by(BankTransaction.operation_date.desc()).all()

    # Valori distinti causale ABI per il filtro
    causali_abi = db.session.query(
        BankTransaction.causale_abi, BankTransaction.causale_description
    ).filter(
        BankTransaction.causale_abi.isnot(None),
        BankTransaction.causale_abi != "",
    ).distinct().order_by(BankTransaction.causale_abi).all()

    return render_template(
        "banca/movimenti.html",
        movimenti=movimenti_list,
        date_from=date_from,
        date_to=date_to,
        status_filter=status_filter,
        direction_filter=direction_filter,
        search=search,
        amount_min=amount_min,
        amount_max=amount_max,
        causale_filter=causale_filter,
        causali_abi=causali_abi,
    )


@bp.route("/sospesi")
@login_required
def sospesi():
    """Movimenti da riconciliare con proposte di abbinamento."""
    pending = BankTransaction.query.filter_by(
        status="non_riconciliato"
    ).order_by(BankTransaction.operation_date.desc()).all()

    # Genera proposte e transazioni disponibili per ogni movimento
    items = []
    for bt in pending:
        proposals = get_match_proposals(bt)
        available = get_available_transactions(bt)
        items.append({"bt": bt, "proposals": proposals, "available": available})

    categories = Category.query.filter_by(active=True).order_by(Category.name).all()
    contacts = Contact.query.filter_by(active=True).order_by(Contact.name).all()
    revenue_streams = RevenueStream.query.filter_by(active=True).order_by(RevenueStream.name).all()
    reasons = IgnoreReason.query.order_by(IgnoreReason.name).all()

    return render_template(
        "banca/sospesi.html",
        items=items,
        categories=categories,
        contacts=contacts,
        revenue_streams=revenue_streams,
        reasons=reasons,
    )


@bp.route("/cerca-transazioni/<int:bt_id>")
@login_required
def cerca_transazioni(bt_id):
    """API: cerca transazioni disponibili per abbinamento manuale (AJAX)."""
    from flask import jsonify
    bt = BankTransaction.query.get_or_404(bt_id)

    search = request.args.get("q", "").strip()
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    source_filter = request.args.get("source", "")  # sdi, altre, or empty=all
    include_paid = request.args.get("include_paid", "0") == "1"

    tx_type = "entrata" if bt.direction == "C" else "uscita"

    # Transazioni gia' abbinate ad altri movimenti
    already_matched = db.select(BankTransaction.matched_transaction_id).where(
        BankTransaction.matched_transaction_id.isnot(None),
        BankTransaction.id != bt.id,
    ).scalar_subquery()

    query = Transaction.query.filter(
        Transaction.type == tx_type,
        ~Transaction.id.in_(already_matched),
    )

    # Filtro date (nessun limite di default - cerca tutto)
    if date_from:
        try:
            query = query.filter(Transaction.date >= date.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(Transaction.date <= date.fromisoformat(date_to))
        except ValueError:
            pass

    # Filtro fonte
    if source_filter == "sdi":
        query = query.filter(Transaction.source == "sdi")
        if not include_paid:
            query = query.filter(Transaction.payment_status.in_(["da_pagare", "parziale"]))
    elif source_filter == "altre":
        query = query.filter(Transaction.source.in_(["manuale", "banca"]))
        if not include_paid:
            query = query.filter(Transaction.payment_status != "pagato")

    # Escludi pagate (per default, se non filtro per fonte)
    if not source_filter and not include_paid:
        query = query.filter(Transaction.payment_status != "pagato")

    # Ricerca testo
    if search:
        like_q = f"%{search}%"
        from app.models import Contact as C
        query = query.outerjoin(C, Transaction.contact_id == C.id).filter(db.or_(
            Transaction.description.ilike(like_q),
            C.name.ilike(like_q),
        ))

    results = query.order_by(Transaction.date.desc()).limit(50).all()

    items = []
    for tx in results:
        items.append({
            "id": tx.id,
            "description": (tx.description or "-")[:55],
            "date": tx.date.strftime("%d/%m/%Y"),
            "amount": f"{tx.amount:,.2f}",
            "contact": tx.contact.name[:25] if tx.contact else "",
            "source": tx.source.upper(),
            "status": tx.payment_status or "",
        })

    return jsonify(items)


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
    """Ignora un movimento bancario con motivo."""
    bt = BankTransaction.query.get_or_404(id)
    bt.status = "ignorato"
    bt.ignore_reason_id = request.form.get("ignore_reason_id", type=int) or None
    db.session.commit()
    label = bt.ignore_reason.name if bt.ignore_reason else "Senza motivo"
    flash(f"Movimento ignorato ({label}).", "info")
    return redirect(url_for("banca.sospesi"))


@bp.route("/ignorati")
@login_required
def ignorati():
    """Lista movimenti ignorati, divisi per entrata/uscita."""
    ignorati_list = BankTransaction.query.filter_by(
        status="ignorato"
    ).order_by(BankTransaction.operation_date.desc()).all()

    entrate = [bt for bt in ignorati_list if bt.direction == "C"]
    uscite = [bt for bt in ignorati_list if bt.direction == "D"]

    totale_entrate = sum(bt.amount for bt in entrate)
    totale_uscite = sum(bt.amount for bt in uscite)

    # Conteggi per motivo
    reason_counts = {}
    for bt in ignorati_list:
        name = bt.ignore_reason.name if bt.ignore_reason else "Senza motivo"
        reason_counts[name] = reason_counts.get(name, 0) + 1

    reasons = IgnoreReason.query.order_by(IgnoreReason.name).all()

    return render_template(
        "banca/ignorati.html",
        entrate=entrate,
        uscite=uscite,
        totale_entrate=totale_entrate,
        totale_uscite=totale_uscite,
        reason_counts=reason_counts,
        reasons=reasons,
    )


@bp.route("/ripristina/<int:id>", methods=["POST"])
@login_required
@write_required
def ripristina(id):
    """Ripristina un movimento ignorato a sospeso."""
    bt = BankTransaction.query.get_or_404(id)
    bt.status = "non_riconciliato"
    bt.ignore_reason_id = None
    db.session.commit()
    flash("Movimento ripristinato tra i sospesi.", "info")
    return redirect(url_for("banca.ignorati"))


@bp.route("/motivi-ignora/nuovo", methods=["POST"])
@login_required
@write_required
def nuovo_motivo_ignora():
    """Crea un nuovo motivo di ignorazione."""
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#6c757d")
    if name:
        existing = IgnoreReason.query.filter_by(name=name).first()
        if existing:
            flash("Questo motivo esiste gia'.", "warning")
        else:
            db.session.add(IgnoreReason(name=name, color=color))
            db.session.commit()
            flash(f"Motivo '{name}' creato.", "success")
    return redirect(url_for("banca.ignorati"))


@bp.route("/motivi-ignora/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def elimina_motivo_ignora(id):
    """Elimina un motivo di ignorazione."""
    reason = IgnoreReason.query.get_or_404(id)
    # Rimuovi il motivo dai movimenti che lo usano
    BankTransaction.query.filter_by(ignore_reason_id=id).update({"ignore_reason_id": None})
    name = reason.name
    db.session.delete(reason)
    db.session.commit()
    flash(f"Motivo '{name}' eliminato.", "success")
    return redirect(url_for("banca.ignorati"))


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
            action_payment_method=request.form.get("action_payment_method", "").strip() or None,
            action_iva_rate=request.form.get("action_iva_rate", type=float),
            action_notes=request.form.get("action_notes", "").strip() or None,
            action_date_offset=request.form.get("action_date_offset", type=int) or None,
            action_date_end_prev_month="action_date_end_prev_month" in request.form,
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
        rule.action_payment_method = request.form.get("action_payment_method", "").strip() or None
        rule.action_iva_rate = request.form.get("action_iva_rate", type=float)
        rule.action_notes = request.form.get("action_notes", "").strip() or None
        rule.action_date_offset = request.form.get("action_date_offset", type=int) or None
        rule.action_date_end_prev_month = "action_date_end_prev_month" in request.form

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


@bp.route("/regole/riapplica", methods=["POST"])
@login_required
@write_required
def regole_riapplica():
    """Riapplica regole selezionate su transazioni bancarie esistenti."""
    rule_ids = request.form.getlist("rule_ids[]", type=int)
    if not rule_ids:
        rule_ids = request.form.getlist("rule_ids", type=int)
    scope = request.form.get("scope", "non_riconciliati")

    if not rule_ids:
        flash("Seleziona almeno una regola da riapplicare.", "warning")
        return redirect(url_for("banca.regole"))

    # Filtra transazioni bancarie in base allo scope
    if scope == "tutti":
        bank_txs = BankTransaction.query.all()
    else:
        bank_txs = BankTransaction.query.filter_by(status="non_riconciliato").all()

    created = 0
    updated = 0

    for bt in bank_txs:
        # Salta se gia' riconciliata con transazione collegata
        if bt.status == "riconciliato" and bt.matched_transaction_id:
            continue

        rule_data = {
            "description": bt.causale_description or "",
            "counterpart": bt.counterpart_name or "",
            "causale_abi": bt.causale_abi or "",
            "amount": bt.amount,
            "direction": bt.direction,
            "remittance_info": bt.remittance_info or "",
        }

        actions = apply_specific_rules(rule_data, "banca", rule_ids)
        if not actions:
            continue

        if actions.get("auto_create") and bt.status != "riconciliato":
            create_transaction_from_rule(bt, actions)
            created += 1
        else:
            # Aggiorna matched_rule_id per tracciamento
            bt.matched_rule_id = actions.get("rule_id")
            updated += 1

    db.session.commit()

    parts = []
    if created:
        parts.append(f"{created} movimenti creati")
    if updated:
        parts.append(f"{updated} transazioni aggiornate")
    if not parts:
        parts.append("nessuna transazione corrispondente")

    flash(f"Regole riapplicate: {', '.join(parts)}.", "success")
    return redirect(url_for("banca.regole"))
