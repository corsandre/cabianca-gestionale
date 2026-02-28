"""Routes per la sezione Allevamento Suini – Ca Bianca Gestionale."""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (
    Allarme, Box, BoxCiclo, Capannone, ConsegnaAlimentare, CurvaAccrescimento,
    EventoCiclo, InappetenzaBox, LottoProduttivo, MagazzinoProdotto,
    ManutenzioneBox, OrdineAlimentare, RazioneGiornaliera, Setting,
    TabellaSostSiero, TrattamentoSanitario, User,
)
from app.utils.decorators import section_required, write_required

bp = Blueprint("allevamento", __name__, url_prefix="/allevamento")
bp.before_request(section_required("allevamento"))


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────

def _admin_required():
    if current_user.role != "admin":
        flash("Accesso riservato agli amministratori.", "danger")
        return redirect(url_for("allevamento.index"))
    return None


def _eta_da_peso(peso_kg):
    """Interpola la curva di accrescimento per stimare l'età in giorni da un peso."""
    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    if not curva:
        return None
    if peso_kg <= curva[0].peso_kg:
        return curva[0].eta_giorni
    if peso_kg >= curva[-1].peso_kg:
        return curva[-1].eta_giorni
    for i in range(len(curva) - 1):
        a, b = curva[i], curva[i + 1]
        if a.peso_kg <= peso_kg <= b.peso_kg:
            ratio = (peso_kg - a.peso_kg) / (b.peso_kg - a.peso_kg)
            return int(a.eta_giorni + ratio * (b.eta_giorni - a.eta_giorni))
    return None


def _razione_da_eta(eta_gg):
    """Razione giornaliera (kg/capo) interpolata dalla curva di accrescimento."""
    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    if not curva:
        return 0.0
    if eta_gg <= curva[0].eta_giorni:
        return curva[0].razione_kg_giorno
    if eta_gg >= curva[-1].eta_giorni:
        return curva[-1].razione_kg_giorno
    for i in range(len(curva) - 1):
        a, b = curva[i], curva[i + 1]
        if a.eta_giorni <= eta_gg <= b.eta_giorni:
            ratio = (eta_gg - a.eta_giorni) / (b.eta_giorni - a.eta_giorni)
            return a.razione_kg_giorno + ratio * (b.razione_kg_giorno - a.razione_kg_giorno)
    return 0.0


def _perc_siero_da_eta(eta_gg):
    """Percentuale di sostituzione siero per un'età data."""
    tabella = TabellaSostSiero.query.filter(
        TabellaSostSiero.eta_min <= eta_gg,
        TabellaSostSiero.eta_max >= eta_gg,
    ).first()
    return tabella.percentuale_siero if tabella else 0.0


def _calcola_razioni_linea(linea):
    """Calcola razione teorica totale per una linea (kg mangime + litri siero)."""
    oggi = date.today()
    # Box attivi sulla linea
    boxes_linea = Box.query.filter_by(linea_alimentazione=linea).all()
    box_ids = [b.id for b in boxes_linea]
    cicli_attivi = BoxCiclo.query.filter(
        BoxCiclo.box_id.in_(box_ids),
        BoxCiclo.stato.in_(["attivo", "in_uscita"]),
    ).all()

    totale_mangime_kg = 0.0
    totale_siero_litri = 0.0

    for bc in cicli_attivi:
        if not bc.eta_stimata_gg or not bc.data_accasamento or not bc.capi_presenti:
            continue
        eta_oggi = bc.eta_stimata_gg + (oggi - bc.data_accasamento).days
        razione_base = _razione_da_eta(eta_oggi)

        # Riduzione per inappetenza attiva
        inapp = bc.inappetenze.filter(
            InappetenzaBox.data_inizio <= oggi,
            db.or_(InappetenzaBox.data_fine == None, InappetenzaBox.data_fine >= oggi),
        ).first()
        perc_razione = (inapp.percentuale_razione / 100.0) if inapp else 1.0

        razione_box = razione_base * bc.capi_presenti * perc_razione  # kg totale box

        # Sostituzione siero
        perc_s = _perc_siero_da_eta(eta_oggi) / 100.0
        ss_perc = _get_setting_float("allevamento_perc_ss_siero", 6.0) / 100.0

        siero_ss_kg = razione_box * perc_s  # kg sostanza secca da siero
        siero_litri = (siero_ss_kg / ss_perc) if ss_perc > 0 else 0.0
        mangime_kg = razione_box - siero_ss_kg

        totale_mangime_kg += mangime_kg
        totale_siero_litri += siero_litri

    return round(totale_mangime_kg, 1), round(totale_siero_litri, 1)


