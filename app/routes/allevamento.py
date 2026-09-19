import os
import uuid
from datetime import date, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user
from app import db

bp = Blueprint("allevamento", __name__, url_prefix="/allevamento")

BOLLA_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp"}


def _salva_bolla(file_storage):
    """Salva la foto/PDF di una bolla in UPLOAD_FOLDER/allevamento_consegne e
    ritorna il path relativo da salvare nel DB, o None se non valida."""
    if not file_storage or not file_storage.filename:
        return None
    ext = file_storage.filename.rsplit(".", 1)[-1].lower() if "." in file_storage.filename else ""
    if ext not in BOLLA_EXTENSIONS:
        return None
    filename = f"{uuid.uuid4().hex}.{ext}"
    upload_dir = os.path.join(current_app.config["UPLOAD_FOLDER"], "allevamento_consegne")
    os.makedirs(upload_dir, exist_ok=True)
    file_storage.save(os.path.join(upload_dir, filename))
    return f"allevamento_consegne/{filename}"


def _elimina_bolla(bolla_path):
    if not bolla_path:
        return
    filepath = os.path.join(current_app.config["UPLOAD_FOLDER"], bolla_path)
    try:
        os.remove(filepath)
    except OSError:
        pass

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
    from app.models import EventoMortalita, ConsegnaSiero, ConsegnaMangime, Censimento, UsoPasto
    from app.services.allevamento_scorte import stato_mangime, stato_siero, giacenza_mangime_a_data
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        return render_template("allevamento/index.html", ciclo=None,
                               cap_data={}, kpi={}, consegne_siero=[], consegne_mangime=[],
                               totali_alimentazione_ciclo={"mangime": 0, "siero": 0, "acqua": 0},
                               scorta_mangime=stato_mangime(), scorta_siero=stato_siero(),
                               apertura_mangime=None,
                               stat_fine_ciclo={"capi": 0, "kg": 0}, stat_scarti={"capi": 0, "kg": 0},
                               stat_agriturismo={"capi": 0, "kg": 0},
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

    stat_fine_ciclo = _statistiche_uscita(ciclo.id, "fine_ciclo")
    stat_scarti = _statistiche_uscita(ciclo.id, "scarto_sottopeso")
    stat_agriturismo = _statistiche_uscita(ciclo.id, "agriturismo")

    totali_alimentazione_ciclo = {
        "mangime": db.session.query(db.func.sum(UsoPasto.mangime_qli)).filter(
            UsoPasto.ciclo_id == ciclo.id).scalar() or 0,
        "siero": db.session.query(db.func.sum(UsoPasto.siero_qli)).filter(
            UsoPasto.ciclo_id == ciclo.id).scalar() or 0,
        "acqua": db.session.query(db.func.sum(UsoPasto.acqua_qli)).filter(
            UsoPasto.ciclo_id == ciclo.id).scalar() or 0,
    }

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
                           totali_alimentazione_ciclo=totali_alimentazione_ciclo,
                           scorta_mangime=stato_mangime(), scorta_siero=stato_siero(),
                           apertura_mangime=giacenza_mangime_a_data(ciclo.data_inizio),
                           stat_fine_ciclo=stat_fine_ciclo, stat_scarti=stat_scarti,
                           stat_agriturismo=stat_agriturismo,
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

    # Storico completo del ciclo, paginato
    pagina = request.args.get("pagina", 1, type=int)
    pagination = EventoMortalita.query.filter(
        EventoMortalita.ciclo_id == ciclo.id if ciclo else False,
    ).order_by(EventoMortalita.data.desc(), EventoMortalita.id.desc()).paginate(
        page=pagina, per_page=30
    ) if ciclo else None

    tot_settimana = sum(sum(caps.values()) for caps in griglia.values())

    return render_template("allevamento/mortalita.html",
                           ciclo=ciclo, griglia=griglia, lun=lun, dom=dom,
                           settimana_offset=settimana_offset,
                           CAPANNONI=CAPANNONI, BOX_PER_CAP=BOX_PER_CAP,
                           pagination=pagination, oggi=oggi,
                           tot_settimana=tot_settimana)


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


AZIONI_MORTALITA = {
    "pc": ("pc_alimentazione_data", "pc_alimentazione_operatore"),
    "webfarm": ("webfarm_data", "webfarm_operatore"),
    "rift": ("rift_data", "rift_operatore"),
}


@bp.route("/mortalita/<int:ev_id>/segna/<azione>", methods=["POST"])
@login_required
def mortalita_segna(ev_id, azione):
    _check_allevamento()
    from datetime import datetime
    from app.models import EventoMortalita
    if azione not in AZIONI_MORTALITA:
        return jsonify(error="Azione non valida."), 400
    ev = db.session.get(EventoMortalita, ev_id)
    if not ev:
        return jsonify(error="Evento non trovato."), 404
    campo_data, campo_operatore = AZIONI_MORTALITA[azione]
    ora = datetime.now()
    setattr(ev, campo_data, ora)
    setattr(ev, campo_operatore, current_user.display_name or current_user.username)
    db.session.commit()
    return jsonify(
        ok=True,
        testo=f"{ora.strftime('%d/%m %H:%M')} · {getattr(ev, campo_operatore)}",
    )


@bp.route("/mortalita/<int:ev_id>/annulla/<azione>", methods=["POST"])
@login_required
def mortalita_annulla(ev_id, azione):
    _check_allevamento()
    from app.models import EventoMortalita
    if azione not in AZIONI_MORTALITA:
        return jsonify(error="Azione non valida."), 400
    ev = db.session.get(EventoMortalita, ev_id)
    if not ev:
        return jsonify(error="Evento non trovato."), 404
    campo_data, campo_operatore = AZIONI_MORTALITA[azione]
    setattr(ev, campo_data, None)
    setattr(ev, campo_operatore, None)
    db.session.commit()
    return jsonify(ok=True)


# ── Censimento ─────────────────────────────────────────────────────────────

def _proiezione_giorni_peso(ciclo):
    """Per ogni box, proietta a oggi i giorni di vita dall'ultimo censimento
    che li riportava, e ricalcola il peso stimato con la curva di
    accrescimento (non riusa il peso salvato allora, che nel frattempo è
    invecchiato)."""
    from app.models import Censimento, CensimentoBox
    from app.services.allevamento_scorte import peso_da_giorni
    oggi = date.today()
    righe = (
        CensimentoBox.query.join(Censimento)
        .filter(Censimento.ciclo_id == ciclo.id, CensimentoBox.giorni_vita.isnot(None))
        .order_by(Censimento.data.desc(), Censimento.id.desc())
        .all()
    )
    risultato = {}
    for cb in righe:
        if cb.box_numero in risultato:
            continue
        giorni_oggi = cb.giorni_vita + (oggi - cb.censimento.data).days
        risultato[cb.box_numero] = {"giorni": giorni_oggi, "peso": peso_da_giorni(giorni_oggi)}
    return risultato


@bp.route("/censimento")
@login_required
def censimento():
    _check_allevamento()
    from app.models import Censimento
    ciclo = _get_ciclo_attivo()
    live = _live_count(ciclo) if ciclo else {b: 0 for b in range(1, 55)}
    totale_live = sum(live.values())
    proiezione = _proiezione_giorni_peso(ciclo) if ciclo else {}

    # Tutti i censimenti del ciclo devono restare consultabili, non solo gli ultimi.
    storico = Censimento.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(Censimento.data.desc()).all() if ciclo else []

    storico_totali = {}
    for c in storico:
        storico_totali[c.id] = sum(cb.quantita for cb in c.conteggi.all())

    return render_template("allevamento/censimento.html",
                           ciclo=ciclo, live=live, totale_live=totale_live,
                           storico=storico, storico_totali=storico_totali,
                           proiezione=proiezione,
                           BOX_PER_CAP=BOX_PER_CAP, CAPANNONI=CAPANNONI,
                           POSTI_PER_BOX_STANDARD=POSTI_PER_BOX_STANDARD,
                           oggi=date.today())


@bp.route("/censimento/<int:cid>/dettaglio")
@login_required
def censimento_dettaglio(cid):
    _check_allevamento()
    from app.models import Censimento
    cens = db.session.get(Censimento, cid)
    if not cens:
        return jsonify(error="Censimento non trovato."), 404
    conteggi = {
        str(cb.box_numero): {
            "quantita": cb.quantita,
            "giorni_vita": cb.giorni_vita,
            "peso_stimato_kg": cb.peso_stimato_kg,
        }
        for cb in cens.conteggi.all()
    }
    return jsonify(
        data=cens.data.strftime("%d/%m/%Y"),
        operatore=cens.operatore or "–",
        note=cens.note or "",
        totale=sum(c["quantita"] for c in conteggi.values()),
        conteggi=conteggi,
    )


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

        from app.services.allevamento_scorte import peso_da_giorni, giorni_da_peso

        totale = 0
        for b in range(1, 55):
            val = request.form.get(f"box_{b}", "0").strip()
            qty = int(val) if val.isdigit() else 0
            giorni_val = request.form.get(f"giorni_{b}", "").strip()
            peso_val = request.form.get(f"peso_{b}", "").strip()
            giorni = int(giorni_val) if giorni_val.isdigit() else None
            try:
                peso = float(peso_val.replace(",", ".")) if peso_val else None
            except ValueError:
                peso = None
            # Basta un dato tra i due: l'altro si calcola dalla curva di
            # accrescimento. Se ci sono entrambi, si tengono quelli inseriti.
            if qty > 0:
                if peso is None and giorni is not None:
                    peso = peso_da_giorni(giorni)
                elif giorni is None and peso is not None:
                    giorni = giorni_da_peso(peso)
            db.session.add(CensimentoBox(
                censimento_id=cens.id, box_numero=b, quantita=qty,
                giorni_vita=giorni, peso_stimato_kg=peso,
            ))
            totale += qty

        db.session.commit()
        flash(f"Censimento salvato: {totale} suini totali.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.censimento"))


