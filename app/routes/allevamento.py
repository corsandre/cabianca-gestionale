from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from app import db

bp = Blueprint("allevamento", __name__, url_prefix="/allevamento")

# Struttura fisica fissa
CAP_PER_BOX = {
    **{i: 1 for i in range(1, 10)},
    **{i: 2 for i in range(10, 16)},
    **{i: 3 for i in range(16, 22)},
    **{i: 4 for i in range(22, 37)},
    **{i: 5 for i in range(37, 43)},
    **{i: 7 for i in range(43, 50)},
    **{i: 6 for i in range(50, 55)},
}
LINEA_PER_BOX = {
    **{i: 1 for i in range(1, 22)},
    **{i: 2 for i in range(22, 37)},
    **{i: 3 for i in range(37, 55)},
}
POSTI_PER_BOX_STANDARD = {
    **{i: 40 for i in range(1, 10)},
    **{i: 26 for i in range(10, 16)},
    **{i: 10 for i in range(16, 22)},
    **{i: 38 for i in range(22, 37)},
    **{i: 38 for i in range(37, 43)},
    **{i: 31 for i in range(43, 49)},
    49: 32,
    50: 47, 51: 47, 52: 46, 53: 45, 54: 45,
}
CAPANNONI = [1, 2, 3, 4, 5, 6, 7]
BOX_PER_CAP = {
    1: list(range(1, 10)), 2: list(range(10, 16)), 3: list(range(16, 22)),
    4: list(range(22, 37)), 5: list(range(37, 43)), 7: list(range(43, 50)),
    6: list(range(50, 55)),
}
POSTI_PER_CAP = {cap: sum(POSTI_PER_BOX_STANDARD[b] for b in boxes) for cap, boxes in BOX_PER_CAP.items()}
GIORNI_SETTIMANA = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]


def _check_allevamento():
    if not current_user.has_section("allevamento"):
        flash("Accesso non autorizzato alla sezione allevamento.", "danger")
        abort(403)


def _get_ciclo_attivo():
    from app.models import Ciclo
    return Ciclo.query.filter_by(attivo=True).order_by(Ciclo.data_inizio.desc()).first()


def _live_count(ciclo):
    from app.models import Censimento, EventoMortalita, Spostamento
    ultimo = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(
        Censimento.data.desc(), Censimento.id.desc()
    ).first()
    if not ultimo:
        return {b: 0 for b in range(1, 55)}

    count = {b: 0 for b in range(1, 55)}
    for cb in ultimo.conteggi.all():
        count[cb.box_numero] = cb.quantita

    morti = EventoMortalita.query.filter(
        EventoMortalita.ciclo_id == ciclo.id,
        EventoMortalita.data >= ultimo.data,
    ).all()
    for m in morti:
        if m.box_numero:
            count[m.box_numero] = max(0, count.get(m.box_numero, 0) - m.quantita)
        else:
            boxes_cap = BOX_PER_CAP.get(m.capannone_numero, [])
            if boxes_cap:
                per_box = m.quantita // len(boxes_cap)
                resto = m.quantita % len(boxes_cap)
                for i, b in enumerate(boxes_cap):
                    sottrai = per_box + (1 if i < resto else 0)
                    count[b] = max(0, count.get(b, 0) - sottrai)

    spostamenti = Spostamento.query.filter(
        Spostamento.ciclo_id == ciclo.id,
        Spostamento.data >= ultimo.data,
    ).all()
    for s in spostamenti:
        if s.tipo == "interno":
            if s.box_origine:
                count[s.box_origine] = max(0, count.get(s.box_origine, 0) - s.quantita)
            if s.box_destinazione:
                count[s.box_destinazione] = count.get(s.box_destinazione, 0) + s.quantita
        elif s.tipo == "entrata":
            if s.box_destinazione:
                count[s.box_destinazione] = count.get(s.box_destinazione, 0) + s.quantita
        elif s.tipo == "uscita":
            if s.box_origine:
                count[s.box_origine] = max(0, count.get(s.box_origine, 0) - s.quantita)

    return count