def _get_setting_float(key, default):
    s = Setting.query.get(key)
    try:
        return float(s.value) if s else default
    except (TypeError, ValueError):
        return default


def _genera_lotto_id():
    anno = date.today().year % 100
    count = LottoProduttivo.query.count() + 1
    data_str = date.today().strftime("%Y%m%d")
    return f"CICLO{anno:02d}-{count:02d}-{data_str}"


def _box_state(box, active_alarms_bc_ids):
    """Restituisce stato box per la mappa SVG."""
    ciclo = box.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
    if ciclo is None:
        return "libero", 0, None, None
    if ciclo.id in active_alarms_bc_ids:
        stato = "allarme"
    elif ciclo.stato == "in_uscita":
        stato = "in_attesa"
    else:
        stato = f"linea{box.linea_alimentazione}"
    return stato, ciclo.capi_presenti or 0, ciclo.id, ciclo.lotto.lotto_id


def _allarmi_attivi_count():
    now = datetime.utcnow()
    return Allarme.query.filter(
        Allarme.stato == "attivo",
        db.or_(Allarme.silenziato_fino == None, Allarme.silenziato_fino < now),
    ).count()


# ─────────────────────────────────────────────────────────────────────────────
# FASE 1 — PANORAMICA (Mappa SVG)
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/")
@login_required
def index():
    boxes = Box.query.order_by(Box.numero).all()
    capannoni = Capannone.query.order_by(Capannone.numero).all()

    # Allarmi attivi collegati a box_cicli
    active_alarms_bc_ids = {
        a.riferimento_id for a in Allarme.query.filter_by(stato="attivo", riferimento_tipo="box_ciclo").all()
    }

    box_data = {}
    for b in boxes:
        stato, capi, ciclo_id, lotto_codice = _box_state(b, active_alarms_bc_ids)
        box_data[b.numero] = {
            "stato": stato,
            "capi": capi,
            "ciclo_id": ciclo_id,
            "lotto_id": lotto_codice,
            "linea": b.linea_alimentazione,
            "capannone": b.capannone.nome,
            "superficie": b.superficie_m2,
        }

    allarmi_count = _allarmi_attivi_count()
    return render_template("allevamento/index.html",
                           boxes=boxes, box_data=box_data,
                           capannoni=capannoni, allarmi_count=allarmi_count)


@bp.route("/box/<int:id>/modal")
@login_required
def box_modal(id):
    """API JSON per il modal del box sulla mappa."""
    box = Box.query.get_or_404(id)
    ciclo = box.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
    data = {
        "numero": box.numero,
        "capannone": box.capannone.nome,
        "linea": box.linea_alimentazione,
        "superficie": box.superficie_m2,
        "ciclo": None,
    }
    if ciclo:
        oggi = date.today()
        eta_oggi = None
        if ciclo.eta_stimata_gg and ciclo.data_accasamento:
            eta_oggi = ciclo.eta_stimata_gg + (oggi - ciclo.data_accasamento).days
        data["ciclo"] = {
            "id": ciclo.id,
            "lotto_id": ciclo.lotto.lotto_id,
            "data_accasamento": ciclo.data_accasamento.strftime("%d/%m/%Y"),
            "capi_iniziali": ciclo.capi_iniziali,
            "capi_presenti": ciclo.capi_presenti,
            "peso_medio_iniziale": ciclo.peso_medio_iniziale,
            "eta_oggi": eta_oggi,
            "stato": ciclo.stato,
        }
    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
# FASE 2 — CICLI PRODUTTIVI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/lotti/")
@login_required
def lotti_index():
    stato_filter = request.args.get("stato", "attivo")
    q = LottoProduttivo.query
    if stato_filter != "tutti":
        q = q.filter_by(stato=stato_filter)
    lotti = q.order_by(LottoProduttivo.data_inizio.desc()).all()
    return render_template("allevamento/lotti/index.html", lotti=lotti, stato_filter=stato_filter)


