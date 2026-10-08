"""Fatture emesse: copie PDF dalla Coldiretti lette con OCR (vedi services/fatture_emesse.py)."""

from datetime import date, datetime

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app import db
from app.models import BankTransaction, FatturaEmessa
from app.services import fatture_emesse as servizio
from app.services.fatture_emesse_ocr import sezionale as leggi_sezionale
from app.utils.decorators import section_required, write_required

bp = Blueprint("fatture_emesse", __name__, url_prefix="/fatture-emesse")
bp.before_request(section_required("finanza"))

STATI = {
    "incassata": "Incassata (bonifico)",
    "altro": "Incassata in altro modo",
    "da_abbinare": "Da abbinare",
    "nota_credito": "Nota di credito",
    "stornata": "Stornata",
    "interna": "Autoconsumo",
}


def stato(f):
    if f.tipo == "nota_credito":
        return "nota_credito"
    if f.stornata:
        return "stornata"
    if f.interna:
        return "interna"
    if f.transaction_id:
        return "incassata"
    if f.incasso == "altro":
        return "altro"
    return "da_abbinare"


@bp.route("/")
@login_required
def index():
    anni = [r[0] for r in db.session.query(FatturaEmessa.anno).distinct()
            .order_by(FatturaEmessa.anno.desc()).all() if r[0]]
    anno = request.args.get("anno", type=int)
    if anno is None and "anno" not in request.args:
        anno = anni[0] if anni else date.today().year
    sez = request.args.get("sez")
    filtro_stato = request.args.get("stato", "")
    q = request.args.get("q", "").strip()
    verificare = request.args.get("verificare") == "1"

    query = FatturaEmessa.query
    if anno:
        query = query.filter(FatturaEmessa.anno == anno)
    if sez is not None and sez != "tutti":
        query = query.filter(FatturaEmessa.sezionale == sez)
    if q:
        query = query.filter(db.or_(FatturaEmessa.cliente.ilike(f"%{q}%"),
                                    FatturaEmessa.numero.ilike(f"%{q}%"),
                                    FatturaEmessa.descrizione.ilike(f"%{q}%")))
    if verificare:
        query = query.filter(FatturaEmessa.da_verificare.is_(True))
    tutte = query.order_by(FatturaEmessa.data.desc(), FatturaEmessa.sezionale,
                           FatturaEmessa.progressivo.desc()).all()

    stati = {f.id: stato(f) for f in tutte}
    righe = [f for f in tutte if not filtro_stato or stati[f.id] == filtro_stato]

    # Riepilogo (sulle fatture filtrate per anno/sezionale/ricerca, senza filtro stato)
    vendite = [f for f in tutte if stati[f.id] in ("incassata", "altro", "da_abbinare")]
    riepilogo = {
        "fatturato": sum(f.totale for f in vendite),
        "n_fatture": len(vendite),
        "incassato": sum(f.totale for f in vendite if stati[f.id] == "incassata"),
        "n_incassate": sum(1 for f in vendite if stati[f.id] == "incassata"),
        "altro": sum(f.totale for f in vendite if stati[f.id] == "altro"),
        "da_abbinare": sum(f.totale for f in vendite if stati[f.id] == "da_abbinare"),
        "n_da_abbinare": sum(1 for f in vendite if stati[f.id] == "da_abbinare"),
        "n_verificare": sum(1 for f in tutte if f.da_verificare),
    }
    mancanti = [(a, s, nums) for (a, s), nums in servizio.numeri_mancanti().items()
                if not anno or a == anno]
    sezionali = [r[0] for r in db.session.query(FatturaEmessa.sezionale).distinct()
                 .order_by(FatturaEmessa.sezionale).all()]
    return render_template("fatture_emesse/index.html", fatture=righe, stati=stati, STATI=STATI,
                           riepilogo=riepilogo, mancanti=mancanti, anni=anni, anno=anno,
                           sezionali=sezionali, sez=sez, filtro_stato=filtro_stato, q=q,
                           verificare=verificare,
                           configurato=bool(current_app.config.get("FATTURE_EMESSE_MITTENTE")))


@bp.route("/<int:id>")
@login_required
def detail(id):
    f = FatturaEmessa.query.get_or_404(id)
    cand = servizio.candidati(f) if servizio.da_abbinare(f) else []
    stornata_fattura = FatturaEmessa.query.filter_by(stornata_da_id=f.id).first() \
        if f.tipo == "nota_credito" else None
    return render_template("fatture_emesse/detail.html", f=f, stato=stato(f), STATI=STATI,
                           candidati=cand, stornata_fattura=stornata_fattura)