# ── Dashboard ──────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def index():
    _check_allevamento()
    from app.models import EventoMortalita, ConsegnaSiero, ConsegnaMangime, Censimento
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        return render_template("allevamento/index.html", ciclo=None,
                               cap_data={}, kpi={}, consegne_siero=[], consegne_mangime=[],
                               CAP_PER_BOX=CAP_PER_BOX, BOX_PER_CAP=BOX_PER_CAP,
                               POSTI_PER_CAP=POSTI_PER_CAP, CAPANNONI=CAPANNONI)

    live = _live_count(ciclo)
    oggi = date.today()
    inizio_settimana = oggi - timedelta(days=oggi.weekday())

    morti_settimana = db.session.query(db.func.sum(EventoMortalita.quantita)).filter(
        EventoMortalita.ciclo_id == ciclo.id,
        EventoMortalita.data >= inizio_settimana,
    ).scalar() or 0

    morti_totali = db.session.query(db.func.sum(EventoMortalita.quantita)).filter(
        EventoMortalita.ciclo_id == ciclo.id,
    ).scalar() or 0

    ultimo_censimento = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(
        Censimento.data.desc()
    ).first()

    cap_data = {}
    for cap in CAPANNONI:
        boxes = BOX_PER_CAP[cap]
        vivi = sum(live.get(b, 0) for b in boxes)
        posti = POSTI_PER_CAP[cap]
        perc = (vivi / posti * 100) if posti else 0
        cap_data[cap] = {"vivi": vivi, "posti": posti, "perc": round(perc, 1)}

    kpi = {
        "vivi_totali": sum(live.values()),
        "morti_settimana": morti_settimana,
        "morti_totali": morti_totali,
        "ultimo_censimento": ultimo_censimento,
    }

    consegne_siero = ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).order_by(
        ConsegnaSiero.data.desc()
    ).limit(5).all()
    consegne_mangime = ConsegnaMangime.query.filter_by(ciclo_id=ciclo.id).order_by(
        ConsegnaMangime.data.desc()
    ).limit(5).all()

    return render_template("allevamento/index.html",
                           ciclo=ciclo, cap_data=cap_data, kpi=kpi,
                           consegne_siero=consegne_siero, consegne_mangime=consegne_mangime,
                           CAP_PER_BOX=CAP_PER_BOX, BOX_PER_CAP=BOX_PER_CAP,
                           POSTI_PER_CAP=POSTI_PER_CAP, CAPANNONI=CAPANNONI)


# ── Mortalità ──────────────────────────────────────────────────────────────

@bp.route("/mortalita")
@login_required
def mortalita():
    _check_allevamento()
    from app.models import EventoMortalita
    ciclo = _get_ciclo_attivo()

    # Selettore settimana
    settimana_offset = int(request.args.get("settimana", 0))
    oggi = date.today()
    lun = oggi - timedelta(days=oggi.weekday()) + timedelta(weeks=settimana_offset)
    dom = lun + timedelta(days=6)

    # Griglia [giorno][cap] → quantità
    morti_periodo = EventoMortalita.query.filter(
        EventoMortalita.ciclo_id == ciclo.id if ciclo else False,
        EventoMortalita.data >= lun,
        EventoMortalita.data <= dom,
    ).all() if ciclo else []

    griglia = {}
    for i in range(7):
        d = lun + timedelta(days=i)
        griglia[d] = {cap: 0 for cap in CAPANNONI}
    for m in morti_periodo:
        if m.data in griglia:
            griglia[m.data][m.capannone_numero] = griglia[m.data].get(m.capannone_numero, 0) + m.quantita

    # Ultimi 30gg eventi
    ultimi = EventoMortalita.query.filter(
        EventoMortalita.ciclo_id == ciclo.id if ciclo else False,
        EventoMortalita.data >= oggi - timedelta(days=30),
    ).order_by(EventoMortalita.data.desc(), EventoMortalita.id.desc()).all() if ciclo else []

    return render_template("allevamento/mortalita.html",
                           ciclo=ciclo, griglia=griglia, lun=lun, dom=dom,
                           settimana_offset=settimana_offset,
                           CAPANNONI=CAPANNONI, BOX_PER_CAP=BOX_PER_CAP,
                           ultimi=ultimi, oggi=oggi)