@bp.route("/lotti/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def lotti_nuovo():
    boxes = Box.query.order_by(Box.numero).all()
    # Prefiltra box liberi (senza ciclo attivo)
    boxes_liberi = [
        b for b in boxes
        if not b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
    ]

    if request.method == "POST":
        box_ids_raw = request.form.getlist("box_ids")
        data_arrivo_str = request.form.get("data_arrivo", str(date.today()))
        capi_totali = int(request.form.get("capi_totali", 0))
        peso_totale_bolla = float(request.form.get("peso_totale_bolla", 0) or 0)
        note = request.form.get("note", "").strip()

        if not box_ids_raw:
            flash("Seleziona almeno un box.", "danger")
            return render_template("allevamento/lotti/nuovo.html",
                                   boxes_liberi=boxes_liberi, today=date.today())

        box_ids = [int(x) for x in box_ids_raw]
        data_arrivo = date.fromisoformat(data_arrivo_str)

        # Calcolo peso medio e età stimata
        peso_medio = (peso_totale_bolla / capi_totali) if capi_totali > 0 else 0.0
        eta_stimata = _eta_da_peso(peso_medio) if peso_medio > 0 else None

        # Distribuzione capi tra i box
        n_boxes = len(box_ids)
        capi_base = capi_totali // n_boxes
        extra = capi_totali % n_boxes

        lotto = LottoProduttivo(
            lotto_id=_genera_lotto_id(),
            numero_ciclo=LottoProduttivo.query.count() + 1,
            data_inizio=data_arrivo,
            stato="attivo",
            note=note,
            created_by=current_user.id,
        )
        db.session.add(lotto)
        db.session.flush()

        for i, bid in enumerate(box_ids):
            capi_box = capi_base + (1 if i < extra else 0)
            peso_box = (peso_totale_bolla / capi_totali * capi_box) if capi_totali else 0
            bc = BoxCiclo(
                lotto_id=lotto.id,
                box_id=bid,
                data_accasamento=data_arrivo,
                capi_iniziali=capi_box,
                peso_totale_iniziale=round(peso_box, 1),
                peso_medio_iniziale=round(peso_medio, 2),
                eta_stimata_gg=eta_stimata,
                capi_presenti=capi_box,
                stato="attivo",
            )
            db.session.add(bc)

        db.session.commit()
        flash(f"Lotto {lotto.lotto_id} creato con {capi_totali} capi in {n_boxes} box.", "success")
        return redirect(url_for("allevamento.lotti_detail", id=lotto.id))

    return render_template("allevamento/lotti/nuovo.html",
                           boxes_liberi=boxes_liberi, today=date.today())


@bp.route("/lotti/<int:id>")
@login_required
def lotti_detail(id):
    lotto = LottoProduttivo.query.get_or_404(id)
    box_cicli = lotto.box_cicli.all()
    # Tutti gli eventi per questo lotto, ordinati per data desc
    bc_ids = [bc.id for bc in box_cicli]
    eventi = EventoCiclo.query.filter(
        EventoCiclo.box_ciclo_id.in_(bc_ids)
    ).order_by(EventoCiclo.data.desc()).all() if bc_ids else []
    return render_template("allevamento/lotti/detail.html",
                           lotto=lotto, box_cicli=box_cicli, eventi=eventi)


@bp.route("/lotti/<int:id>/chiudi", methods=["POST"])
@login_required
@write_required
def lotti_chiudi(id):
    lotto = LottoProduttivo.query.get_or_404(id)
    if lotto.stato == "chiuso":
        flash("Lotto già chiuso.", "warning")
        return redirect(url_for("allevamento.lotti_detail", id=id))
    lotto.stato = "chiuso"
    lotto.data_chiusura = date.today()
    for bc in lotto.box_cicli.all():
        bc.stato = "chiuso"
    db.session.commit()
    flash(f"Lotto {lotto.lotto_id} chiuso.", "success")
    return redirect(url_for("allevamento.lotti_index"))


@bp.route("/eventi/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def eventi_nuovo():
    """Registrazione rapida evento: mortalità / frazionamento / uscita macello."""
    cicli_attivi = BoxCiclo.query.filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"])
    ).join(Box).order_by(Box.numero).all()

    if request.method == "POST":
        tipo = request.form.get("tipo")
        box_ciclo_id = int(request.form.get("box_ciclo_id", 0))
        quantita = int(request.form.get("quantita", 0) or 0)
        peso_totale = float(request.form.get("peso_totale", 0) or 0)
        data_str = request.form.get("data", str(date.today()))
        note = request.form.get("note", "").strip()

        bc = BoxCiclo.query.get_or_404(box_ciclo_id)
        ev = EventoCiclo(
            box_ciclo_id=box_ciclo_id,
            tipo=tipo,
            data=date.fromisoformat(data_str),
            quantita=quantita,
            peso_totale=peso_totale if peso_totale else None,
            note=note,
            operatore_id=current_user.id,
        )
        db.session.add(ev)

        if tipo == "mortalita":
            bc.capi_presenti = max(0, (bc.capi_presenti or 0) - quantita)
        elif tipo == "frazionamento_out":
            bc.capi_presenti = max(0, (bc.capi_presenti or 0) - quantita)
            # frazionamento_in va registrato sul box destinazione separatamente
            dest_bc_id = int(request.form.get("dest_box_ciclo_id", 0) or 0)
            if dest_bc_id:
                dest_bc = BoxCiclo.query.get(dest_bc_id)
                if dest_bc:
                    dest_bc.capi_presenti = (dest_bc.capi_presenti or 0) + quantita
                    db.session.add(EventoCiclo(
                        box_ciclo_id=dest_bc_id,
                        tipo="frazionamento_in",
                        data=date.fromisoformat(data_str),
                        quantita=quantita,
                        note=f"Da box {bc.box.numero} – {note}",
                        operatore_id=current_user.id,
                    ))
        elif tipo == "uscita_macello":
            bc.capi_presenti = max(0, (bc.capi_presenti or 0) - quantita)
            if bc.capi_presenti == 0:
                bc.stato = "chiuso"
                # Controlla se tutto il lotto è chiuso
                lotto = bc.lotto
                if all(b.stato == "chiuso" for b in lotto.box_cicli.all()):
                    lotto.stato = "chiuso"
                    lotto.data_chiusura = date.today()

        db.session.commit()
        flash(f"Evento '{tipo}' registrato ({quantita} capi).", "success")
        return redirect(url_for("allevamento.lotti_detail", id=bc.lotto_id))

    # GET: eventuale preselect da query string
    preselect_bc = request.args.get("bc")
    return render_template("allevamento/eventi/form.html",
                           cicli_attivi=cicli_attivi, preselect_bc=preselect_bc,
                           today=date.today())


# ─────────────────────────────────────────────────────────────────────────────
# FASE 3 — SANITÀ
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/sanita/")
@login_required
def sanita_index():
    oggi = date.today()
    trattamenti_attivi = TrattamentoSanitario.query.join(BoxCiclo).filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"]),
        TrattamentoSanitario.data_inizio <= oggi,
    ).order_by(TrattamentoSanitario.data_inizio.desc()).all()
    # filtra quelli ancora in corso
    trattamenti_oggi = [
        t for t in trattamenti_attivi
        if t.data_inizio + timedelta(days=t.durata_giorni - 1) >= oggi
    ]
    return render_template("allevamento/sanita/index.html",
                           trattamenti_oggi=trattamenti_oggi, today=oggi,
                           timedelta=timedelta)


