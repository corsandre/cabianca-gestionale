"""
Soccida: pagine della sezione Allevamento.
La scheda la vedono gli amministratori e gli utenti con la sezione «soccida» (sola lettura: possono provare
gli scenari ma non salvarli); impostazioni e ogni modifica restano agli amministratori.

    /allevamento/soccida                la scheda: esito, probabilità, leve, dati da aggiornare, conto
    /allevamento/soccida/impostazioni   contratto, dati del ciclo, scenario standard, tabella, anticipi

Le rotte stanno sul blueprint dell'allevamento (stesso menu, stesso tema) ma in un file a parte.
Qui c'è solo il passaggio tra pagina e servizi:
    app/services/soccida.py          il calcolo (nessun database)
    app/services/soccida_dati.py     la raccolta dei dati dal gestionale
    app/services/soccida_scheda.py   la preparazione di quello che la scheda mostra
"""
import re
from datetime import date, timedelta

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import BankTransaction, SdiInvoice, SoccidaAnticipo, SoccidaFattura, SoccidaTabella
from app.routes.allevamento import _check_allevamento, _get_ciclo_attivo, _ciclo_scelto, bp
from app.services import soccida as S
from app.services import soccida_dati as D
from app.services import soccida_scheda as V


def _solo_admin():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)


def _puo_vedere():
    """La scheda in sola lettura: amministratori e utenti a cui è stata data la sezione «soccida»."""
    _check_allevamento()
    if not current_user.has_section("soccida"):
        abort(403)


def _ciclo():
    """Il ciclo scelto in alto (3.5.0), anche chiuso: liquidazione, giacenza finale e premi si inseriscono dopo
    la chiusura. Un ciclo in avvio non ha ancora la Soccida (le servono data di fine e giacenza finale del
    ciclo precedente): si resta sul ciclo attivo."""
    ciclo = _ciclo_scelto()
    if ciclo and ciclo.in_avvio:
        if request.method == "GET":
            flash(f"La Soccida di «{ciclo.nome}» si apre dopo la chiusura del ciclo attivo: qui vedi quella del ciclo attivo.", "info")
        return _get_ciclo_attivo()
    return ciclo


def _oggi(ciclo):
    """Per un ciclo chiuso la scheda si ferma alla data di fine."""
    return ciclo.data_fine if ciclo and ciclo.chiuso and ciclo.data_fine else None


def _url(nome):
    """Indirizzi delle pagine a cui la scheda rimanda per aggiornare un dato."""
    return url_for({"impostazioni": "allevamento.soccida_impostazioni", "censimento": "allevamento.censimento",
                    "consegne": "allevamento.consegne", "spostamenti": "allevamento.spostamenti"}[nome])