@bp.route("/mortalita/new", methods=["POST"])
@login_required
def mortalita_new():
    _check_allevamento()
    from app.models import EventoMortalita
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.mortalita"))

    try:
        data_str = request.form.get("data", str(date.today()))
        data_ev = date.fromisoformat(data_str)
        cap = int(request.form["capannone"])
        box = request.form.get("box")
        box_num = int(box) if box else None
        qty = int(request.form.get("quantita", 1))
        causa = request.form.get("causa", "").strip() or None
        note = request.form.get("note", "").strip() or None

        ev = EventoMortalita(
            ciclo_id=ciclo.id, data=data_ev,
            capannone_numero=cap, box_numero=box_num,
            quantita=qty, causa=causa, note=note,
        )
        db.session.add(ev)
        db.session.commit()
        flash(f"Registrati {qty} morti in CAP {cap}" + (f" box {box_num}" if box_num else "") + ".", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.mortalita"))


@bp.route("/mortalita/<int:ev_id>/delete", methods=["POST"])
@login_required
def mortalita_delete(ev_id):
    _check_allevamento()
    from app.models import EventoMortalita
    ev = db.session.get(EventoMortalita, ev_id)
    if ev:
        db.session.delete(ev)
        db.session.commit()
        flash("Evento eliminato.", "success")
    return redirect(url_for("allevamento.mortalita"))


# ── Censimento ─────────────────────────────────────────────────────────────

@bp.route("/censimento")
@login_required
def censimento():
    _check_allevamento()
    from app.models import Censimento
    ciclo = _get_ciclo_attivo()
    live = _live_count(ciclo) if ciclo else {b: 0 for b in range(1, 55)}

    storico = Censimento.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(Censimento.data.desc()).limit(20).all() if ciclo else []

    storico_totali = {}
    for c in storico:
        storico_totali[c.id] = sum(cb.quantita for cb in c.conteggi.all())

    return render_template("allevamento/censimento.html",
                           ciclo=ciclo, live=live, storico=storico,
                           storico_totali=storico_totali,
                           BOX_PER_CAP=BOX_PER_CAP, CAPANNONI=CAPANNONI,
                           POSTI_PER_BOX_STANDARD=POSTI_PER_BOX_STANDARD,
                           oggi=date.today())


@bp.route("/censimento/new", methods=["POST"])
@login_required
def censimento_new():
    _check_allevamento()
    from app.models import Censimento, CensimentoBox
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.censimento"))

    try:
        data_str = request.form.get("data", str(date.today()))
        data_cens = date.fromisoformat(data_str)
        operatore = request.form.get("operatore", "").strip() or None
        note = request.form.get("note", "").strip() or None

        cens = Censimento(ciclo_id=ciclo.id, data=data_cens, operatore=operatore, note=note)
        db.session.add(cens)
        db.session.flush()

        totale = 0
        for b in range(1, 55):
            val = request.form.get(f"box_{b}", "0").strip()
            qty = int(val) if val.isdigit() else 0
            db.session.add(CensimentoBox(censimento_id=cens.id, box_numero=b, quantita=qty))
            totale += qty

        db.session.commit()
        flash(f"Censimento salvato: {totale} suini totali.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.censimento"))


# ── Spostamenti ────────────────────────────────────────────────────────────

@bp.route("/spostamenti")
@login_required
def spostamenti():
    _check_allevamento()
    from app.models import Spostamento
    ciclo = _get_ciclo_attivo()

    tipo_filter = request.args.get("tipo", "")
    q = Spostamento.query.filter_by(ciclo_id=ciclo.id if ciclo else -1)
    if tipo_filter:
        q = q.filter_by(tipo=tipo_filter)
    lista = q.order_by(Spostamento.data.desc(), Spostamento.id.desc()).limit(100).all() if ciclo else []

    totali = {"entrata": 0, "uscita": 0, "interno": 0}
    if ciclo:
        for tipo in totali:
            totali[tipo] = db.session.query(db.func.sum(Spostamento.quantita)).filter(
                Spostamento.ciclo_id == ciclo.id,
                Spostamento.tipo == tipo,
            ).scalar() or 0

    return render_template("allevamento/spostamenti.html",
                           ciclo=ciclo, lista=lista, totali=totali,
                           tipo_filter=tipo_filter,
                           BOX_PER_CAP=BOX_PER_CAP, CAPANNONI=CAPANNONI,
                           oggi=date.today())