@bp.route("/sanita/trattamento/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def sanita_trattamento_nuovo():
    cicli_attivi = BoxCiclo.query.filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"])
    ).join(Box).order_by(Box.numero).all()

    if request.method == "POST":
        box_ciclo_id = int(request.form.get("box_ciclo_id", 0))
        t = TrattamentoSanitario(
            box_ciclo_id=box_ciclo_id,
            tipo=request.form.get("tipo", "").strip(),
            farmaco=request.form.get("farmaco", "").strip(),
            via_somministrazione=request.form.get("via", "orale"),
            data_inizio=date.fromisoformat(request.form.get("data_inizio", str(date.today()))),
            durata_giorni=int(request.form.get("durata_giorni", 1) or 1),
            intervallo_ore=int(request.form.get("intervallo_ore", 24) or 24),
            note=request.form.get("note", "").strip(),
            operatore_id=current_user.id,
        )
        db.session.add(t)
        db.session.commit()
        flash("Trattamento registrato.", "success")
        return redirect(url_for("allevamento.sanita_index"))

    preselect_bc = request.args.get("bc")
    return render_template("allevamento/sanita/trattamento_form.html",
                           cicli_attivi=cicli_attivi, preselect_bc=preselect_bc,
                           today=date.today())


@bp.route("/sanita/inappetenza/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def sanita_inappetenza_nuovo():
    cicli_attivi = BoxCiclo.query.filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"])
    ).join(Box).order_by(Box.numero).all()

    if request.method == "POST":
        box_ciclo_id = int(request.form.get("box_ciclo_id", 0))
        perc = float(request.form.get("percentuale_razione", 100) or 100)
        data_inizio_str = request.form.get("data_inizio", str(date.today()))
        data_fine_str = request.form.get("data_fine", "").strip()
        note = request.form.get("note", "").strip()

        inp = InappetenzaBox(
            box_ciclo_id=box_ciclo_id,
            percentuale_razione=perc,
            data_inizio=date.fromisoformat(data_inizio_str),
            data_fine=date.fromisoformat(data_fine_str) if data_fine_str else None,
            note=note,
        )
        db.session.add(inp)
        db.session.commit()
        flash("Inappetenza registrata.", "success")
        return redirect(url_for("allevamento.sanita_index"))

    return render_template("allevamento/sanita/inappetenza_form.html",
                           cicli_attivi=cicli_attivi, today=date.today())