@bp.route("/controlla-email", methods=["POST"])
@login_required
@write_required
def controlla_email():
    try:
        s = servizio.controlla_email(current_app._get_current_object())
    except Exception as e:
        current_app.logger.exception("Fatture emesse: controllo email fallito")
        flash(f"Controllo email non riuscito: {e}", "danger")
        return redirect(url_for("fatture_emesse.index"))
    if s["fatture"]:
        flash(f"{s['fatture']} nuove fatture emesse importate"
              + (f", {s['da_verificare']} da controllare" if s["da_verificare"] else "") + ".", "success")
    if s["abbinate"]:
        flash(f"{s['abbinate']} fatture abbinate ai bonifici.", "success")
    if s["errori"]:
        flash(f"{s['errori']} email non lette per errore (vedi log).", "warning")
    if not s["fatture"] and not s["abbinate"] and not s["errori"]:
        flash("Nessuna nuova fattura emessa nelle email.", "info")
    return redirect(url_for("fatture_emesse.index"))


@bp.route("/<int:id>/collega/<int:bt_id>", methods=["POST"])
@login_required
@write_required
def collega(id, bt_id):
    f = FatturaEmessa.query.get_or_404(id)
    bt = BankTransaction.query.get_or_404(bt_id)
    if not servizio.da_abbinare(f):
        flash("Questa fattura non è da abbinare.", "warning")
    elif bt.id not in {c["bt"].id for c in servizio.candidati(f)}:
        flash("Questo bonifico non è abbinabile alla fattura.", "warning")
    else:
        servizio.collega(f, bt, "manuale")
        db.session.commit()
        flash(f"Fattura {f.numero} collegata al bonifico del {bt.operation_date.strftime('%d/%m/%Y')}.", "success")
    return redirect(url_for("fatture_emesse.detail", id=id))


@bp.route("/<int:id>/scollega", methods=["POST"])
@login_required
@write_required
def scollega(id):
    f = FatturaEmessa.query.get_or_404(id)
    servizio.scollega(f)
    if f.incasso == "altro":
        f.incasso = ""
    db.session.commit()
    flash(f"Fattura {f.numero} scollegata.", "info")
    return redirect(url_for("fatture_emesse.detail", id=id))


@bp.route("/<int:id>/incasso-altro", methods=["POST"])
@login_required
@write_required
def incasso_altro(id):
    """Incassata in contanti o con POS (già in cassa): nessuna entrata da creare."""
    f = FatturaEmessa.query.get_or_404(id)
    if f.transaction_id:
        flash("La fattura è già collegata a un incasso.", "warning")
    else:
        f.incasso = "altro"
        db.session.commit()
        flash(f"Fattura {f.numero} segnata come incassata in altro modo.", "success")
    return redirect(url_for("fatture_emesse.detail", id=id))


@bp.route("/<int:id>/modifica", methods=["POST"])
@login_required
@write_required
def modifica(id):
    """Correzione dei dati letti male dall'OCR."""
    f = FatturaEmessa.query.get_or_404(id)

    def importo(nome):
        v = request.form.get(nome, "").strip().replace(",", ".")
        return round(float(v), 2) if v else None

    try:
        numero = request.form.get("numero", "").strip()
        data = datetime.strptime(request.form.get("data", ""), "%Y-%m-%d").date()
        totale = importo("totale")
        if not numero or totale is None:
            raise ValueError("numero e totale sono obbligatori")
        altra = FatturaEmessa.query.filter(FatturaEmessa.numero == numero, FatturaEmessa.data == data,
                                           FatturaEmessa.id != f.id).first()
        if altra:
            raise ValueError(f"esiste già la fattura {numero} del {data.strftime('%d/%m/%Y')}")
        f.numero, f.data, f.anno = numero, data, data.year
        f.sezionale, f.progressivo = leggi_sezionale(numero)
        f.cliente = request.form.get("cliente", "").strip()
        f.totale = totale
        f.imponibile = importo("imponibile")
        f.iva = importo("iva")
        f.note = request.form.get("note", "").strip() or None
        f.da_verificare = request.form.get("da_verificare") == "1"
        db.session.commit()
        flash("Dati della fattura aggiornati.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(f"Dati non validi: {e}", "danger")
    return redirect(url_for("fatture_emesse.detail", id=id))