@bp.route("/spostamenti/new", methods=["POST"])
@login_required
def spostamenti_new():
    _check_allevamento()
    from app.models import Spostamento
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.spostamenti"))

    try:
        data_str = request.form.get("data", str(date.today()))
        tipo = request.form["tipo"]
        qty = int(request.form["quantita"])
        motivo = request.form.get("motivo", "").strip() or None
        note = request.form.get("note", "").strip() or None

        box_orig = request.form.get("box_origine")
        box_dest = request.form.get("box_destinazione")
        cap_orig = request.form.get("capannone_origine")
        cap_dest = request.form.get("capannone_destinazione")

        s = Spostamento(
            ciclo_id=ciclo.id,
            data=date.fromisoformat(data_str),
            tipo=tipo, quantita=qty, motivo=motivo, note=note,
            box_origine=int(box_orig) if box_orig else None,
            box_destinazione=int(box_dest) if box_dest else None,
            capannone_origine=int(cap_orig) if cap_orig else None,
            capannone_destinazione=int(cap_dest) if cap_dest else None,
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Spostamento registrato: {qty} capi ({tipo}).", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.spostamenti"))


@bp.route("/spostamenti/<int:sp_id>/delete", methods=["POST"])
@login_required
def spostamenti_delete(sp_id):
    _check_allevamento()
    from app.models import Spostamento
    s = db.session.get(Spostamento, sp_id)
    if s:
        db.session.delete(s)
        db.session.commit()
        flash("Spostamento eliminato.", "success")
    return redirect(url_for("allevamento.spostamenti"))


# ── Consegne ───────────────────────────────────────────────────────────────

@bp.route("/consegne")
@login_required
def consegne():
    _check_allevamento()
    from app.models import ConsegnaSiero, ConsegnaMangime
    ciclo = _get_ciclo_attivo()

    tab = request.args.get("tab", "siero")
    siero_list = ConsegnaSiero.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(ConsegnaSiero.data.desc()).all() if ciclo else []
    mangime_list = ConsegnaMangime.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(ConsegnaMangime.data.desc()).all() if ciclo else []

    tot_siero = sum(c.quantita_qli for c in siero_list)
    tot_mangime = sum(c.quantita_qli for c in mangime_list)

    return render_template("allevamento/consegne.html",
                           ciclo=ciclo, tab=tab,
                           siero_list=siero_list, mangime_list=mangime_list,
                           tot_siero=tot_siero, tot_mangime=tot_mangime,
                           oggi=date.today())