@bp.route("/sanita/storico")
@login_required
def sanita_storico():
    trattamenti = TrattamentoSanitario.query.order_by(
        TrattamentoSanitario.data_inizio.desc()
    ).limit(200).all()
    return render_template("allevamento/sanita/storico.html", trattamenti=trattamenti)


# ─────────────────────────────────────────────────────────────────────────────
# FASE 4 — ALIMENTAZIONE & RAZIONI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/alimentazione/")
@login_required
def alimentazione_index():
    oggi = date.today()
    razioni = {}
    for linea in [1, 2, 3]:
        mangime, siero = _calcola_razioni_linea(linea)
        razione_db = RazioneGiornaliera.query.filter_by(data=oggi, linea=linea).first()
        razioni[linea] = {
            "teorica_mangime": mangime,
            "teorica_siero": siero,
            "consumo_mangime": razione_db.consumo_mangime_kg if razione_db else None,
            "consumo_siero": razione_db.consumo_siero_litri if razione_db else None,
            "note": razione_db.note if razione_db else "",
        }
    return render_template("allevamento/alimentazione/index.html",
                           razioni=razioni, oggi=oggi)


@bp.route("/alimentazione/consumi", methods=["GET", "POST"])
@login_required
@write_required
def alimentazione_consumi():
    oggi = date.today()
    if request.method == "POST":
        data_str = request.form.get("data", str(oggi))
        data_razione = date.fromisoformat(data_str)
        for linea in [1, 2, 3]:
            mangime_s = request.form.get(f"mangime_{linea}", "").strip()
            siero_s = request.form.get(f"siero_{linea}", "").strip()
            note_s = request.form.get(f"note_{linea}", "").strip()
            if not mangime_s and not siero_s:
                continue
            mangime_val = float(mangime_s) if mangime_s else None
            siero_val = float(siero_s) if siero_s else None
            teorica_m, teorica_s = _calcola_razioni_linea(linea)
            razione = RazioneGiornaliera.query.filter_by(data=data_razione, linea=linea).first()
            if razione is None:
                razione = RazioneGiornaliera(data=data_razione, linea=linea)
                db.session.add(razione)
            razione.razione_teorica_kg = teorica_m
            razione.consumo_mangime_kg = mangime_val
            razione.consumo_siero_litri = siero_val
            razione.note = note_s
        db.session.commit()
        flash("Consumi registrati.", "success")
        return redirect(url_for("allevamento.alimentazione_index"))

    # Pre-calcola razioni teoriche per il form
    razioni_teoriche = {}
    for linea in [1, 2, 3]:
        m, s = _calcola_razioni_linea(linea)
        razioni_teoriche[linea] = {"mangime": m, "siero": s}
    return render_template("allevamento/alimentazione/consumi.html",
                           oggi=oggi, razioni_teoriche=razioni_teoriche)


@bp.route("/alimentazione/storico")
@login_required
def alimentazione_storico():
    razioni = RazioneGiornaliera.query.order_by(
        RazioneGiornaliera.data.desc(), RazioneGiornaliera.linea
    ).limit(90).all()
    return render_template("allevamento/alimentazione/storico.html", razioni=razioni)


