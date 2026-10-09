"""Controllo di fine mese: tutto quello che manca perché banca, fatture e conti siano in ordine."""

import collections
from datetime import date, timedelta

from flask import Blueprint, current_app, flash, redirect, render_template, url_for
from flask_login import login_required

from app import db
from app.models import BankTransaction, FatturaEmessa, SdiInvoice, Transaction
from app.utils.decorators import section_required, write_required

bp = Blueprint("controllo", __name__, url_prefix="/controllo")
bp.before_request(section_required("finanza"))

GIORNI_ESTRATTO_VECCHIO = 35


def _netto(bts):
    return sum(b.amount if b.direction == "C" else -b.amount for b in bts)


def stato() -> dict:
    """Tutti i numeri del controllo (usati anche dal cruscotto)."""
    from app.services.saldo_banca import verifica_saldo
    from app.services.fatture_emesse import da_abbinare, numeri_mancanti
    from app.services.spese_carta import e_amazon, arretrati_senza_domanda
    oggi = date.today()

    # 1. Banca
    sospesi = BankTransaction.query.filter_by(status="non_riconciliato").all()
    quadratura = verifica_saldo()
    ultimo_import = db.session.query(db.func.max(BankTransaction.created_at)).scalar()
    estratto_vecchio = bool(quadratura and (oggi - quadratura["saldo_banca_data"]).days > GIORNI_ESTRATTO_VECCHIO)
    amazon = [b for b in sospesi if e_amazon(b)]

    # 2. Fatture ricevute non collegate a un pagamento in banca
    from app.services.reconciliation import transazioni_collegate
    collegate = transazioni_collegate()
    aperte = Transaction.query.join(SdiInvoice, SdiInvoice.id == Transaction.invoice_id).filter(
        Transaction.source == "sdi", Transaction.type == "uscita", Transaction.amount > 0,
        SdiInvoice.direction == "ricevuta",
        ~Transaction.id.in_(collegate),
        db.or_(Transaction.payment_method.is_(None), Transaction.payment_method.notin_(["contanti", "non_applicabile"])),
    ).all()
    def scaduta(t):
        return (t.due_date or (t.date + timedelta(days=60))) < oggi
    # prima dell'inizio dell'estratto conto i pagamenti passavano dal vecchio conto: non si abbinano
    inizio = quadratura["apertura_data"] if quadratura else date(2000, 1, 1)
    sdi_pagate = [t for t in aperte if t.payment_status == "pagato" and t.date >= inizio]
    sdi_scadute = [t for t in aperte if t.payment_status != "pagato" and scaduta(t)]
    sdi_da_pagare = [t for t in aperte if t.payment_status != "pagato" and not scaduta(t)]

    # 3. Fatture emesse senza incasso
    fe_tutte = [f for f in FatturaEmessa.query.all() if da_abbinare(f)]
    fe_aperte = [f for f in fe_tutte if f.data >= inizio]
    fe_vecchie = len(fe_tutte) - len(fe_aperte)
    mancanti = [(a, s, n) for (a, s), nums in numeri_mancanti().items() for n in nums]

    # Mese per mese (ultimi 12 mesi)
    mesi = []
    m = date(oggi.year, oggi.month, 1)
    for _ in range(12):
        mesi.append(m.strftime("%Y-%m"))
        m = (m - timedelta(days=1)).replace(day=1)
    per_mese = {k: collections.Counter() for k in mesi}
    for b in sospesi:
        k = b.operation_date.strftime("%Y-%m")
        if k in per_mese:
            per_mese[k]["banca"] += 1
    for t in sdi_pagate + sdi_scadute:
        k = t.date.strftime("%Y-%m")
        if k in per_mese:
            per_mese[k]["ricevute"] += 1
    for f in fe_aperte:
        k = f.data.strftime("%Y-%m")
        if k in per_mese:
            per_mese[k]["emesse"] += 1

    da_fare = len(sospesi) + len(sdi_pagate) + len(sdi_scadute) + len(fe_aperte) + \
        (0 if not quadratura or quadratura["quadra"] else 1)
    return dict(
        oggi=oggi, sospesi=sospesi, sospesi_netto=_netto(sospesi),
        quadratura=quadratura, ultimo_import=ultimo_import, estratto_vecchio=estratto_vecchio,
        amazon=amazon, sdi_pagate=sdi_pagate, sdi_scadute=sdi_scadute, sdi_da_pagare=sdi_da_pagare,
        fe_aperte=fe_aperte, fe_vecchie=fe_vecchie, inizio=inizio, mancanti=mancanti, mesi=mesi, per_mese=per_mese, da_fare=da_fare,
        amazon_senza_domanda=arretrati_senza_domanda())


@bp.route("/")
@login_required
def index():
    return render_template("controllo/index.html", **stato())


@bp.route("/amazon-sul-bot", methods=["POST"])
@login_required
@write_required
def amazon_sul_bot():
    """Manda sul bot Telegram le prossime 10 spese Amazon arretrate da descrivere."""
    from app.services.spese_carta import chiedi_spese
    n = chiedi_spese(current_app._get_current_object(), arretrati=10)
    flash(f"{n} spese Amazon mandate sul gruppo Telegram della finanza." if n else
          "Nessuna spesa mandata (bot non configurato o niente da chiedere).", "success" if n else "info")
    return redirect(url_for("controllo.index"))
