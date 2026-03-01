"""Routes per la sezione Allevamento Suini – Ca Bianca Gestionale."""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (
    Allarme, Box, BoxCiclo, Capannone, ConsegnaAlimentare, CurvaAccrescimento,
    EventoCiclo, InappetenzaBox, LottoProduttivo, MagazzinoProdotto,
    ManutenzioneBox, OrdineAlimentare, OrarioPasto, RazionePasto,
    RazioneGiornaliera, Setting,
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
    """Calcola razione teorica totale per una linea (kg mangime, litri siero, litri acqua)."""
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

    totale_mangime_kg = round(totale_mangime_kg, 1)
    totale_siero_litri = round(totale_siero_litri, 1)
    totale_acqua_litri = _calcola_acqua(totale_mangime_kg, totale_siero_litri)
    return totale_mangime_kg, totale_siero_litri, totale_acqua_litri


def _get_setting_float(key, default):
    s = Setting.query.get(key)
    try:
        return float(s.value) if s else default
    except (TypeError, ValueError):
        return default


def _calcola_acqua(mangime_kg, siero_litri):
    """Calcola acqua aggiuntiva (L) necessaria dal rapporto SS:Liquido.

    Formula:
      ss_totale = mangime_kg + siero_litri * (perc_ss/100)
      liquido_totale = ss_totale * (rapporto_liquido / rapporto_ss)
      acqua_da_siero = siero_litri * (1 - perc_ss/100)
      acqua_aggiuntiva = max(0, liquido_totale - acqua_da_siero)
    """
    rapporto_ss = _get_setting_float("rapporto_ss", 10.0)
    rapporto_liquido = _get_setting_float("rapporto_liquido", 31.0)
    perc_ss = _get_setting_float("allevamento_perc_ss_siero", 6.0) / 100.0
    if rapporto_ss <= 0:
        return 0.0
    ss_totale = mangime_kg + siero_litri * perc_ss
    liquido_totale = ss_totale * (rapporto_liquido / rapporto_ss)
    acqua_da_siero = siero_litri * (1.0 - perc_ss)
    return round(max(0.0, liquido_totale - acqua_da_siero), 1)


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


@bp.route("/box/<int:numero>/modal")
@login_required
def box_modal(numero):
    """API JSON per il modal del box sulla mappa (numero = numero box 1-54)."""
    box = Box.query.filter_by(numero=numero).first_or_404()
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
            "lotto_db_id": ciclo.lotto_id,
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
    all_boxes = Box.query.order_by(Box.numero).all()

    # Mappa box_numero -> info (usata anche nel template)
    box_map = {}
    for b in all_boxes:
        libero = not b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
        box_map[b.numero] = {
            "id": b.id,
            "capannone": b.capannone.numero,
            "linea": b.linea_alimentazione,
            "capienza": int(b.superficie_m2) if b.superficie_m2 else 0,
            "libero": libero,
        }

    if request.method == "POST":
        data_arrivo_str = request.form.get("data_arrivo", str(date.today()))
        peso_totale_bolla = float(request.form.get("peso_totale_bolla", 0) or 0)
        note = request.form.get("note", "").strip()

        # Leggi capi per singolo box
        box_capi = {}
        for b in all_boxes:
            val = request.form.get(f"capi_box_{b.id}", "").strip()
            if val:
                try:
                    n = int(val)
                    if n > 0:
                        box_capi[b.id] = n
                except ValueError:
                    pass

        if not box_capi:
            flash("Seleziona almeno un box e inserisci i capi.", "danger")
            return render_template("allevamento/lotti/nuovo.html",
                                   box_map=box_map, today=date.today())

        capi_effettivi = sum(box_capi.values())
        data_arrivo = date.fromisoformat(data_arrivo_str)
        peso_medio = (peso_totale_bolla / capi_effettivi) if capi_effettivi > 0 else 0.0
        eta_stimata = _eta_da_peso(peso_medio) if peso_medio > 0 else None

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

        for bid, capi_box in box_capi.items():
            peso_box = (peso_totale_bolla / capi_effettivi * capi_box) if capi_effettivi else 0
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
        flash(f"Lotto {lotto.lotto_id} creato con {capi_effettivi} capi in {len(box_capi)} box.", "success")
        return redirect(url_for("allevamento.lotti_detail", id=lotto.id))

    return render_template("allevamento/lotti/nuovo.html",
                           box_map=box_map, today=date.today())


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


@bp.route("/lotti/<int:id>/riaccasamento", methods=["GET", "POST"])
@login_required
@write_required
def lotti_riaccasamento(id):
    lotto = LottoProduttivo.query.get_or_404(id)
    if lotto.stato != "attivo":
        flash("Il lotto non è attivo.", "warning")
        return redirect(url_for("allevamento.lotti_detail", id=id))

    all_boxes = Box.query.order_by(Box.numero).all()

    # BoxCiclo attivi/in_uscita del lotto: numero_box -> bc
    lotto_bc = {
        bc.box.numero: bc
        for bc in lotto.box_cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).all()
    }

    # Mappa completa per SVG: numero_box -> info
    box_map = {}
    for b in all_boxes:
        if b.numero in lotto_bc:
            bc = lotto_bc[b.numero]
            box_map[b.numero] = {
                "id": b.id, "bc_id": bc.id,
                "capannone": b.capannone.numero, "linea": b.linea_alimentazione,
                "capienza": int(b.superficie_m2) if b.superficie_m2 else 0,
                "stato": "in_lotto",
                "capi_presenti": bc.capi_presenti or 0,
                "peso_medio": bc.peso_medio_iniziale or 0,
            }
        else:
            altro_ciclo = b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
            box_map[b.numero] = {
                "id": b.id, "bc_id": None,
                "capannone": b.capannone.numero, "linea": b.linea_alimentazione,
                "capienza": int(b.superficie_m2) if b.superficie_m2 else 0,
                "stato": "libero" if not altro_ciclo else "occupato",
                "capi_presenti": 0, "peso_medio": 0,
            }

    capi_totali_prima = sum(bc.capi_presenti or 0 for bc in lotto_bc.values())

    if request.method == "POST":
        data_str = request.form.get("data_riaccasamento", str(date.today()))
        data_riaccasamento = date.fromisoformat(data_str)

        # Aggiorna box già nel lotto
        for box_num, bc in lotto_bc.items():
            val_capi = request.form.get(f"capi_bc_{bc.id}", "").strip()
            val_peso = request.form.get(f"peso_bc_{bc.id}", "").strip()
            if not val_capi:
                continue
            nuovi_capi = int(val_capi)
            nuovi_peso = float(val_peso) if val_peso else None
            capi_prima = bc.capi_presenti or 0

            bc.capi_presenti = nuovi_capi
            bc.stato = "chiuso" if nuovi_capi == 0 else bc.stato
            if nuovi_peso:
                bc.peso_medio_iniziale = round(nuovi_peso, 2)
                bc.eta_stimata_gg = _eta_da_peso(nuovi_peso)

            nota = f"Riaccasamento: {capi_prima}→{nuovi_capi} capi"
            if nuovi_peso:
                nota += f", peso medio {nuovi_peso:.1f} kg"
            db.session.add(EventoCiclo(
                box_ciclo_id=bc.id, tipo="riaccasamento",
                data=data_riaccasamento, quantita=nuovi_capi,
                peso_totale=round(nuovi_peso * nuovi_capi, 1) if nuovi_peso and nuovi_capi else None,
                note=nota, operatore_id=current_user.id,
            ))

        # Aggiunge box nuovi (liberi selezionati)
        for b in all_boxes:
            if b.numero in lotto_bc:
                continue
            val_capi = request.form.get(f"capi_box_{b.id}", "").strip()
            val_peso = request.form.get(f"peso_box_{b.id}", "").strip()
            if not val_capi or int(val_capi) <= 0:
                continue
            if b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first():
                continue

            nuovi_capi = int(val_capi)
            nuovi_peso = float(val_peso) if val_peso else None
            # Se peso non specificato, eredita media del lotto
            if not nuovi_peso:
                pesi = [bc.peso_medio_iniziale for bc in lotto_bc.values() if bc.peso_medio_iniziale]
                nuovi_peso = round(sum(pesi) / len(pesi), 2) if pesi else None
            eta = _eta_da_peso(nuovi_peso) if nuovi_peso else None

            bc_new = BoxCiclo(
                lotto_id=lotto.id, box_id=b.id,
                data_accasamento=data_riaccasamento,
                capi_iniziali=nuovi_capi,
                peso_totale_iniziale=round((nuovi_peso or 0) * nuovi_capi, 1),
                peso_medio_iniziale=nuovi_peso,
                eta_stimata_gg=eta,
                capi_presenti=nuovi_capi,
                stato="attivo",
            )
            db.session.add(bc_new)
            db.session.flush()

            nota = f"Riaccasamento: nuovo box con {nuovi_capi} capi"
            if nuovi_peso:
                nota += f", peso medio {nuovi_peso:.1f} kg"
            db.session.add(EventoCiclo(
                box_ciclo_id=bc_new.id, tipo="riaccasamento",
                data=data_riaccasamento, quantita=nuovi_capi,
                peso_totale=round((nuovi_peso or 0) * nuovi_capi, 1) if nuovi_peso else None,
                note=nota, operatore_id=current_user.id,
            ))

        db.session.commit()
        flash("Riaccasamento registrato.", "success")
        return redirect(url_for("allevamento.lotti_detail", id=id))

    return render_template("allevamento/lotti/riaccasamento.html",
                           lotto=lotto, box_map=box_map,
                           lotto_bc=lotto_bc,
                           capi_totali_prima=capi_totali_prima,
                           today=date.today())


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
        is_scarti = request.form.get("is_scarti") == "1"

        bc = BoxCiclo.query.get_or_404(box_ciclo_id)
        ev = EventoCiclo(
            box_ciclo_id=box_ciclo_id,
            tipo=tipo,
            data=date.fromisoformat(data_str),
            quantita=quantita,
            peso_totale=peso_totale if peso_totale else None,
            note=note,
            operatore_id=current_user.id,
            is_scarti=is_scarti,
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
    orari_pasto = OrarioPasto.query.filter_by(attivo=True).order_by(OrarioPasto.numero).all()
    razioni = {}
    for linea in [1, 2, 3]:
        mangime, siero, acqua = _calcola_razioni_linea(linea)
        razione_db = RazioneGiornaliera.query.filter_by(data=oggi, linea=linea).first()
        pasti_oggi = RazionePasto.query.filter_by(data=oggi, linea=linea).order_by(RazionePasto.numero_pasto).all()
        razioni[linea] = {
            "teorica_mangime": mangime,
            "teorica_siero": siero,
            "teorica_acqua": acqua,
            "consumo_mangime": razione_db.consumo_mangime_kg if razione_db else None,
            "consumo_siero": razione_db.consumo_siero_litri if razione_db else None,
            "consumo_acqua": razione_db.consumo_acqua_litri if razione_db else None,
            "note": razione_db.note if razione_db else "",
            "pasti": pasti_oggi,
        }
    return render_template("allevamento/alimentazione/index.html",
                           razioni=razioni, oggi=oggi, orari_pasto=orari_pasto)


@bp.route("/alimentazione/consumi", methods=["GET", "POST"])
@login_required
@write_required
def alimentazione_consumi():
    """Redirect al form pasti multipli (legacy: mantiene compatibilità URL)."""
    return redirect(url_for("allevamento.alimentazione_consumi_pasto"))


@bp.route("/alimentazione/consumi/pasto", methods=["GET", "POST"])
@login_required
@write_required
def alimentazione_consumi_pasto():
    oggi = date.today()
    numero_pasti = int(_get_setting_float("numero_pasti", 3))
    orari_pasto = {op.numero: op for op in OrarioPasto.query.filter_by(attivo=True).order_by(OrarioPasto.numero).all()}

    if request.method == "POST":
        data_str = request.form.get("data", str(oggi))
        data_razione = date.fromisoformat(data_str)

        for pasto in range(1, numero_pasti + 1):
            for linea in [1, 2, 3]:
                mangime_s = request.form.get(f"mangime_{pasto}_{linea}", "").strip()
                siero_s = request.form.get(f"siero_{pasto}_{linea}", "").strip()
                acqua_s = request.form.get(f"acqua_{pasto}_{linea}", "").strip()
                note_s = request.form.get(f"note_{pasto}_{linea}", "").strip()
                if not mangime_s and not siero_s and not acqua_s:
                    continue
                mangime_val = float(mangime_s) if mangime_s else None
                siero_val = float(siero_s) if siero_s else None
                acqua_val = float(acqua_s) if acqua_s else None

                rp = RazionePasto.query.filter_by(data=data_razione, numero_pasto=pasto, linea=linea).first()
                if rp is None:
                    rp = RazionePasto(data=data_razione, numero_pasto=pasto, linea=linea,
                                      created_by=current_user.id)
                    db.session.add(rp)
                rp.consumo_mangime_kg = mangime_val
                rp.consumo_siero_litri = siero_val
                rp.consumo_acqua_litri = acqua_val
                rp.note = note_s

        db.session.flush()

        # Aggiorna RazioneGiornaliera aggregata per ogni linea
        for linea in [1, 2, 3]:
            pasti_linea = RazionePasto.query.filter_by(data=data_razione, linea=linea).all()
            if not pasti_linea:
                continue
            sum_mangime = sum(p.consumo_mangime_kg or 0 for p in pasti_linea)
            sum_siero = sum(p.consumo_siero_litri or 0 for p in pasti_linea)
            sum_acqua = sum(p.consumo_acqua_litri or 0 for p in pasti_linea)
            teorica_m, teorica_s, teorica_a = _calcola_razioni_linea(linea)

            rg = RazioneGiornaliera.query.filter_by(data=data_razione, linea=linea).first()
            if rg is None:
                rg = RazioneGiornaliera(data=data_razione, linea=linea)
                db.session.add(rg)
            rg.razione_teorica_kg = teorica_m
            rg.consumo_mangime_kg = sum_mangime if sum_mangime else None
            rg.consumo_siero_litri = sum_siero if sum_siero else None
            rg.consumo_acqua_litri = sum_acqua if sum_acqua else None
            rg.acqua_teorica_litri = teorica_a

        db.session.commit()
        flash("Consumi registrati.", "success")
        return redirect(url_for("allevamento.alimentazione_index"))

    # GET: pre-carica razioni teoriche e pasti esistenti per oggi
    razioni_teoriche = {}
    pasti_esistenti = {}
    for linea in [1, 2, 3]:
        m, s, a = _calcola_razioni_linea(linea)
        razioni_teoriche[linea] = {"mangime": m, "siero": s, "acqua": a}
        for pasto in range(1, numero_pasti + 1):
            rp = RazionePasto.query.filter_by(data=oggi, numero_pasto=pasto, linea=linea).first()
            if rp:
                pasti_esistenti[(pasto, linea)] = rp

    rapporto_ss = _get_setting_float("rapporto_ss", 10.0)
    rapporto_liquido = _get_setting_float("rapporto_liquido", 31.0)
    perc_ss_siero = _get_setting_float("allevamento_perc_ss_siero", 6.0)

    return render_template("allevamento/alimentazione/consumi_pasto.html",
                           oggi=oggi, numero_pasti=numero_pasti,
                           orari_pasto=orari_pasto,
                           razioni_teoriche=razioni_teoriche,
                           pasti_esistenti=pasti_esistenti,
                           rapporto_ss=rapporto_ss,
                           rapporto_liquido=rapporto_liquido,
                           perc_ss_siero=perc_ss_siero)


@bp.route("/alimentazione/storico")
@login_required
def alimentazione_storico():
    vista = request.args.get("vista", "giornaliera")
    razioni = RazioneGiornaliera.query.order_by(
        RazioneGiornaliera.data.desc(), RazioneGiornaliera.linea
    ).limit(90).all()
    pasti = RazionePasto.query.order_by(
        RazionePasto.data.desc(), RazionePasto.linea, RazionePasto.numero_pasto
    ).limit(270).all()
    return render_template("allevamento/alimentazione/storico.html",
                           razioni=razioni, pasti=pasti, vista=vista)


@bp.route("/alimentazione/cisterna")
@login_required
def alimentazione_cisterna():
    from datetime import time as dt_time
    orari = OrarioPasto.query.order_by(OrarioPasto.numero).all()
    buffer_min = int(_get_setting_float("cisterna_buffer_minuti", 60))

    now = datetime.now()
    pasti_info = []
    for op in orari:
        if not op.attivo:
            continue
        ora_limite = datetime.combine(now.date(), op.ora)
        ora_limite -= timedelta(minutes=buffer_min)
        if now < ora_limite:
            status = "verde"
        elif now < datetime.combine(now.date(), op.ora):
            status = "arancio"
        else:
            status = "rosso"
        pasti_info.append({
            "numero": op.numero,
            "ora_pasto": op.ora,
            "ora_limite": ora_limite.time(),
            "status": status,
        })

    ordini_siero = OrdineAlimentare.query.filter(
        OrdineAlimentare.tipo == "siero",
        OrdineAlimentare.stato.in_(["bozza", "inviato", "confermato"]),
    ).order_by(OrdineAlimentare.data_consegna).limit(10).all()

    return render_template("allevamento/alimentazione/cisterna.html",
                           pasti_info=pasti_info, ordini_siero=ordini_siero,
                           buffer_min=buffer_min, now=now)


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
        elif azione == "orari_pasto":
            from datetime import time as dt_time
            numero_pasti_new = int(request.form.get("numero_pasti", 3))
            _set_setting("numero_pasti", str(numero_pasti_new))
            for n in range(1, 4):
                ora_s = request.form.get(f"ora_pasto_{n}", "").strip()
                attivo = request.form.get(f"attivo_pasto_{n}") == "1"
                if not ora_s:
                    continue
                try:
                    h, m = map(int, ora_s.split(":"))
                    op = OrarioPasto.query.get(n)
                    if op is None:
                        op = OrarioPasto(numero=n, ora=dt_time(h, m), attivo=attivo)
                        db.session.add(op)
                    else:
                        op.ora = dt_time(h, m)
                        op.attivo = attivo
                except (ValueError, TypeError):
                    continue
            db.session.commit()
            flash("Orari pasti aggiornati.", "success")
        elif azione == "parametri_acqua":
            rapporto_ss = request.form.get("rapporto_ss", "10").strip()
            rapporto_liquido = request.form.get("rapporto_liquido", "31").strip()
            buffer_min = request.form.get("cisterna_buffer_minuti", "60").strip()
            _set_setting("rapporto_ss", rapporto_ss)
            _set_setting("rapporto_liquido", rapporto_liquido)
            _set_setting("cisterna_buffer_minuti", buffer_min)
            db.session.commit()
            flash("Parametri acqua/cisterna aggiornati.", "success")
        return redirect(url_for("allevamento.alimentazione_impostazioni"))

    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    tabella_siero = TabellaSostSiero.query.order_by(TabellaSostSiero.eta_min).all()
    perc_ss = _get_setting_float("allevamento_perc_ss_siero", 6.0)
    orari_pasto = {op.numero: op for op in OrarioPasto.query.order_by(OrarioPasto.numero).all()}
    numero_pasti = int(_get_setting_float("numero_pasti", 3))
    rapporto_ss = _get_setting_float("rapporto_ss", 10.0)
    rapporto_liquido = _get_setting_float("rapporto_liquido", 31.0)
    buffer_min = int(_get_setting_float("cisterna_buffer_minuti", 60))

    # Anteprima calcolo acqua con 100 kg mangime + 100 L siero
    acqua_preview = _calcola_acqua(100.0, 100.0)

    return render_template("allevamento/alimentazione/impostazioni.html",
                           curva=curva, tabella_siero=tabella_siero, perc_ss=perc_ss,
                           orari_pasto=orari_pasto, numero_pasti=numero_pasti,
                           rapporto_ss=rapporto_ss, rapporto_liquido=rapporto_liquido,
                           buffer_min=buffer_min, acqua_preview=acqua_preview)


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

    uscite_normali = [e for e in eventi if e.tipo == "uscita_macello" and not e.is_scarti]
    uscite_scarti  = [e for e in eventi if e.tipo == "uscita_macello" and e.is_scarti]

    peso_uscita_normale = sum(e.peso_totale for e in uscite_normali if e.peso_totale)
    capi_usciti_normale = sum(e.quantita for e in uscite_normali if e.quantita)

    peso_uscita_scarti  = sum(e.peso_totale for e in uscite_scarti if e.peso_totale)
    capi_usciti_scarti  = sum(e.quantita for e in uscite_scarti if e.quantita)

    peso_uscita_effettivo = peso_uscita_normale + peso_uscita_scarti * 0.5
    capi_usciti_tot = capi_usciti_normale + capi_usciti_scarti

    # Mantenuto per compatibilità template (totale grezzo)
    peso_uscita_tot = peso_uscita_normale + peso_uscita_scarti
    capi_usciti = capi_usciti_tot

    durata_gg = None
    if lotto.data_chiusura:
        durata_gg = (lotto.data_chiusura - lotto.data_inizio).days

    return render_template("allevamento/report/ciclo.html",
                           lotto=lotto, box_cicli=box_cicli, eventi=eventi,
                           capi_iniziali_tot=capi_iniziali_tot,
                           capi_finali=capi_finali, morti=morti,
                           mortalita_perc=mortalita_perc,
                           peso_uscita_tot=peso_uscita_tot,
                           peso_uscita_normale=peso_uscita_normale,
                           peso_uscita_scarti=peso_uscita_scarti,
                           peso_uscita_effettivo=peso_uscita_effettivo,
                           capi_usciti_normale=capi_usciti_normale,
                           capi_usciti_scarti=capi_usciti_scarti,
                           capi_usciti=capi_usciti,
                           capi_usciti_tot=capi_usciti_tot,
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