@bp.route("/alimentazione/impostazioni", methods=["GET", "POST"])
@login_required
def alimentazione_impostazioni():
    redir = _admin_required()
    if redir:
        return redir

    if request.method == "POST":
        azione = request.form.get("azione")
        if azione == "curva":
            # Salva/aggiorna curva accrescimento
            CurvaAccrescimento.query.delete()
            eta_list = request.form.getlist("eta_giorni[]")
            peso_list = request.form.getlist("peso_kg[]")
            razione_list = request.form.getlist("razione_kg[]")
            for eta_s, peso_s, razione_s in zip(eta_list, peso_list, razione_list):
                try:
                    db.session.add(CurvaAccrescimento(
                        eta_giorni=int(eta_s),
                        peso_kg=float(peso_s),
                        razione_kg_giorno=float(razione_s),
                    ))
                except (ValueError, TypeError):
                    continue
            db.session.commit()
            flash("Curva di accrescimento aggiornata.", "success")
        elif azione == "siero_tabella":
            TabellaSostSiero.query.delete()
            eta_min_list = request.form.getlist("eta_min[]")
            eta_max_list = request.form.getlist("eta_max[]")
            perc_list = request.form.getlist("percentuale[]")
            for a, b, p in zip(eta_min_list, eta_max_list, perc_list):
                try:
                    db.session.add(TabellaSostSiero(
                        eta_min=int(a), eta_max=int(b), percentuale_siero=float(p)
                    ))
                except (ValueError, TypeError):
                    continue
            db.session.commit()
            flash("Tabella sostituzione siero aggiornata.", "success")
        elif azione == "parametri_siero":
            perc_ss = request.form.get("perc_ss", "6").strip()
            _set_setting("allevamento_perc_ss_siero", perc_ss)
            db.session.commit()
            flash("Parametri siero aggiornati.", "success")
        return redirect(url_for("allevamento.alimentazione_impostazioni"))

    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    tabella_siero = TabellaSostSiero.query.order_by(TabellaSostSiero.eta_min).all()
    perc_ss = _get_setting_float("allevamento_perc_ss_siero", 6.0)
    return render_template("allevamento/alimentazione/impostazioni.html",
                           curva=curva, tabella_siero=tabella_siero, perc_ss=perc_ss)


def _set_setting(key, value):
    s = Setting.query.get(key)
    if s is None:
        s = Setting(key=key, value=str(value))
        db.session.add(s)
    else:
        s.value = str(value)


# ─────────────────────────────────────────────────────────────────────────────
# FASE 5 — MAGAZZINO & ORDINI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/magazzino/")
@login_required
def magazzino_index():
    prodotti = MagazzinoProdotto.query.all()
    ultime_consegne = ConsegnaAlimentare.query.order_by(
        ConsegnaAlimentare.data.desc()
    ).limit(10).all()
    return render_template("allevamento/magazzino/index.html",
                           prodotti=prodotti, ultime_consegne=ultime_consegne)


@bp.route("/magazzino/consegna/nuova", methods=["GET", "POST"])
@login_required
@write_required
def magazzino_consegna_nuova():
    prodotti = MagazzinoProdotto.query.all()
    if request.method == "POST":
        tipo = request.form.get("tipo")
        quantita = float(request.form.get("quantita_q", 0) or 0)
        data_str = request.form.get("data", str(date.today()))
        fornitore = request.form.get("fornitore", "").strip()
        perc_ss = request.form.get("percentuale_ss", "").strip()
        note = request.form.get("note", "").strip()

        consegna = ConsegnaAlimentare(
            tipo=tipo,
            data=date.fromisoformat(data_str),
            quantita_q=quantita,
            fornitore=fornitore,
            percentuale_ss_siero=float(perc_ss) if perc_ss else None,
            note=note,
            created_by=current_user.id,
        )
        db.session.add(consegna)

        # Aggiorna scorta
        mp = MagazzinoProdotto.query.filter_by(tipo=tipo).first()
        if mp:
            mp.quantita_attuale_q = (mp.quantita_attuale_q or 0) + quantita

        db.session.commit()
        flash(f"Consegna {tipo} registrata: {quantita} q.", "success")
        return redirect(url_for("allevamento.magazzino_index"))

    return render_template("allevamento/magazzino/consegna_form.html",
                           prodotti=prodotti, today=date.today())


@bp.route("/ordini/")
@login_required
def ordini_index():
    ordini = OrdineAlimentare.query.order_by(OrdineAlimentare.data_ordine.desc()).all()
    return render_template("allevamento/ordini/index.html", ordini=ordini)