def _numero(testo, intero=False):
    """Numero scritto all'italiana o dai campi numerici del browser, o None se vuoto.
    «16,38» e «1.820,5» usano la virgola per i decimali; «98.000» e «1.820» (gruppi di tre cifre dopo
    il punto) sono migliaia; «83.5» o «3.0», come li invia un campo type=number, sono decimali."""
    t = (testo or "").strip().replace(" ", "")
    if not t:
        return None
    if "," in t or re.fullmatch(r"-?\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "").replace(",", ".")
    v = float(t)
    return int(round(v)) if intero else v


# ── La scheda ───────────────────────────────────────────────────────────────

@bp.route("/soccida")
@login_required
def soccida():
    _puo_vedere()
    modifica = current_user.role == "admin"
    ciclo = _ciclo()
    if not ciclo:
        return render_template("allevamento/soccida.html", s=None, modifica=modifica)
    par = D.parametri(ciclo)
    from app.services import cicli_riepilogo as R
    foto = R.ultima_fotografia(ciclo)
    return render_template("allevamento/soccida.html", s=V.scheda(ciclo, par, request.args, _url, oggi=_oggi(ciclo)),
                           par=par, modifica=modifica, foto=foto, foto_dati=R.dati_fotografia(foto),
                           correnti=R.dati_correnti(ciclo) if (foto or ciclo.chiuso) else None)


@bp.route("/soccida/scenario", methods=["POST"])
@login_required
def soccida_scenario():
    """Salva i valori provati nella scheda come scenario standard."""
    _solo_admin()
    ciclo = _ciclo()
    if not ciclo:
        abort(404)
    par = D.parametri(ciclo)
    try:
        primo, ultimo = date.fromisoformat(request.form["primo"]), date.fromisoformat(request.form["ultimo"])
        if ultimo < primo:
            raise ValueError("l'ultimo carico non può venire prima del primo")
        par.primo_carico, par.ultimo_carico = primo, ultimo
        par.date_confermate = request.form.get("conf") == "1"
        par.peso_extra_kg = _numero(request.form.get("peso")) or 0.0
        for campo, nome in (("resa_perc", "resa"), ("premi_perc", "premi"), ("morti_giorno", "morti"), ("giacenza_iniziale_kg", "giac")):
            v = _numero(request.form.get(nome))
            if v is not None:
                setattr(par, campo, v)
        db.session.commit()
        flash("Scenario standard aggiornato.", "success")
    except (KeyError, ValueError) as e:
        db.session.rollback()
        flash(f"Scenario non salvato: {e}", "danger")
    return redirect(url_for("allevamento.soccida"))


# ── Impostazioni ────────────────────────────────────────────────────────────

CAMPI_NUMERICI = ("minimo_annuo", "prezzo_partenza", "premio_tabella_perc", "quota_scarti_perc", "calo_scarti_perc",
                  "resa_partenza_perc", "premio_extra_perc", "premi_perc", "peso_extra_kg", "resa_perc", "morti_giorno")
CAMPI_INTERI = ("posti", "suini_cabianca", "capi_carico", "carichi_giorno")
CAMPI_FACOLTATIVI = ("giacenza_iniziale_kg", "giacenza_finale_kg")     # vuoto = non ancora noto
CAMPI_DATA = ("ultimo_giorno_pagato_prec", "primo_carico", "ultimo_carico")
CAMPI_TESTO = ("fornitori_siero_piva", "anticipi_pagante")


@bp.route("/soccida/impostazioni")
@login_required
def soccida_impostazioni():
    _solo_admin()
    ciclo = _ciclo()
    if not ciclo:
        return render_template("allevamento/soccida_impostazioni.html", ciclo=None)
    par = D.parametri(ciclo)
    contratto = D.contratto(ciclo, par)
    righe = SoccidaTabella.query.filter_by(ciclo_id=ciclo.id).order_by(SoccidaTabella.indice).all()
    # fatture dei fornitori di siero vicine al ciclo, con il ciclo in cui contano
    piva = D._piva_siero(par)
    del_ciclo = {f.id for f in D.fatture_siero(ciclo, par)}
    a_mano = {f.sdi_invoice_id for f in SoccidaFattura.query.all()}
    fatture = []
    if piva:
        # dalle fatture di quattro mesi prima dell'inizio: bastano per vedere quelle a cavallo con il ciclo scorso
        q = SdiInvoice.query.filter(SdiInvoice.sender_partita_iva.in_(piva), SdiInvoice.direction == "ricevuta",
                                    SdiInvoice.invoice_date >= ciclo.data_inizio - timedelta(days=120))
        fatture = [{"f": f, "nel_ciclo": f.id in del_ciclo, "a_mano": f.id in a_mano} for f in q.order_by(SdiInvoice.invoice_date)]
    migliori, peggiori = S.righe_prolungate(contratto.tabella)     # come prosegue la tabella oltre le righe di Veronesi
    return render_template(
        "allevamento/soccida_impostazioni.html", ciclo=ciclo, par=par, righe=righe, prezzo_tabella=contratto.prezzo_tabella,
        righe_migliori=migliori, righe_peggiori=peggiori,
        anticipi=D.anticipi(ciclo), da_banca=D.anticipi_da_banca(ciclo, par), fatture=fatture, V=V)


@bp.route("/soccida/impostazioni", methods=["POST"])
@login_required
def soccida_impostazioni_salva():
    _solo_admin()
    ciclo = _ciclo()
    if not ciclo:
        abort(404)
    par = D.parametri(ciclo)
    try:
        for campo in CAMPI_NUMERICI:
            v = _numero(request.form.get(campo))
            if v is None:
                raise ValueError(f"manca il valore di «{campo}»")
            setattr(par, campo, v)
        for campo in CAMPI_INTERI:
            v = _numero(request.form.get(campo), intero=True)
            setattr(par, campo, v if v is not None else 0)
        for campo in CAMPI_FACOLTATIVI:
            setattr(par, campo, _numero(request.form.get(campo)))
        for campo in CAMPI_DATA:
            setattr(par, campo, date.fromisoformat(request.form[campo]))
        for campo in CAMPI_TESTO:
            setattr(par, campo, (request.form.get(campo) or "").strip() or None)
        par.date_confermate = request.form.get("date_confermate") == "1"
        par.premi_noti = request.form.get("premi_noti") == "1"
        if par.ultimo_carico < par.primo_carico:
            raise ValueError("l'ultimo carico non può venire prima del primo")
        if par.capi_carico < 1 or par.carichi_giorno < 1:
            raise ValueError("capi per carico e carichi al giorno devono essere almeno 1")
        db.session.commit()
        flash("Impostazioni della soccida salvate.", "success")
    except (KeyError, ValueError) as e:
        db.session.rollback()
        flash(f"Impostazioni non salvate: {e}", "danger")
    return redirect(url_for("allevamento.soccida_impostazioni"))


@bp.route("/soccida/tabella", methods=["POST"])
@login_required
def soccida_tabella_salva():
    """Sostituisce la tabella di rapporto del ciclo con le righe inviate (le righe vuote si scartano)."""
    _solo_admin()
    ciclo = _ciclo()
    if not ciclo:
        abort(404)
    try:
        righe = {}
        for indice, perc in zip(request.form.getlist("indice"), request.form.getlist("percentuale")):
            i, p = _numero(indice), _numero(perc)
            if i is None and p is None:
                continue
            if i is None or p is None:
                raise ValueError("ogni riga vuole indice e percentuale")
            righe[round(i, 3)] = p
        if len(righe) < 2:
            raise ValueError("servono almeno due righe")
        SoccidaTabella.query.filter_by(ciclo_id=ciclo.id).delete()
        for i, p in sorted(righe.items()):
            db.session.add(SoccidaTabella(ciclo_id=ciclo.id, indice=i, percentuale=p))
        db.session.commit()
        flash("Tabella di rapporto salvata.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(f"Tabella non salvata: {e}", "danger")
    return redirect(url_for("allevamento.soccida_impostazioni") + "#tabella")


@bp.route("/soccida/anticipi", methods=["POST"])
@login_required
def soccida_anticipo_nuovo():
    """Aggiunge un anticipo: a mano (data e importo) o da un bonifico trovato in banca (bank_id)."""
    _solo_admin()
    ciclo = _ciclo()
    if not ciclo:
        abort(404)
    try:
        bank_id = request.form.get("bank_id")
        if bank_id:
            t = db.session.get(BankTransaction, int(bank_id))
            if not t or SoccidaAnticipo.query.filter_by(bank_transaction_id=t.id).first():
                raise ValueError("bonifico non trovato o già registrato")
            db.session.add(SoccidaAnticipo(ciclo_id=ciclo.id, data=t.operation_date, importo=t.amount, bank_transaction_id=t.id,
                                           nota=(t.remittance_info or "").strip()[:200] or None))
        else:
            importo = _numero(request.form.get("importo"))
            if not importo or importo <= 0:
                raise ValueError("importo mancante")
            db.session.add(SoccidaAnticipo(ciclo_id=ciclo.id, data=date.fromisoformat(request.form["data"]), importo=importo,
                                           nota=(request.form.get("nota") or "").strip() or None))
        db.session.commit()
        flash("Anticipo registrato.", "success")
    except (KeyError, ValueError) as e:
        db.session.rollback()
        flash(f"Anticipo non registrato: {e}", "danger")
    return redirect(url_for("allevamento.soccida_impostazioni") + "#anticipi")


@bp.route("/soccida/anticipi/<int:aid>/elimina", methods=["POST"])
@login_required
def soccida_anticipo_elimina(aid):
    _solo_admin()
    a = db.session.get(SoccidaAnticipo, aid)
    if a:
        db.session.delete(a)
        db.session.commit()
        flash("Anticipo eliminato.", "success")
    return redirect(url_for("allevamento.soccida_impostazioni") + "#anticipi")


@bp.route("/soccida/fatture/<int:fid>", methods=["POST"])
@login_required
def soccida_fattura_assegna(fid):
    """Assegna a mano una fattura di siero: a questo ciclo, fuori da questo ciclo, o di nuovo «secondo la data»."""
    _solo_admin()
    ciclo = _ciclo()
    f = db.session.get(SdiInvoice, fid)
    if not ciclo or not f:
        abort(404)
    scelta = request.form.get("scelta")
    riga = SoccidaFattura.query.filter_by(sdi_invoice_id=fid).first()
    if scelta == "data":
        if riga:
            db.session.delete(riga)
    elif scelta in ("dentro", "fuori"):
        riga = riga or SoccidaFattura(sdi_invoice_id=fid)
        riga.ciclo_id = ciclo.id if scelta == "dentro" else None
        db.session.add(riga)
    db.session.commit()
    flash("Assegnazione della fattura aggiornata.", "success")
    return redirect(url_for("allevamento.soccida_impostazioni") + "#fatture")


# ── Fotografia del conto e cicli a confronto (3.6.0) ────────────────────────

@bp.route("/soccida/fotografia", methods=["POST"])
@login_required
def soccida_fotografia():
    """Salva il conto del ciclo così com'è adesso, con la liquidazione di Veronesi se è arrivata."""
    _solo_admin()
    from app.services import cicli_riepilogo as R
    ciclo = _ciclo()
    if not ciclo:
        abort(404)
    try:
        R.fotografa(ciclo, current_user.display_name or current_user.username,
                    liquidato_eur=_numero(request.form.get("liquidato")), nota=(request.form.get("nota") or "").strip() or None)
        db.session.commit()
        flash(f"Conto di «{ciclo.nome}» salvato: da qui in poi la tabella dei cicli usa questi numeri.", "success")
    except ValueError as e:
        db.session.rollback()
        flash(f"Conto non salvato: {e}", "danger")
    return redirect(url_for("allevamento.soccida") + "#fotografia")


@bp.route("/cicli")
@login_required
def cicli():
    """Tutti i cicli a confronto: numeri finali, giacenze e conto (anche quelli vecchi dall'Excel)."""
    _puo_vedere()
    from app.services import cicli_riepilogo as R
    from app.models import CicloStorico
    R.importa_excel_se_serve()
    valori = {c.id: dict({k: getattr(c, k) for k in CAMPI_STORICO_INTERI + CAMPI_STORICO_NUMERI},
                         premi_perc_prontuario=c.premi_perc) for c in CicloStorico.query.all()}
    return render_template("allevamento/cicli.html", righe=R.tabella(), modifica=current_user.role == "admin",
                           storico_valori=valori)


CAMPI_STORICO_INTERI = ("posti", "capi_entrati", "capi_cabianca", "capi_usciti", "morti", "giorni_pagati")
CAMPI_STORICO_NUMERI = ("giacenza_iniziale_kg", "mangime_bolle_kg", "giacenza_finale_kg", "mangime_consumato_kg",
                        "carne_kg", "indice", "premi_perc", "premio_extra_perc", "siero_eur", "resa_eur", "minimo_eur",
                        "anticipi_eur", "saldo_eur")


@bp.route("/cicli/storico/<int:sid>", methods=["POST"])
@login_required
def ciclo_storico_salva(sid):
    _solo_admin()
    from app.models import CicloStorico
    c = db.session.get(CicloStorico, sid)
    if not c:
        abort(404)
    try:
        if request.form.get("elimina") == "1":
            db.session.delete(c)
            db.session.commit()
            flash(f"«{c.nome}» eliminato dallo storico.", "success")
            return redirect(url_for("allevamento.cicli"))
        c.nome = (request.form.get("nome") or c.nome).strip()
        c.data_inizio = date.fromisoformat(request.form["data_inizio"])
        c.data_fine = date.fromisoformat(request.form["data_fine"]) if request.form.get("data_fine") else None
        for campo in CAMPI_STORICO_INTERI:
            setattr(c, campo, _numero(request.form.get(campo), intero=True))
        for campo in CAMPI_STORICO_NUMERI:
            setattr(c, campo, _numero(request.form.get(campo)))
        c.controllato = request.form.get("controllato") == "1"
        c.note = (request.form.get("note") or "").strip() or None
        db.session.commit()
        flash(f"«{c.nome}» salvato.", "success")
    except (KeyError, ValueError) as e:
        db.session.rollback()
        flash(f"Non salvato: {e}", "danger")
    return redirect(url_for("allevamento.cicli") + f"#storico-{sid}")