# ── Spostamenti ────────────────────────────────────────────────────────────

def _statistiche_uscita(ciclo_id, categoria):
    """Capi e kg totali (quantità × peso medio) per una categoria di uscita
    ('fine_ciclo', 'scarto_sottopeso' o 'agriturismo') di questo ciclo."""
    from app.models import Spostamento
    capi = db.session.query(db.func.sum(Spostamento.quantita)).filter(
        Spostamento.ciclo_id == ciclo_id, Spostamento.tipo == "uscita",
        Spostamento.categoria_uscita == categoria,
    ).scalar() or 0
    kg = db.session.query(db.func.sum(Spostamento.quantita * Spostamento.peso_medio_kg)).filter(
        Spostamento.ciclo_id == ciclo_id, Spostamento.tipo == "uscita",
        Spostamento.categoria_uscita == categoria,
    ).scalar() or 0
    return {"capi": capi, "kg": kg}


@bp.route("/spostamenti")
@login_required
def spostamenti():
    _check_allevamento()
    from app.models import Spostamento
    ciclo = _get_ciclo_attivo()

    tipo_filter = request.args.get("tipo", "")
    categoria_filter = request.args.get("categoria", "")
    q = Spostamento.query.filter_by(ciclo_id=ciclo.id if ciclo else -1)
    if categoria_filter:
        q = q.filter_by(tipo="uscita", categoria_uscita=categoria_filter)
    elif tipo_filter:
        q = q.filter_by(tipo=tipo_filter)
    lista = q.order_by(Spostamento.data.desc(), Spostamento.id.desc()).limit(100).all() if ciclo else []

    totali = {"entrata": 0, "uscita": 0, "interno": 0}
    if ciclo:
        for tipo in totali:
            totali[tipo] = db.session.query(db.func.sum(Spostamento.quantita)).filter(
                Spostamento.ciclo_id == ciclo.id,
                Spostamento.tipo == tipo,
            ).scalar() or 0

    stat_fine_ciclo = _statistiche_uscita(ciclo.id, "fine_ciclo") if ciclo else {"capi": 0, "kg": 0}
    stat_scarti = _statistiche_uscita(ciclo.id, "scarto_sottopeso") if ciclo else {"capi": 0, "kg": 0}
    stat_agriturismo = _statistiche_uscita(ciclo.id, "agriturismo") if ciclo else {"capi": 0, "kg": 0}

    return render_template("allevamento/spostamenti.html",
                           ciclo=ciclo, lista=lista, totali=totali,
                           stat_fine_ciclo=stat_fine_ciclo, stat_scarti=stat_scarti,
                           stat_agriturismo=stat_agriturismo,
                           tipo_filter=tipo_filter, categoria_filter=categoria_filter,
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

        # Un capannone intero non si sposta mai tutto insieme: il box è sempre obbligatorio.
        if tipo in ("interno", "uscita") and not box_orig:
            raise ValueError("Il box di origine è obbligatorio.")
        if tipo in ("interno", "entrata") and not box_dest:
            raise ValueError("Il box di destinazione è obbligatorio.")

        categoria_uscita = None
        peso_medio = None
        if tipo == "uscita":
            categoria_uscita = request.form.get("categoria_uscita", "").strip()
            if categoria_uscita not in ("fine_ciclo", "scarto_sottopeso", "agriturismo"):
                raise ValueError("Seleziona la categoria dell'uscita.")
        if tipo in ("entrata", "uscita"):
            peso_val = request.form.get("peso_medio_kg", "").strip()
            peso_medio = float(peso_val.replace(",", ".")) if peso_val else None

        s = Spostamento(
            ciclo_id=ciclo.id,
            data=date.fromisoformat(data_str),
            tipo=tipo, quantita=qty, motivo=motivo, note=note,
            box_origine=int(box_orig) if box_orig else None,
            box_destinazione=int(box_dest) if box_dest else None,
            capannone_origine=int(cap_orig) if cap_orig else None,
            capannone_destinazione=int(cap_dest) if cap_dest else None,
            categoria_uscita=categoria_uscita,
            peso_medio_kg=peso_medio,
            bolla_path=_salva_bolla(request.files.get("bolla")) if tipo in ("entrata", "uscita") else None,
        )
        db.session.add(s)
        db.session.commit()
        flash(f"Spostamento registrato: {qty} capi ({tipo}).", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.spostamenti"))


@bp.route("/spostamenti/<int:sp_id>/bolla", methods=["POST"])
@login_required
def spostamenti_bolla(sp_id):
    _check_allevamento()
    from app.models import Spostamento
    s = db.session.get(Spostamento, sp_id)
    if not s:
        return jsonify(error="Spostamento non trovato."), 404
    path = _salva_bolla(request.files.get("bolla"))
    if not path:
        return jsonify(error="File non valido (usa jpg, png, webp o pdf)."), 400
    _elimina_bolla(s.bolla_path)
    s.bolla_path = path
    db.session.commit()
    return jsonify(ok=True, path=path)


@bp.route("/spostamenti/<int:sp_id>/delete", methods=["POST"])
@login_required
def spostamenti_delete(sp_id):
    _check_allevamento()
    from app.models import Spostamento
    s = db.session.get(Spostamento, sp_id)
    if s:
        _elimina_bolla(s.bolla_path)
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
    from app.services.allevamento_scorte import stato_mangime, stato_siero, scarto_consegna_siero, get_setting_float
    ciclo = _get_ciclo_attivo()

    tab = request.args.get("tab", "siero")
    siero_list = ConsegnaSiero.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(ConsegnaSiero.data.desc()).all() if ciclo else []
    mangime_list = ConsegnaMangime.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(ConsegnaMangime.data.desc()).all() if ciclo else []

    # round(): la somma di float (es. 45.5 + 30.25) può introdurre residui
    # binari tipo 88.05000000000001, visibili altrimenti nel totale.
    tot_siero = round(sum(c.quantita_qli for c in siero_list), 2)
    tot_mangime = round(sum(c.quantita_qli for c in mangime_list), 2)

    soglia_scarto_siero_q = get_setting_float("allevamento_soglia_scarto_siero_q")
    scarti_siero = {
        c.id: scarto_consegna_siero(c, soglia_scarto_siero_q)
        for c in siero_list if c.data_esaurimento
    }

    return render_template("allevamento/consegne.html",
                           ciclo=ciclo, tab=tab,
                           siero_list=siero_list, mangime_list=mangime_list,
                           tot_siero=tot_siero, tot_mangime=tot_mangime,
                           scorta_mangime=stato_mangime(), scorta_siero=stato_siero(),
                           scarti_siero=scarti_siero,
                           oggi=date.today())


@bp.route("/mangime/ricalibra", methods=["POST"])
@login_required
def mangime_ricalibra():
    _check_allevamento()
    from datetime import datetime, time as dt_time
    from app.models import CalibrazioneGiacenza
    try:
        valore = float(request.form["valore_q"].strip().replace(",", "."))
        data_str = request.form.get("data", str(date.today()))
        ora_str = request.form.get("ora", "").strip()
        if not ora_str:
            raise ValueError("L'ora è obbligatoria.")
        h, m = ora_str.split(":")
        timestamp = datetime.combine(date.fromisoformat(data_str), dt_time(int(h), int(m)))
        operatore = request.form.get("operatore", "").strip() or None
        note = request.form.get("note", "").strip() or None

        db.session.add(CalibrazioneGiacenza(
            tipo="mangime", valore_q=valore, timestamp=timestamp,
            operatore=operatore, note=note,
        ))
        db.session.commit()
        flash(f"Giacenza mangime ricalibrata a {valore} q.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="mangime"))


@bp.route("/consegne/siero/new", methods=["POST"])
@login_required
def consegne_siero_new():
    _check_allevamento()
    from app.models import ConsegnaSiero
    from app.services.allevamento_scorte import chiudi_consegne_siero_precedenti
    ciclo = _get_ciclo_attivo()
    ajax = request.headers.get("X-Requested-With") == "fetch"
    if not ciclo:
        if ajax:
            return jsonify(error="Nessun ciclo attivo."), 400
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.consegne", tab="siero"))
    try:
        from datetime import time as dt_time
        data_str = request.form.get("data", str(date.today()))
        ora_str = request.form.get("ora", "").strip()
        if not ora_str:
            raise ValueError("L'ora della consegna è obbligatoria: serve per chiudere con precisione il carico precedente.")
        ora = dt_time.fromisoformat(ora_str)
        qty = float(request.form["quantita_qli"])
        ss = request.form.get("perc_sostanza_secca", "").strip()
        data_consegna = date.fromisoformat(data_str)
        c = ConsegnaSiero(
            ciclo_id=ciclo.id, data=data_consegna, ora=ora,
            quantita_qli=qty,
            perc_sostanza_secca=float(ss) if ss else None,
            lotto=request.form.get("lotto", "").strip() or None,
            speditore=request.form.get("speditore", "").strip() or None,
            trasportatore=request.form.get("trasportatore", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
            bolla_path=_salva_bolla(request.files.get("bolla")),
        )
        db.session.add(c)
        # La cisterna viene sempre svuotata prima del carico: chiude il periodo precedente.
        chiudi_consegne_siero_precedenti(data_consegna, ora)
        db.session.commit()
        if ajax:
            return jsonify(id=c.id, redirect=url_for("allevamento.consegne", tab="siero"))
        flash(f"Consegna siero registrata: {qty} qli.", "success")
    except Exception as e:
        db.session.rollback()
        if ajax:
            return jsonify(error=str(e)), 400
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="siero"))


@bp.route("/consegne/siero/<int:cid>/bolla", methods=["POST"])
@login_required
def consegne_siero_bolla(cid):
    _check_allevamento()
    from app.models import ConsegnaSiero
    c = db.session.get(ConsegnaSiero, cid)
    if not c:
        return jsonify(error="Consegna non trovata."), 404
    path = _salva_bolla(request.files.get("bolla"))
    if not path:
        return jsonify(error="File non valido (usa jpg, png, webp o pdf)."), 400
    _elimina_bolla(c.bolla_path)
    c.bolla_path = path
    db.session.commit()
    return jsonify(ok=True, path=path)


@bp.route("/consegne/siero/<int:cid>/delete", methods=["POST"])
@login_required
def consegne_siero_delete(cid):
    _check_allevamento()
    from app.models import ConsegnaSiero
    c = db.session.get(ConsegnaSiero, cid)
    if c:
        _elimina_bolla(c.bolla_path)
        db.session.delete(c)
        db.session.commit()
        flash("Consegna siero eliminata.", "success")
    return redirect(url_for("allevamento.consegne", tab="siero"))


@bp.route("/consegne/siero/<int:cid>/chiudi", methods=["POST"])
@login_required
def consegne_siero_chiudi(cid):
    _check_allevamento()
    from app.models import ConsegnaSiero
    c = db.session.get(ConsegnaSiero, cid)
    if not c:
        flash("Consegna non trovata.", "danger")
        return redirect(url_for("allevamento.consegne", tab="siero"))
    try:
        from datetime import datetime, time as dt_time
        data_str = request.form.get("data_esaurimento", str(date.today()))
        ora_str = request.form.get("ora_esaurimento", "").strip()
        c.data_esaurimento = date.fromisoformat(data_str)
        c.ora_esaurimento = dt_time.fromisoformat(ora_str) if ora_str else datetime.now().time().replace(microsecond=0)
        db.session.commit()
        flash("Cisterna segnata come vuota.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="siero"))


@bp.route("/consegne/mangime/new", methods=["POST"])
@login_required
def consegne_mangime_new():
    _check_allevamento()
    from app.models import ConsegnaMangime
    ciclo = _get_ciclo_attivo()
    ajax = request.headers.get("X-Requested-With") == "fetch"
    if not ciclo:
        if ajax:
            return jsonify(error="Nessun ciclo attivo."), 400
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.consegne", tab="mangime"))
    try:
        from datetime import time as dt_time
        data_str = request.form.get("data", str(date.today()))
        ora_str = request.form.get("ora", "").strip()
        if not ora_str:
            raise ValueError("L'ora della consegna è obbligatoria.")
        ora = dt_time.fromisoformat(ora_str)
        qty = float(request.form["quantita_qli"])
        c = ConsegnaMangime(
            ciclo_id=ciclo.id, data=date.fromisoformat(data_str), ora=ora,
            quantita_qli=qty,
            tipo_mangime=request.form.get("tipo_mangime", "").strip() or None,
            numero_bolla=request.form.get("numero_bolla", "").strip() or None,
            fornitore=request.form.get("fornitore", "").strip() or None,
            note=request.form.get("note", "").strip() or None,
            bolla_path=_salva_bolla(request.files.get("bolla")),
        )
        db.session.add(c)
        db.session.commit()
        if ajax:
            return jsonify(id=c.id, redirect=url_for("allevamento.consegne", tab="mangime"))
        flash(f"Consegna mangime registrata: {qty} qli.", "success")
    except Exception as e:
        db.session.rollback()
        if ajax:
            return jsonify(error=str(e)), 400
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="mangime"))


@bp.route("/consegne/mangime/<int:cid>/edit", methods=["POST"])
@login_required
def consegne_mangime_edit(cid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from datetime import time as dt_time
    from app.models import ConsegnaMangime
    c = db.session.get(ConsegnaMangime, cid)
    if not c:
        flash("Consegna non trovata.", "danger")
        return redirect(url_for("allevamento.consegne", tab="mangime"))
    try:
        data_str = request.form.get("data", "").strip()
        ora_str = request.form.get("ora", "").strip()
        if not data_str or not ora_str:
            raise ValueError("Data e ora sono obbligatorie.")
        c.data = date.fromisoformat(data_str)
        c.ora = dt_time.fromisoformat(ora_str)
        c.quantita_qli = float(request.form["quantita_qli"])
        c.tipo_mangime = request.form.get("tipo_mangime", "").strip() or None
        c.numero_bolla = request.form.get("numero_bolla", "").strip() or None
        c.fornitore = request.form.get("fornitore", "").strip() or None
        c.note = request.form.get("note", "").strip() or None
        db.session.commit()
        flash("Consegna mangime aggiornata.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.consegne", tab="mangime"))


@bp.route("/consegne/mangime/<int:cid>/bolla", methods=["POST"])
@login_required
def consegne_mangime_bolla(cid):
    _check_allevamento()
    from app.models import ConsegnaMangime
    c = db.session.get(ConsegnaMangime, cid)
    if not c:
        return jsonify(error="Consegna non trovata."), 404
    path = _salva_bolla(request.files.get("bolla"))
    if not path:
        return jsonify(error="File non valido (usa jpg, png, webp o pdf)."), 400
    _elimina_bolla(c.bolla_path)
    c.bolla_path = path
    db.session.commit()
    return jsonify(ok=True, path=path)


@bp.route("/consegne/mangime/<int:cid>/delete", methods=["POST"])
@login_required
def consegne_mangime_delete(cid):
    _check_allevamento()
    from app.models import ConsegnaMangime
    c = db.session.get(ConsegnaMangime, cid)
    if c:
        _elimina_bolla(c.bolla_path)
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

    from app.services.allevamento_scorte import pasto_avvenuto
    avvenuto = {pasto: pasto_avvenuto(data_sel, pasto) for pasto in [1, 2, 3]}

    pasti = {}
    if ciclo:
        for p in UsoPasto.query.filter_by(ciclo_id=ciclo.id, data=data_sel).all():
            pasti[(p.pasto, p.linea)] = p

    # Totali giornalieri per linea
    totali = {linea: {"mangime": 0, "siero": 0, "acqua": 0} for linea in [1, 2, 3]}
    for (pasto, linea), p in pasti.items():
        totali[linea]["mangime"] += p.mangime_qli or 0
        totali[linea]["siero"] += p.siero_qli or 0
        totali[linea]["acqua"] += p.acqua_qli or 0

    # Totali per pasto (somma delle 3 linee) e totale giornaliero complessivo
    totale_per_pasto = {pasto: {"mangime": 0, "siero": 0, "acqua": 0} for pasto in [1, 2, 3]}
    for (pasto, linea), p in pasti.items():
        totale_per_pasto[pasto]["mangime"] += p.mangime_qli or 0
        totale_per_pasto[pasto]["siero"] += p.siero_qli or 0
        totale_per_pasto[pasto]["acqua"] += p.acqua_qli or 0

    totale_giorno = {"mangime": 0, "siero": 0, "acqua": 0}
    for t in totali.values():
        totale_giorno["mangime"] += t["mangime"]
        totale_giorno["siero"] += t["siero"]
        totale_giorno["acqua"] += t["acqua"]

    # Tipo mangime e % sostanza secca siero: dall'ultima consegna, informativi
    tipo_mangime_attuale = None
    perc_ss_siero_attuale = None
    perc_sostituzione = {linea: None for linea in [1, 2, 3]}
    if ciclo:
        from app.services.allevamento_pasti import (
            ultimo_tipo_mangime, ultima_perc_sostanza_secca_siero, calcola_perc_siero,
        )
        tipo_mangime_attuale = ultimo_tipo_mangime(ciclo.id)
        perc_ss_siero_attuale = ultima_perc_sostanza_secca_siero(ciclo.id)
        for linea in [1, 2, 3]:
            perc_sostituzione[linea] = calcola_perc_siero(
                totali[linea]["mangime"], totali[linea]["siero"], perc_ss_siero_attuale
            )

    return render_template("allevamento/alimentazione.html",
                           ciclo=ciclo, data_sel=data_sel, pasti=pasti, avvenuto=avvenuto,
                           totali=totali, tipo_mangime_attuale=tipo_mangime_attuale,
                           perc_ss_siero_attuale=perc_ss_siero_attuale,
                           perc_sostituzione=perc_sostituzione,
                           totale_per_pasto=totale_per_pasto, totale_giorno=totale_giorno)


@bp.route("/alimentazione/new", methods=["POST"])
@login_required
def alimentazione_new():
    _check_allevamento()
    from app.services.allevamento_pasti import registra_pasto
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.alimentazione"))

    try:
        data_str = request.form.get("data", str(date.today()))
        data_pasto = date.fromisoformat(data_str)

        for linea in [1, 2, 3]:
            for pasto in [1, 2, 3]:
                if request.form.get(f"touched_{pasto}_{linea}") != "1":
                    continue  # cella non modificata dall'utente: resta una stima aggiornabile

                mang = request.form.get(f"mang_{pasto}_{linea}", "").strip()
                siero = request.form.get(f"siero_{pasto}_{linea}", "").strip()
                acqua = request.form.get(f"acqua_{pasto}_{linea}", "").strip()

                registra_pasto(
                    ciclo_id=ciclo.id, data=data_pasto, pasto=pasto, linea=linea,
                    mangime_qli=float(mang) if mang else None,
                    siero_qli=float(siero) if siero else None,
                    acqua_qli=float(acqua) if acqua else None,
                )

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


# ── Trattamenti ────────────────────────────────────────────────────────────

def _stato_trattamento(t):
    """Progresso di un corso di cura: quante dosi fatte, se ne manca una da
    fare oggi (è passato almeno un giorno dall'ultima), e — a corso finito —
    fino a quando resta in sospensione prima del macello."""
    somm = t.somministrazioni.all()  # già ordinate per numero_giorno (vedi relationship)
    fatte = len(somm)
    ultima = somm[-1] if somm else None
    completo = fatte >= t.giorni_somministrazione or t.chiuso_anticipatamente
    oggi = date.today()
    da_ripetere = (not completo) and ultima is not None and oggi > ultima.data
    data_fine_sospensione = None
    if completo and ultima:
        data_fine_sospensione = ultima.data + timedelta(days=t.giorni_sospensione)
    dose_capo_ml = None
    dose_totale_ml = None
    if t.ml_per_kg and t.peso_medio_kg:
        dose_capo_ml = t.ml_per_kg * t.peso_medio_kg
        dose_totale_ml = dose_capo_ml * t.numero_animali
    return {
        "fatte": fatte,
        "totali": t.giorni_somministrazione,
        "completo": completo,
        "chiuso_anticipatamente": t.chiuso_anticipatamente,
        "da_ripetere": da_ripetere,
        "ultima_data": ultima.data if ultima else None,
        "prossima_data": (ultima.data + timedelta(days=1)) if ultima and not completo else None,
        "data_fine_sospensione": data_fine_sospensione,
        "in_sospensione": bool(data_fine_sospensione and oggi < data_fine_sospensione),
        "dose_capo_ml": dose_capo_ml,
        "dose_totale_ml": dose_totale_ml,
    }


@bp.route("/box/<int:box_numero>/ultimo-peso")
@login_required
def box_ultimo_peso(box_numero):
    _check_allevamento()
    from app.models import Censimento, CensimentoBox
    ciclo = _get_ciclo_attivo()
    peso = None
    if ciclo:
        riga = (
            CensimentoBox.query.join(Censimento)
            .filter(
                Censimento.ciclo_id == ciclo.id,
                CensimentoBox.box_numero == box_numero,
                CensimentoBox.peso_stimato_kg.isnot(None),
            )
            .order_by(Censimento.data.desc(), Censimento.id.desc())
            .first()
        )
        peso = riga.peso_stimato_kg if riga else None
    return jsonify(peso_stimato_kg=peso)


@bp.route("/trattamenti")
@login_required
def trattamenti():
    _check_allevamento()
    from app.models import Trattamento, Medicinale
    ciclo = _get_ciclo_attivo()

    lista = Trattamento.query.filter_by(
        ciclo_id=ciclo.id if ciclo else -1
    ).order_by(Trattamento.data_inizio.desc(), Trattamento.id.desc()).all() if ciclo else []

    stati = {t.id: _stato_trattamento(t) for t in lista}
    medicinali = Medicinale.query.filter_by(attivo=True).order_by(Medicinale.nome).all()

    return render_template("allevamento/trattamenti.html",
                           ciclo=ciclo, lista=lista, stati=stati, medicinali=medicinali,
                           BOX_PER_CAP=BOX_PER_CAP, CAPANNONI=CAPANNONI,
                           oggi=date.today())


@bp.route("/trattamenti/new", methods=["POST"])
@login_required
def trattamenti_new():
    _check_allevamento()
    from app.models import Trattamento, Somministrazione, Medicinale
    ciclo = _get_ciclo_attivo()
    if not ciclo:
        flash("Nessun ciclo attivo.", "danger")
        return redirect(url_for("allevamento.trattamenti"))

    try:
        medicinale_id = int(request.form["medicinale_id"])
        medicinale = db.session.get(Medicinale, medicinale_id)
        if not medicinale:
            raise ValueError("Medicinale non valido.")

        box = request.form.get("box_numero", "").strip()
        cap = request.form.get("capannone_numero", "").strip()
        if not box and not cap:
            raise ValueError("Seleziona un box o un capannone.")

        data_str = request.form.get("data_inizio", str(date.today()))
        data_inizio = date.fromisoformat(data_str)
        qty = int(request.form["numero_animali"])
        operatore = request.form.get("operatore", "").strip() or None
        note = request.form.get("note", "").strip() or None

        ml_val = request.form.get("ml_per_kg", "").strip()
        ml_per_kg = float(ml_val.replace(",", ".")) if ml_val else medicinale.ml_per_kg
        giorni_somm = int(request.form.get("giorni_somministrazione") or medicinale.giorni_somministrazione)
        giorni_sosp = int(request.form.get("giorni_sospensione") or medicinale.giorni_sospensione)
        peso_val = request.form.get("peso_medio_kg", "").strip()
        peso_medio_kg = float(peso_val.replace(",", ".")) if peso_val else None

        t = Trattamento(
            ciclo_id=ciclo.id, medicinale_id=medicinale.id,
            box_numero=int(box) if box else None,
            capannone_numero=int(cap) if cap else None,
            numero_animali=qty, peso_medio_kg=peso_medio_kg, data_inizio=data_inizio,
            operatore=operatore, note=note,
            ml_per_kg=ml_per_kg, giorni_somministrazione=giorni_somm, giorni_sospensione=giorni_sosp,
        )
        db.session.add(t)
        db.session.flush()
        db.session.add(Somministrazione(trattamento_id=t.id, numero_giorno=1, data=data_inizio))
        db.session.commit()
        flash(f"Trattamento registrato: {medicinale.nome}, {qty} capi.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")

    return redirect(url_for("allevamento.trattamenti"))


@bp.route("/trattamenti/<int:tid>/somministra", methods=["POST"])
@login_required
def trattamenti_somministra(tid):
    _check_allevamento()
    from app.models import Trattamento, Somministrazione
    t = db.session.get(Trattamento, tid)
    if not t:
        flash("Trattamento non trovato.", "danger")
        return redirect(url_for("allevamento.trattamenti"))

    stato = _stato_trattamento(t)
    if stato["completo"]:
        flash("Il corso di cura è già completo.", "warning")
        return redirect(url_for("allevamento.trattamenti"))

    db.session.add(Somministrazione(
        trattamento_id=t.id, numero_giorno=stato["fatte"] + 1, data=date.today(),
    ))
    db.session.commit()
    flash(f"Somministrazione {stato['fatte'] + 1}/{stato['totali']} registrata.", "success")
    return redirect(url_for("allevamento.trattamenti"))


@bp.route("/trattamenti/<int:tid>/chiudi", methods=["POST"])
@login_required
def trattamenti_chiudi(tid):
    _check_allevamento()
    from app.models import Trattamento
    t = db.session.get(Trattamento, tid)
    if not t:
        flash("Trattamento non trovato.", "danger")
        return redirect(url_for("allevamento.trattamenti"))

    stato = _stato_trattamento(t)
    if stato["completo"]:
        flash("Il corso di cura è già completo.", "warning")
        return redirect(url_for("allevamento.trattamenti"))

    motivo = request.form.get("motivo", "").strip()
    riga = f"Chiuso anticipatamente il {date.today().strftime('%d/%m/%Y')}"
    if motivo:
        riga += f": {motivo}"
    t.note = f"{t.note}\n\n{riga}" if t.note else riga
    t.chiuso_anticipatamente = True
    db.session.commit()
    flash("Trattamento chiuso.", "success")
    return redirect(url_for("allevamento.trattamenti"))


@bp.route("/trattamenti/<int:tid>/delete", methods=["POST"])
@login_required
def trattamenti_delete(tid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Trattamento
    t = db.session.get(Trattamento, tid)
    if t:
        db.session.delete(t)
        db.session.commit()
        flash("Trattamento eliminato.", "success")
    return redirect(url_for("allevamento.trattamenti"))


# ── Medicinali (Impostazioni) ──────────────────────────────────────────────

@bp.route("/medicinali/new", methods=["POST"])
@login_required
def medicinali_new():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Medicinale
    try:
        nome = request.form["nome"].strip()
        if not nome:
            raise ValueError("Il nome è obbligatorio.")
        tipo = request.form.get("tipo", "iniettabile").strip() or "iniettabile"
        ml_val = request.form.get("ml_per_kg", "").strip()
        db.session.add(Medicinale(
            nome=nome, tipo=tipo,
            ml_per_kg=float(ml_val.replace(",", ".")) if ml_val else None,
            giorni_somministrazione=int(request.form.get("giorni_somministrazione") or 1),
            giorni_sospensione=int(request.form.get("giorni_sospensione") or 0),
        ))
        db.session.commit()
        flash(f"Medicinale '{nome}' aggiunto.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))


@bp.route("/medicinali/<int:mid>/edit", methods=["POST"])
@login_required
def medicinali_edit(mid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Medicinale
    m = db.session.get(Medicinale, mid)
    if not m:
        flash("Medicinale non trovato.", "danger")
        return redirect(url_for("allevamento.impostazioni"))
    try:
        ml_val = request.form.get("ml_per_kg", "").strip()
        m.ml_per_kg = float(ml_val.replace(",", ".")) if ml_val else None
        m.giorni_somministrazione = int(request.form.get("giorni_somministrazione") or 1)
        m.giorni_sospensione = int(request.form.get("giorni_sospensione") or 0)
        db.session.commit()
        flash(f"Medicinale '{m.nome}' aggiornato.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))


@bp.route("/medicinali/<int:mid>/delete", methods=["POST"])
@login_required
def medicinali_delete(mid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Medicinale
    m = db.session.get(Medicinale, mid)
    if m:
        m.attivo = False
        db.session.commit()
        flash(f"Medicinale '{m.nome}' disattivato.", "success")
    return redirect(url_for("allevamento.impostazioni"))


# ── Curva di accrescimento (Impostazioni) ──────────────────────────────────

@bp.route("/curva-accrescimento/new", methods=["POST"])
@login_required
def curva_new():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import CurvaAccrescimento
    try:
        eta = int(request.form["eta_giorni"])
        peso = float(request.form["peso_kg"].strip().replace(",", "."))
        if CurvaAccrescimento.query.filter_by(eta_giorni=eta).first():
            raise ValueError(f"Esiste già un punto a {eta} giorni.")
        db.session.add(CurvaAccrescimento(eta_giorni=eta, peso_kg=peso))
        db.session.commit()
        flash(f"Punto {eta}gg → {peso}kg aggiunto.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))


@bp.route("/curva-accrescimento/<int:cid>/edit", methods=["POST"])
@login_required
def curva_edit(cid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import CurvaAccrescimento
    c = db.session.get(CurvaAccrescimento, cid)
    if not c:
        flash("Punto non trovato.", "danger")
        return redirect(url_for("allevamento.impostazioni"))
    try:
        c.peso_kg = float(request.form["peso_kg"].strip().replace(",", "."))
        db.session.commit()
        flash(f"Punto {c.eta_giorni}gg aggiornato.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))


@bp.route("/curva-accrescimento/<int:cid>/delete", methods=["POST"])
@login_required
def curva_delete(cid):
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import CurvaAccrescimento
    c = db.session.get(CurvaAccrescimento, cid)
    if c:
        db.session.delete(c)
        db.session.commit()
        flash(f"Punto {c.eta_giorni}gg eliminato.", "success")
    return redirect(url_for("allevamento.impostazioni"))


# ── Impostazioni / Cicli ───────────────────────────────────────────────────

@bp.route("/impostazioni")
@login_required
def impostazioni():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.models import Ciclo, Medicinale, CurvaAccrescimento
    from app.services.allevamento_scorte import get_setting_float, get_setting_int, orario_pasto_str
    ciclo_attivo = _get_ciclo_attivo()
    cicli_precedenti = Ciclo.query.filter_by(attivo=False).order_by(Ciclo.data_inizio.desc()).all()
    medicinali = Medicinale.query.filter_by(attivo=True).order_by(Medicinale.nome).all()
    curva_accrescimento = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    soglia_mangime_pasti = get_setting_int("allevamento_soglia_mangime_pasti") or 0
    soglia_mangime_giorni, soglia_mangime_pasti_extra = divmod(soglia_mangime_pasti, 3)
    scorte_settings = {
        "capacita_mangime_q": get_setting_float("allevamento_capacita_mangime_q"),
        "soglia_mangime_giorni": soglia_mangime_giorni,
        "soglia_mangime_pasti_extra": soglia_mangime_pasti_extra,
        "ordine_mangime_q": get_setting_float("allevamento_ordine_mangime_q"),
        "soglia_scarto_siero_q": get_setting_float("allevamento_soglia_scarto_siero_q"),
        "orario_pasto_1": orario_pasto_str(1),
        "orario_pasto_2": orario_pasto_str(2),
        "orario_pasto_3": orario_pasto_str(3),
    }
    return render_template("allevamento/impostazioni.html",
                           ciclo_attivo=ciclo_attivo, cicli_precedenti=cicli_precedenti,
                           scorte_settings=scorte_settings, medicinali=medicinali,
                           curva_accrescimento=curva_accrescimento,
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


@bp.route("/impostazioni/scorte", methods=["POST"])
@login_required
def impostazioni_scorte():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)
    from app.services.allevamento_scorte import set_setting
    campi_numerici = [
        "allevamento_capacita_mangime_q", "allevamento_soglia_scarto_siero_q",
        "allevamento_ordine_mangime_q",
    ]
    campi_orario = [
        "allevamento_orario_pasto_1", "allevamento_orario_pasto_2", "allevamento_orario_pasto_3",
    ]
    try:
        for campo in campi_numerici:
            valore = request.form.get(campo, "").strip()
            if valore:
                set_setting(campo, float(valore))
        for campo in campi_orario:
            valore = request.form.get(campo, "").strip()
            if valore:
                set_setting(campo, valore)

        giorni = int(request.form.get("soglia_mangime_giorni", "0").strip() or 0)
        pasti_extra = int(request.form.get("soglia_mangime_pasti_extra", "0").strip() or 0)
        set_setting("allevamento_soglia_mangime_pasti", giorni * 3 + pasti_extra)

        db.session.commit()
        flash("Impostazioni scorte salvate.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni"))