@bp.route("/ordini/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def ordini_nuovo():
    if request.method == "POST":
        tipo = request.form.get("tipo")
        quantita = float(request.form.get("quantita_q", 0) or 0)
        fornitore = request.form.get("fornitore", "").strip()
        data_str = request.form.get("data_ordine", str(date.today()))
        data_cons_str = request.form.get("data_consegna", "").strip()
        note = request.form.get("note", "").strip()

        ordine = OrdineAlimentare(
            tipo=tipo,
            data_ordine=date.fromisoformat(data_str),
            quantita_q=quantita,
            fornitore=fornitore,
            data_consegna=date.fromisoformat(data_cons_str) if data_cons_str else None,
            note=note,
            created_by=current_user.id,
        )
        db.session.add(ordine)
        db.session.commit()
        flash("Ordine creato.", "success")
        return redirect(url_for("allevamento.ordini_index"))

    return render_template("allevamento/ordini/form.html", today=date.today())


@bp.route("/ordini/<int:id>/stato", methods=["POST"])
@login_required
@write_required
def ordini_stato(id):
    ordine = OrdineAlimentare.query.get_or_404(id)
    nuovo_stato = request.form.get("stato")
    if nuovo_stato in ["bozza", "inviato", "confermato", "validato"]:
        ordine.stato = nuovo_stato
        db.session.commit()
        flash(f"Ordine aggiornato: {nuovo_stato}.", "success")
    return redirect(url_for("allevamento.ordini_index"))


# ─────────────────────────────────────────────────────────────────────────────
# FASE 6 — ALLARMI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/allarmi/")
@login_required
def allarmi_index():
    now = datetime.utcnow()
    allarmi = Allarme.query.filter(
        Allarme.stato == "attivo",
        db.or_(Allarme.silenziato_fino == None, Allarme.silenziato_fino < now),
    ).order_by(Allarme.data_creazione.desc()).all()
    return render_template("allevamento/allarmi/index.html",
                           allarmi=allarmi, count=len(allarmi))


@bp.route("/allarmi/<int:id>/silenzia", methods=["POST"])
@login_required
@write_required
def allarmi_silenzia(id):
    allarme = Allarme.query.get_or_404(id)
    ore = int(request.form.get("ore", 24))
    allarme.silenziato_fino = datetime.utcnow() + timedelta(hours=ore)
    db.session.commit()
    flash(f"Allarme silenziato per {ore} ore.", "success")
    return redirect(url_for("allevamento.allarmi_index"))


@bp.route("/allarmi/<int:id>/risolvi", methods=["POST"])
@login_required
@write_required
def allarmi_risolvi(id):
    allarme = Allarme.query.get_or_404(id)
    allarme.stato = "risolto"
    db.session.commit()
    flash("Allarme risolto.", "success")
    return redirect(url_for("allevamento.allarmi_index"))


@bp.route("/allarmi/rigenera", methods=["POST"])
@login_required
def allarmi_rigenera():
    redir = _admin_required()
    if redir:
        return redir
    try:
        from app.services.allevamento_alarms import rigenera_allarmi
        rigenera_allarmi()
        flash("Allarmi rigenerati.", "success")
    except Exception as e:
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.allarmi_index"))


# ─────────────────────────────────────────────────────────────────────────────
# FASE 7 — REPORT & MANUTENZIONI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/report/ciclo/<int:id>")
@login_required
def report_ciclo(id):
    lotto = LottoProduttivo.query.get_or_404(id)
    box_cicli = lotto.box_cicli.all()
    bc_ids = [bc.id for bc in box_cicli]

    eventi = EventoCiclo.query.filter(
        EventoCiclo.box_ciclo_id.in_(bc_ids)
    ).order_by(EventoCiclo.data).all() if bc_ids else []

    # Calcolo statistiche
    capi_iniziali_tot = sum(bc.capi_iniziali for bc in box_cicli)
    capi_finali = sum(bc.capi_presenti or 0 for bc in box_cicli)
    morti = sum(
        e.quantita for e in eventi if e.tipo == "mortalita" and e.quantita
    )
    mortalita_perc = (morti / capi_iniziali_tot * 100) if capi_iniziali_tot else 0

    peso_uscita_tot = sum(
        e.peso_totale for e in eventi if e.tipo == "uscita_macello" and e.peso_totale
    )
    capi_usciti = sum(
        e.quantita for e in eventi if e.tipo == "uscita_macello" and e.quantita
    )

    durata_gg = None
    if lotto.data_chiusura:
        durata_gg = (lotto.data_chiusura - lotto.data_inizio).days

    return render_template("allevamento/report/ciclo.html",
                           lotto=lotto, box_cicli=box_cicli, eventi=eventi,
                           capi_iniziali_tot=capi_iniziali_tot,
                           capi_finali=capi_finali, morti=morti,
                           mortalita_perc=mortalita_perc,
                           peso_uscita_tot=peso_uscita_tot,
                           capi_usciti=capi_usciti,
                           durata_gg=durata_gg)


@bp.route("/report/trattamenti")
@login_required
def report_trattamenti():
    trattamenti = TrattamentoSanitario.query.order_by(
        TrattamentoSanitario.data_inizio.desc()
    ).all()
    return render_template("allevamento/report/trattamenti.html", trattamenti=trattamenti)


@bp.route("/report/movimenti")
@login_required
def report_movimenti():
    """Registro carichi/scarichi."""
    eventi = EventoCiclo.query.filter(
        EventoCiclo.tipo.in_(["uscita_macello", "frazionamento_in", "frazionamento_out"])
    ).order_by(EventoCiclo.data.desc()).all()
    return render_template("allevamento/report/movimenti.html", eventi=eventi)


@bp.route("/manutenzioni/")
@login_required
def manutenzioni_index():
    stato_filter = request.args.get("stato", "da_fare")
    q = ManutenzioneBox.query
    if stato_filter != "tutte":
        q = q.filter_by(stato=stato_filter)
    manutenzioni = q.order_by(ManutenzioneBox.scadenza).all()
    capannoni = Capannone.query.order_by(Capannone.numero).all()
    boxes = Box.query.order_by(Box.numero).all()
    return render_template("allevamento/manutenzioni/index.html",
                           manutenzioni=manutenzioni, stato_filter=stato_filter,
                           capannoni=capannoni, boxes=boxes, today=date.today())


@bp.route("/manutenzioni/nuova", methods=["POST"])
@login_required
@write_required
def manutenzioni_nuova():
    box_id_s = request.form.get("box_id", "").strip()
    cap_id_s = request.form.get("capannone_id", "").strip()
    tipo = request.form.get("tipo_attivita", "").strip()
    scadenza_s = request.form.get("scadenza", "").strip()
    note = request.form.get("note", "").strip()

    m = ManutenzioneBox(
        box_id=int(box_id_s) if box_id_s else None,
        capannone_id=int(cap_id_s) if cap_id_s else None,
        tipo_attivita=tipo,
        scadenza=date.fromisoformat(scadenza_s) if scadenza_s else None,
        note=note,
    )
    db.session.add(m)
    db.session.commit()
    flash("Manutenzione registrata.", "success")
    return redirect(url_for("allevamento.manutenzioni_index"))


@bp.route("/manutenzioni/<int:id>/esegui", methods=["POST"])
@login_required
@write_required
def manutenzioni_esegui(id):
    m = ManutenzioneBox.query.get_or_404(id)
    m.stato = "eseguita"
    m.data_esecuzione = date.today()
    db.session.commit()
    flash("Manutenzione segnata come eseguita.", "success")
    return redirect(url_for("allevamento.manutenzioni_index"))


# ─────────────────────────────────────────────────────────────────────────────
# IMPOSTAZIONI STRUTTURA
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/impostazioni")
@bp.route("/impostazioni/struttura")
@login_required
def impostazioni():
    redir = _admin_required()
    if redir:
        return redir
    capannoni = Capannone.query.order_by(Capannone.numero).all()
    boxes = Box.query.order_by(Box.numero).all()
    return render_template("allevamento/impostazioni/struttura.html",
                           capannoni=capannoni, boxes=boxes)


@bp.route("/impostazioni/box/<int:id>/modifica", methods=["POST"])
@login_required
@write_required
def impostazioni_box_modifica(id):
    redir = _admin_required()
    if redir:
        return redir
    box = Box.query.get_or_404(id)
    box.superficie_m2 = float(request.form.get("superficie_m2", box.superficie_m2) or box.superficie_m2)
    box.lunghezza_trogolo_m = float(request.form.get("lunghezza_trogolo_m", box.lunghezza_trogolo_m) or box.lunghezza_trogolo_m)
    box.note = request.form.get("note", "").strip()
    db.session.commit()
    flash(f"Box {box.numero} aggiornato.", "success")
    return redirect(url_for("allevamento.impostazioni"))