@bp.route("/consegne/siero/new", methods=["POST"])
@login_required
def consegne_siero_new():
    _check_allevamento()
    from app.models import ConsegnaSiero
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.consegne", tab="siero"))
    try:
        from datetime import time as dt_time
        data_str = request.form.get("data", str(date.today()))
        ora_str = request.form.get("ora", "").strip()
        ora = dt_time.fromisoformat(ora_str) if ora_str else None
        qty = float(request.form["quantita_qli"])
        c = ConsegnaSiero(
            ciclo_id=ciclo.id, data=date.fromisoformat(data_str), ora=ora,
            quantita_qli=qty,
            lotto=request.form.get("lotto", "").strip() or None,
            speditore=request.form.get("speditore", "").strip() or None,
            trasportatore=request.form.get("trasportatore", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
        )
        db.session.add(c)
        db.session.commit()
        flash(f"Consegna siero registrata: {qty} qli.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="siero"))


@bp.route("/consegne/siero/<int:cid>/delete", methods=["POST"])
@login_required
def consegne_siero_delete(cid):
    _check_allevamento()
    from app.models import ConsegnaSiero
    c = db.session.get(ConsegnaSiero, cid)
    if c:
        db.session.delete(c)
        db.session.commit()
        flash("Consegna siero eliminata.", "success")
    return redirect(url_for("allevamento.consegne", tab="siero"))


@bp.route("/consegne/mangime/new", methods=["POST"])
@login_required
def consegne_mangime_new():
    _check_allevamento()
    from app.models import ConsegnaMangime
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.consegne", tab="mangime"))
    try:
        from datetime import time as dt_time
        data_str = request.form.get("data", str(date.today()))
        ora_str = request.form.get("ora", "").strip()
        ora = dt_time.fromisoformat(ora_str) if ora_str else None
        qty = float(request.form["quantita_qli"])
        c = ConsegnaMangime(
            ciclo_id=ciclo.id, data=date.fromisoformat(data_str), ora=ora,
            quantita_qli=qty,
            tipo_mangime=request.form.get("tipo_mangime", "").strip() or None,
            numero_bolla=request.form.get("numero_bolla", "").strip() or None,
            fornitore=request.form.get("fornitore", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
        )
        db.session.add(c)
        db.session.commit()
        flash(f"Consegna mangime registrata: {qty} qli.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="mangime"))


@bp.route("/consegne/mangime/<int:cid>/delete", methods=["POST"])
@login_required
def consegne_mangime_delete(cid):
    _check_allevamento()
    from app.models import ConsegnaMangime
    c = db.session.get(ConsegnaMangime, cid)
    if c:
        db.session.delete(c)
        db.session.commit()
        flash("Consegna mangime eliminata.", "success")
    return redirect(url_for("allevamento.consegne", tab="mangime"))


# ── Alimentazione ──────────────────────────────────────────────────────────

@bp.route("/alimentazione")
@login_required
def alimentazione():
    _check_allevamento()
    from app.models import UsoPasto
    ciclo = _get_ciclo_attivo()

    data_str = request.args.get("data", str(date.today()))
    try:
        data_sel = date.fromisoformat(data_str)
    except ValueError:
        data_sel = date.today()

    pasti = {}
    if ciclo:
        for p in UsoPasto.query.filter_by(ciclo_id=ciclo.id, data=data_sel).all():
            pasti[(p.pasto, p.linea)] = p

    # Totali giornalieri per linea
    totali = {linea: {"mangime": 0, "siero": 0, "acqua": 0} for linea in [1, 2, 3]}
    for (pasto, linea), p in pasti.items():
        totali[linea]["mangime"] += p.mangime_kg or 0
        totali[linea]["siero"] += p.siero_kg or 0
        totali[linea]["acqua"] += p.acqua_litri or 0

    return render_template("allevamento/alimentazione.html",
                           ciclo=ciclo, data_sel=data_sel, pasti=pasti,
                           totali=totali)


@bp.route("/alimentazione/new", methods=["POST"])
@login_required
def alimentazione_new():
    _check_allevamento()
    from app.models import UsoPasto
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.alimentazione"))

    try:
        data_str = request.form.get("data", str(date.today()))
        data_pasto = date.fromisoformat(data_str)

        for pasto in [1, 2, 3]:
            for linea in [1, 2, 3]:
                mang = request.form.get(f"mang_{pasto}_{linea}", "").strip()
                siero = request.form.get(f"siero_{pasto}_{linea}", "").strip()
                acqua = request.form.get(f"acqua_{pasto}_{linea}", "").strip()

                if not any([mang, siero, acqua]):
                    continue

                esistente = UsoPasto.query.filter_by(
                    ciclo_id=ciclo.id, data=data_pasto, pasto=pasto, linea=linea
                ).first()

                vals = {
                    "mangime_kg": float(mang) if mang else None,
                    "siero_kg": float(siero) if siero else None,
                    "acqua_litri": float(acqua) if acqua else None,
                    "tipo_mangime": request.form.get("tipo_mangime", "").strip() or None,
                    "perc_siero": float(request.form.get("perc_siero", "") or 0) or None,
                }

                if esistente:
                    for k, v in vals.items():
                        setattr(esistente, k, v)
                else:
                    db.session.add(UsoPasto(
                        ciclo_id=ciclo.id, data=data_pasto, pasto=pasto, linea=linea, **vals
                    ))

        db.session.commit()
        flash("Dati alimentazione salvati.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.alimentazione", data=data_str))


# ── Razione Box ────────────────────────────────────────────────────────────

@bp.route("/razione")
@login_required
def razione():
    _check_allevamento()
    from app.models import RazioneBox
    ciclo = _get_ciclo_attivo()

    settimana_offset = int(request.args.get("settimana", 0))
    oggi = date.today()
    lun = oggi - timedelta(days=oggi.weekday()) + timedelta(weeks=settimana_offset)
    giorni = [lun + timedelta(days=i) for i in range(7)]

    # Dati esistenti per la settimana + settimana precedente (carry-forward)
    lun_prec = lun - timedelta(days=7)
    razioni_raw = RazioneBox.query.filter(
        RazioneBox.ciclo_id == ciclo.id if ciclo else False,
        RazioneBox.data >= lun_prec,
        RazioneBox.data <= giorni[-1],
    ).all() if ciclo else []

    # {box: {data: perc}}
    razioni = {}
    for r in razioni_raw:
        razioni.setdefault(r.box_numero, {})[r.data] = r.percentuale

    return render_template("allevamento/razione.html",
                           ciclo=ciclo, giorni=giorni, razioni=razioni,
                           settimana_offset=settimana_offset,
                           BOX_PER_CAP=BOX_PER_CAP, CAPANNONI=CAPANNONI,
                           lun=lun, GIORNI_SETTIMANA=GIORNI_SETTIMANA)


@bp.route("/razione/save", methods=["POST"])
@login_required
def razione_save():
    _check_allevamento()
    from app.models import RazioneBox
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.razione"))

    try:
        settimana_offset = int(request.form.get("settimana_offset", 0))
        oggi = date.today()
        lun = oggi - timedelta(days=oggi.weekday()) + timedelta(weeks=settimana_offset)
        giorni = [lun + timedelta(days=i) for i in range(7)]

        salvati = 0
        for b in range(1, 55):
            for g in giorni:
                key = f"raz_{b}_{g.isoformat()}"
                val = request.form.get(key, "").strip()
                if not val:
                    continue
                try:
                    perc = float(val)
                except ValueError:
                    continue

                esistente = RazioneBox.query.filter_by(
                    ciclo_id=ciclo.id, data=g, box_numero=b
                ).first()
                if esistente:
                    esistente.percentuale = perc
                else:
                    db.session.add(RazioneBox(
                        ciclo_id=ciclo.id, data=g, box_numero=b, percentuale=perc
                    ))
                salvati += 1

        db.session.commit()
        flash(f"Razione salvata per {salvati} celle.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.razione", settimana=settimana_offset))


# ── Impostazioni / Cicli ───────────────────────────────────────────────────

@bp.route("/impostazioni")
@login_required
def impostazioni():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Ciclo
    ciclo_attivo = _get_ciclo_attivo()
    cicli_precedenti = Ciclo.query.filter_by(attivo=False).order_by(Ciclo.data_inizio.desc()).all()
    return render_template("allevamento/impostazioni.html",
                           ciclo_attivo=ciclo_attivo, cicli_precedenti=cicli_precedenti,
                           oggi=date.today())


@bp.route("/ciclo/new", methods=["POST"])
@login_required
def ciclo_new():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Ciclo
    try:
        nome = request.form["nome"].strip()
        data_inizio = date.fromisoformat(request.form["data_inizio"])
        note = request.form.get("note", "").strip() or None

        # Disattiva tutti i cicli precedenti
        Ciclo.query.filter_by(attivo=True).update({"attivo": False})
        db.session.add(Ciclo(nome=nome, data_inizio=data_inizio, attivo=True, note=note))
        db.session.commit()
        flash(f"Ciclo '{nome}' creato e attivato.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))


@bp.route("/ciclo/<int:cid>/chiudi", methods=["POST"])
@login_required
def ciclo_chiudi(cid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Ciclo
    ciclo = db.session.get(Ciclo, cid)
    if ciclo:
        ciclo.attivo = False
        ciclo.data_fine = date.today()
        db.session.commit()
        flash(f"Ciclo '{ciclo.nome}' chiuso.", "success")
    return redirect(url_for("allevamento.impostazioni"))
