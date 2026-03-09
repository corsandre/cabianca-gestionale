"""Routes per la sezione Allevamento Suini – Ca Bianca Gestionale."""
from datetime import date, datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import (
    Allarme, Box, BoxCiclo, Capannone, CicloProduttivo, ConsegnaAlimentare,
    CurvaAccrescimento, EventoCiclo, InappetenzaBox, Lotto,
    MagazzinoProdotto, ManutenzioneBox, OrdineAlimentare, OrarioPasto,
    RazionePasto, RazioneGiornaliera, Setting,
    TabellaSostSiero, TrattamentoSanitario, User,
)
from app.utils.decorators import section_required, write_required

bp = Blueprint("allevamento", __name__, url_prefix="/allevamento")
bp.before_request(section_required("allevamento"))


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────

# Tabella lettere mesi DOP (disciplinare Prosciutto di Parma)
LETTERE_MESI = {
    'T': 1, 'C': 2, 'B': 3, 'A': 4, 'M': 5, 'P': 6,
    'L': 7, 'E': 8, 'S': 9, 'R': 10, 'H': 11, 'D': 12,
}
MESI_LETTERE = {v: k for k, v in LETTERE_MESI.items()}
NOMI_MESI = {
    1: 'Gennaio', 2: 'Febbraio', 3: 'Marzo', 4: 'Aprile',
    5: 'Maggio', 6: 'Giugno', 7: 'Luglio', 8: 'Agosto',
    9: 'Settembre', 10: 'Ottobre', 11: 'Novembre', 12: 'Dicembre',
}


def _admin_required():
    """Guard helper: restituisce un redirect se l'utente corrente non è admin, altrimenti None."""
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


def _peso_da_eta(eta_gg):
    """Interpola la curva di accrescimento per stimare il peso in kg da un'età in giorni."""
    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    if not curva:
        return None
    if eta_gg <= curva[0].eta_giorni:
        return round(curva[0].peso_kg, 1)
    if eta_gg >= curva[-1].eta_giorni:
        return round(curva[-1].peso_kg, 1)
    for i in range(len(curva) - 1):
        a, b = curva[i], curva[i + 1]
        if a.eta_giorni <= eta_gg <= b.eta_giorni:
            ratio = (eta_gg - a.eta_giorni) / (b.eta_giorni - a.eta_giorni)
            return round(a.peso_kg + ratio * (b.peso_kg - a.peso_kg), 1)
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


def _calcola_razioni_linea_dettaglio(linea):
    """Come _calcola_razioni_linea ma ritorna anche boxes_dettaglio per espansione UI."""
    oggi = date.today()
    boxes_linea = Box.query.filter_by(linea_alimentazione=linea).all()
    box_ids = [b.id for b in boxes_linea]
    cicli_attivi = BoxCiclo.query.filter(
        BoxCiclo.box_id.in_(box_ids),
        BoxCiclo.stato.in_(["attivo", "in_uscita"]),
    ).all()

    totale_mangime_kg = 0.0
    totale_siero_litri = 0.0
    boxes_dettaglio = []

    for bc in cicli_attivi:
        if not bc.eta_stimata_gg or not bc.data_accasamento or not bc.capi_presenti:
            continue
        eta_oggi = bc.eta_stimata_gg + (oggi - bc.data_accasamento).days
        razione_base = _razione_da_eta(eta_oggi)
        inapp = bc.inappetenze.filter(
            InappetenzaBox.data_inizio <= oggi,
            db.or_(InappetenzaBox.data_fine == None, InappetenzaBox.data_fine >= oggi),
        ).first()
        perc_razione = (inapp.percentuale_razione / 100.0) if inapp else 1.0
        razione_box = razione_base * bc.capi_presenti * perc_razione

        perc_s = _perc_siero_da_eta(eta_oggi) / 100.0
        ss_perc = _get_setting_float("allevamento_perc_ss_siero", 6.0) / 100.0
        siero_ss_kg = razione_box * perc_s
        siero_litri = (siero_ss_kg / ss_perc) if ss_perc > 0 else 0.0
        mangime_kg = razione_box - siero_ss_kg

        totale_mangime_kg += mangime_kg
        totale_siero_litri += siero_litri

        acqua_box = _calcola_acqua(round(mangime_kg, 1), round(siero_litri, 1))
        boxes_dettaglio.append({
            "numero": bc.box.numero,
            "capi": bc.capi_presenti,
            "eta": eta_oggi,
            "razione_per_capo": round(razione_base, 2),
            "perc_razione": round(perc_razione * 100),
            "ha_inappetenza": inapp is not None,
            "mangime_kg": round(mangime_kg, 1),
            "siero_litri": round(siero_litri, 1),
            "acqua_litri": acqua_box,
        })

    boxes_dettaglio.sort(key=lambda x: x["numero"])
    totale_mangime_kg = round(totale_mangime_kg, 1)
    totale_siero_litri = round(totale_siero_litri, 1)
    totale_acqua_litri = _calcola_acqua(totale_mangime_kg, totale_siero_litri)
    return totale_mangime_kg, totale_siero_litri, totale_acqua_litri, boxes_dettaglio


def _get_setting_float(key, default):
    """Legge un Setting dal DB per chiave e lo converte in float; ritorna default se assente o non convertibile."""
    s = Setting.query.get(key)
    try:
        return float(s.value) if s else default
    except (TypeError, ValueError):
        return default


def _interp_curva_precaricata(curva, eta_gg):
    """Razione giornaliera (kg/capo) da curva pre-caricata."""
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


def _interp_siero_precaricata(tabella, eta_gg):
    """Percentuale sostituzione siero da tabella pre-caricata."""
    for row in tabella:
        if row.eta_min <= eta_gg <= row.eta_max:
            return row.percentuale_siero
    return 0.0


def _capi_storici_data(bc, data_target, eventi_bc=None):
    """Calcola capi presenti in un BoxCiclo a una data specifica.
    eventi_bc è la lista pre-caricata ordinata per data (opzionale).
    """
    if bc.data_accasamento > data_target:
        return 0
    capi = bc.capi_iniziali or 0
    evs = eventi_bc if eventi_bc is not None else bc.eventi.order_by(EventoCiclo.data).all()
    for ev in evs:
        if ev.data > data_target:
            break
        if ev.tipo == 'riaccasamento':
            capi = ev.quantita or capi
        elif ev.tipo in ('mortalita', 'frazionamento_out', 'uscita_macello'):
            capi -= (ev.quantita or 0)
        elif ev.tipo == 'frazionamento_in':
            capi += (ev.quantita or 0)
    return max(0, capi)


def _rigenera_stime_ciclo(ciclo, data_da=None):
    """Rigenera stime razione teoriche sulle linee del ciclo dal data_da a oggi.
    Sostituisce solo record is_stima=True, mai record reali (is_stima=False/NULL).
    """
    from datetime import timedelta

    data_inizio = data_da if data_da else ciclo.data_inizio
    data_fine = date.today()

    if data_inizio > data_fine:
        return

    # Linee coinvolte da questo ciclo
    linee_ciclo = set()
    for bc in ciclo.box_cicli.all():
        if bc.box and bc.box.linea_alimentazione:
            linee_ciclo.add(bc.box.linea_alimentazione)
    if not linee_ciclo:
        return

    curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    tabella_siero = TabellaSostSiero.query.all()
    if not curva:
        return

    ss_perc = _get_setting_float("allevamento_perc_ss_siero", 6.0) / 100.0

    # Pre-carica tutti i BoxCiclo sulle linee coinvolte (tutti i cicli)
    boxes_per_linea = {}
    all_bc_for_linee = []
    for linea in linee_ciclo:
        boxes_l = Box.query.filter_by(linea_alimentazione=linea).all()
        box_ids_l = [b.id for b in boxes_l]
        bc_list = BoxCiclo.query.filter(BoxCiclo.box_id.in_(box_ids_l)).all()
        boxes_per_linea[linea] = bc_list
        all_bc_for_linee.extend(bc_list)

    # Pre-carica tutti gli eventi per quei BoxCiclo (tutti, non solo nel range)
    all_bc_ids = [bc.id for bc in all_bc_for_linee]
    all_eventi = EventoCiclo.query.filter(
        EventoCiclo.box_ciclo_id.in_(all_bc_ids)
    ).order_by(EventoCiclo.data).all()
    eventi_per_bc = {}
    for ev in all_eventi:
        eventi_per_bc.setdefault(ev.box_ciclo_id, []).append(ev)

    giorni = (data_fine - data_inizio).days + 1

    for delta in range(giorni):
        d = data_inizio + timedelta(days=delta)

        for linea in linee_ciclo:
            # Skip se esiste già un dato reale (non stima) per questa data/linea
            razione_reale = RazioneGiornaliera.query.filter_by(data=d, linea=linea).filter(
                db.or_(RazioneGiornaliera.is_stima == False, RazioneGiornaliera.is_stima == None)
            ).first()
            if razione_reale:
                continue

            totale_mangime = 0.0
            totale_siero = 0.0
            ha_animali = False

            for bc in boxes_per_linea[linea]:
                if not bc.data_accasamento or bc.data_accasamento > d:
                    continue
                if not bc.eta_stimata_gg:
                    continue

                capi = _capi_storici_data(bc, d, eventi_per_bc.get(bc.id, []))
                if capi <= 0:
                    continue

                ha_animali = True
                eta = bc.eta_stimata_gg + (d - bc.data_accasamento).days
                razione_base = _interp_curva_precaricata(curva, eta)
                perc_s = _interp_siero_precaricata(tabella_siero, eta) / 100.0
                razione_box = razione_base * capi

                siero_ss_kg = razione_box * perc_s
                siero_litri = (siero_ss_kg / ss_perc) if ss_perc > 0 else 0.0
                mangime_kg = razione_box - siero_ss_kg

                totale_mangime += mangime_kg
                totale_siero += siero_litri

            # Elimina stima precedente per questa data/linea
            RazioneGiornaliera.query.filter_by(
                data=d, linea=linea, is_stima=True
            ).delete(synchronize_session='fetch')

            if not ha_animali:
                continue

            acqua = _calcola_acqua(round(totale_mangime, 1), round(totale_siero, 1))
            razione_teorica = totale_mangime + totale_siero * ss_perc

            db.session.add(RazioneGiornaliera(
                data=d,
                linea=linea,
                razione_teorica_kg=round(razione_teorica, 1),
                consumo_mangime_kg=round(totale_mangime, 1),
                consumo_siero_litri=round(totale_siero, 1),
                acqua_teorica_litri=round(acqua, 1),
                is_stima=True,
            ))

    db.session.commit()


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


def _genera_ciclo_id():
    """Genera un identificativo univoco per un ciclo produttivo nel formato CICLO{aa}-{nn}-{YYYYMMDD}."""
    anno = date.today().year % 100
    count = CicloProduttivo.query.count() + 1
    data_str = date.today().strftime("%Y%m%d")
    return f"CICLO{anno:02d}-{count:02d}-{data_str}"


def _calcola_data_vendita(lettera, data_arrivo):
    """Calcola data minima di vendita DOP (9 mesi dalla nascita)."""
    mese = LETTERE_MESI.get((lettera or '').upper())
    if not mese:
        return None
    # L'anno di nascita: se il mese lettera è ≤ mese arrivo+1, stessa annata; altrimenti anno prima
    anno_nascita = data_arrivo.year if mese <= data_arrivo.month + 1 else data_arrivo.year - 1
    mese_vendita = mese + 9
    anno_vendita = anno_nascita + (1 if mese_vendita > 12 else 0)
    mese_vendita = mese_vendita - 12 if mese_vendita > 12 else mese_vendita
    return date(anno_vendita, mese_vendita, 1)


def _box_state(box, active_alarms_bc_ids):
    """Restituisce stato box per la mappa SVG."""
    bc = box.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
    if bc is None:
        return "libero", 0, None, None
    if bc.id in active_alarms_bc_ids:
        stato = "allarme"
    elif bc.stato == "in_uscita":
        stato = "in_attesa"
    else:
        stato = f"linea{box.linea_alimentazione}"
    return stato, bc.capi_presenti or 0, bc.id, bc.ciclo.ciclo_id


def _allarmi_attivi_count():
    """Conta gli allarmi attivi non silenziati (usato per badge nel menu)."""
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
        stato, capi, bc_id, ciclo_codice = _box_state(b, active_alarms_bc_ids)
        box_data[b.numero] = {
            "stato": stato,
            "capi": capi,
            "bc_id": bc_id,
            "ciclo_id": ciclo_codice,
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
    bc = box.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
    data = {
        "numero": box.numero,
        "capannone": box.capannone.nome,
        "linea": box.linea_alimentazione,
        "superficie": box.superficie_m2,
        "ciclo": None,
    }
    if bc:
        oggi = date.today()
        eta_oggi = None
        if bc.eta_stimata_gg and bc.data_accasamento:
            eta_oggi = bc.eta_stimata_gg + (oggi - bc.data_accasamento).days
        data["ciclo"] = {
            "id": bc.id,
            "ciclo_db_id": bc.ciclo_id,
            "ciclo_id": bc.ciclo.ciclo_id,
            "data_accasamento": bc.data_accasamento.strftime("%d/%m/%Y"),
            "capi_iniziali": bc.capi_iniziali,
            "capi_presenti": bc.capi_presenti,
            "peso_medio_iniziale": bc.peso_medio_iniziale,
            "eta_oggi": eta_oggi,
            "stato": bc.stato,
        }
    return jsonify(data)


# ─────────────────────────────────────────────────────────────────────────────
# FASE 2 — CICLI PRODUTTIVI
# ─────────────────────────────────────────────────────────────────────────────

@bp.route("/cicli/")
@login_required
def cicli_index():
    stato_filter = request.args.get("stato", "attivo")
    q = CicloProduttivo.query
    if stato_filter != "tutti":
        q = q.filter_by(stato=stato_filter)
    cicli = q.order_by(CicloProduttivo.data_inizio.desc()).all()
    return render_template("allevamento/cicli/index.html", cicli=cicli, stato_filter=stato_filter)


@bp.route("/cicli/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def cicli_nuovo():
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
        lettera = request.form.get("lettera_nascita", "").strip().upper() or None
        fornitore = request.form.get("fornitore", "").strip() or None
        numero_documento = request.form.get("numero_documento", "").strip() or None

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
            return render_template("allevamento/cicli/nuovo.html",
                                   box_map=box_map, today=date.today(),
                                   lettere_mesi=LETTERE_MESI, nomi_mesi=NOMI_MESI)

        capi_effettivi = sum(box_capi.values())
        data_arrivo = date.fromisoformat(data_arrivo_str)
        peso_medio = (peso_totale_bolla / capi_effettivi) if capi_effettivi > 0 else 0.0
        eta_stimata = _eta_da_peso(peso_medio) if peso_medio > 0 else None

        ciclo = CicloProduttivo(
            ciclo_id=_genera_ciclo_id(),
            numero_ciclo=CicloProduttivo.query.count() + 1,
            data_inizio=data_arrivo,
            stato="attivo",
            note=note,
            created_by=current_user.id,
        )
        db.session.add(ciclo)
        db.session.flush()

        # Primo lotto (bolla) del ciclo
        lotto = Lotto(
            ciclo_id=ciclo.id,
            numero_lotto=1,
            data_consegna=data_arrivo,
            peso_totale_bolla_kg=peso_totale_bolla if peso_totale_bolla else None,
            lettera_nascita=lettera,
            fornitore=fornitore,
            numero_documento=numero_documento,
            note=note,
            created_by=current_user.id,
        )
        db.session.add(lotto)
        db.session.flush()

        for bid, capi_box in box_capi.items():
            peso_box = (peso_totale_bolla / capi_effettivi * capi_box) if capi_effettivi else 0
            bc = BoxCiclo(
                ciclo_id=ciclo.id,
                lotto_id=lotto.id,
                lettera_nascita=lettera,
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
        _rigenera_stime_ciclo(ciclo)
        flash(f"Ciclo {ciclo.ciclo_id} creato con {capi_effettivi} capi in {len(box_capi)} box.", "success")
        return redirect(url_for("allevamento.cicli_detail", id=ciclo.id))

    return render_template("allevamento/cicli/nuovo.html",
                           box_map=box_map, today=date.today(),
                           lettere_mesi=LETTERE_MESI, nomi_mesi=NOMI_MESI)


@bp.route("/cicli/<int:id>")
@login_required
def cicli_detail(id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    box_cicli = ciclo.box_cicli.all()
    box_cicli_attivi = ciclo.box_cicli.filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"])
    ).order_by(BoxCiclo.box_id).all()
    lotti = ciclo.lotti.order_by(Lotto.numero_lotto).all()
    # Tutti gli eventi per questo ciclo, ordinati per data desc
    bc_ids = [bc.id for bc in box_cicli]
    eventi = EventoCiclo.query.filter(
        EventoCiclo.box_ciclo_id.in_(bc_ids)
    ).order_by(EventoCiclo.data.desc()).all() if bc_ids else []

    # Calcola data vendita prevista, peso medio ed età stimata per ogni lotto
    lotti_info = []
    for lt in lotti:
        data_vendita = _calcola_data_vendita(lt.lettera_nascita, lt.data_consegna) if lt.lettera_nascita else None
        bcs = lt.box_cicli.all()
        capi_totali = sum(bc.capi_iniziali for bc in bcs)
        # Peso medio: da bolla / capi oppure da BoxCiclo salvato
        if lt.peso_totale_bolla_kg and capi_totali:
            peso_medio = round(lt.peso_totale_bolla_kg / capi_totali, 1)
        else:
            pm_vals = [bc.peso_medio_iniziale for bc in bcs if bc.peso_medio_iniziale]
            peso_medio = round(sum(pm_vals) / len(pm_vals), 1) if pm_vals else None
        # Età stimata: prendi dal primo BoxCiclo, altrimenti ricalcola
        eta_vals = [bc.eta_stimata_gg for bc in bcs if bc.eta_stimata_gg]
        eta_stimata = round(sum(eta_vals) / len(eta_vals)) if eta_vals else (
            _eta_da_peso(peso_medio) if peso_medio else None
        )
        lotti_info.append({
            "lotto": lt,
            "data_vendita": data_vendita,
            "n_box": len(bcs),
            "peso_medio": peso_medio,
            "eta_stimata": eta_stimata,
        })

    # Banner warning se lettere diverse tra lotti
    lettere_uniche = {lt.lettera_nascita for lt in lotti if lt.lettera_nascita}
    lettere_miste = len(lettere_uniche) > 1

    return render_template("allevamento/cicli/detail.html",
                           ciclo=ciclo, box_cicli=box_cicli,
                           box_cicli_attivi=box_cicli_attivi, eventi=eventi,
                           lotti_info=lotti_info, lettere_miste=lettere_miste,
                           nomi_mesi=NOMI_MESI, lettere_mesi=LETTERE_MESI)


@bp.route("/cicli/<int:id>/aggiungi_lotto", methods=["GET", "POST"])
@login_required
@write_required
def cicli_aggiungi_lotto(id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    if ciclo.stato != "attivo":
        flash("Il ciclo non è attivo.", "warning")
        return redirect(url_for("allevamento.cicli_detail", id=id))

    all_boxes = Box.query.order_by(Box.numero).all()
    numero_lotto = ciclo.lotti.count() + 1

    # Box già nel ciclo: numero_box -> bc
    ciclo_bc = {
        bc.box.numero: bc
        for bc in ciclo.box_cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).all()
    }

    box_map = {}
    for b in all_boxes:
        if b.numero in ciclo_bc:
            box_map[b.numero] = {
                "id": b.id,
                "capannone": b.capannone.numero,
                "linea": b.linea_alimentazione,
                "capienza": int(b.superficie_m2) if b.superficie_m2 else 0,
                "stato": "in_ciclo",
            }
        else:
            altro = b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first()
            box_map[b.numero] = {
                "id": b.id,
                "capannone": b.capannone.numero,
                "linea": b.linea_alimentazione,
                "capienza": int(b.superficie_m2) if b.superficie_m2 else 0,
                "stato": "libero" if not altro else "occupato",
                "libero": not bool(altro),
            }

    if request.method == "POST":
        data_cons_str = request.form.get("data_consegna", str(date.today()))
        peso_totale_bolla = float(request.form.get("peso_totale_bolla", 0) or 0)
        lettera = request.form.get("lettera_nascita", "").strip().upper() or None
        fornitore = request.form.get("fornitore", "").strip() or None
        numero_documento = request.form.get("numero_documento", "").strip() or None
        note = request.form.get("note", "").strip()

        box_capi = {}
        for b in all_boxes:
            if b.numero in ciclo_bc:
                continue  # box già nel ciclo, non riaccasare
            val = request.form.get(f"capi_box_{b.id}", "").strip()
            if val:
                try:
                    n = int(val)
                    if n > 0:
                        box_capi[b.id] = n
                except ValueError:
                    pass

        if not box_capi:
            flash("Seleziona almeno un box libero con i capi.", "danger")
            return render_template("allevamento/cicli/aggiungi_lotto.html",
                                   ciclo=ciclo, box_map=box_map,
                                   numero_lotto=numero_lotto, today=date.today(),
                                   lettere_mesi=LETTERE_MESI, nomi_mesi=NOMI_MESI)

        capi_effettivi = sum(box_capi.values())
        data_consegna = date.fromisoformat(data_cons_str)
        peso_medio = (peso_totale_bolla / capi_effettivi) if capi_effettivi > 0 else 0.0
        eta_stimata = _eta_da_peso(peso_medio) if peso_medio > 0 else None

        lotto = Lotto(
            ciclo_id=ciclo.id,
            numero_lotto=numero_lotto,
            data_consegna=data_consegna,
            peso_totale_bolla_kg=peso_totale_bolla if peso_totale_bolla else None,
            lettera_nascita=lettera,
            fornitore=fornitore,
            numero_documento=numero_documento,
            note=note,
            created_by=current_user.id,
        )
        db.session.add(lotto)
        db.session.flush()

        for bid, capi_box in box_capi.items():
            peso_box = (peso_totale_bolla / capi_effettivi * capi_box) if capi_effettivi else 0
            bc = BoxCiclo(
                ciclo_id=ciclo.id,
                lotto_id=lotto.id,
                lettera_nascita=lettera,
                box_id=bid,
                data_accasamento=data_consegna,
                capi_iniziali=capi_box,
                peso_totale_iniziale=round(peso_box, 1),
                peso_medio_iniziale=round(peso_medio, 2) if peso_medio else None,
                eta_stimata_gg=eta_stimata,
                capi_presenti=capi_box,
                stato="attivo",
            )
            db.session.add(bc)

        db.session.commit()
        flash(f"Lotto {numero_lotto} aggiunto al ciclo con {capi_effettivi} capi.", "success")
        return redirect(url_for("allevamento.cicli_detail", id=id))

    return render_template("allevamento/cicli/aggiungi_lotto.html",
                           ciclo=ciclo, box_map=box_map,
                           numero_lotto=numero_lotto, today=date.today(),
                           lettere_mesi=LETTERE_MESI, nomi_mesi=NOMI_MESI)


@bp.route("/cicli/<int:id>/lotti/<int:lotto_id>/modifica", methods=["POST"])
@login_required
@write_required
def cicli_modifica_lotto(id, lotto_id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    lotto = Lotto.query.filter_by(id=lotto_id, ciclo_id=id).first_or_404()

    data_consegna_str = request.form.get("data_consegna", "").strip()
    if data_consegna_str:
        try:
            lotto.data_consegna = date.fromisoformat(data_consegna_str)
        except ValueError:
            flash("Data consegna non valida.", "danger")
            return redirect(url_for("allevamento.cicli_detail", id=id))

    lettera = request.form.get("lettera_nascita", "").strip().upper() or None
    if lettera and lettera not in LETTERE_MESI:
        flash("Lettera DOP non valida.", "danger")
        return redirect(url_for("allevamento.cicli_detail", id=id))
    lotto.lettera_nascita = lettera

    peso_str = request.form.get("peso_totale_bolla_kg", "").strip()
    lotto.peso_totale_bolla_kg = float(peso_str) if peso_str else None

    lotto.fornitore = request.form.get("fornitore", "").strip() or None
    lotto.numero_documento = request.form.get("numero_documento", "").strip() or None
    lotto.note = request.form.get("note", "").strip() or None

    # Aggiorna lettera_nascita e data_accasamento sui BoxCiclo del lotto
    for bc in lotto.box_cicli:
        if lettera:
            bc.lettera_nascita = lettera
        bc.data_accasamento = lotto.data_consegna

    db.session.commit()
    flash(f"Lotto {lotto.numero_lotto} aggiornato.", "success")
    return redirect(url_for("allevamento.cicli_detail", id=id))


@bp.route("/cicli/<int:id>/riaccasamento", methods=["GET", "POST"])
@login_required
@write_required
def cicli_riaccasamento(id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    if ciclo.stato != "attivo":
        flash("Il ciclo non è attivo.", "warning")
        return redirect(url_for("allevamento.cicli_detail", id=id))

    all_boxes = Box.query.order_by(Box.numero).all()

    # BoxCiclo attivi/in_uscita del ciclo: numero_box -> bc
    ciclo_bc = {
        bc.box.numero: bc
        for bc in ciclo.box_cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).all()
    }

    # Mappa completa per SVG: numero_box -> info
    box_map = {}
    for b in all_boxes:
        if b.numero in ciclo_bc:
            bc = ciclo_bc[b.numero]
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

    capi_totali_prima = sum(bc.capi_presenti or 0 for bc in ciclo_bc.values())

    # Calcola peso ed età attuale stimata per ogni BoxCiclo (per mostrarlo nel form)
    oggi = date.today()
    curva_obj = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).all()
    curva_json = [{"eta": c.eta_giorni, "peso": round(c.peso_kg, 1)} for c in curva_obj]
    bc_extra = {}
    for bc in ciclo_bc.values():
        eta_acc = bc.eta_stimata_gg or 0
        giorni = (oggi - bc.data_accasamento).days if bc.data_accasamento else 0
        eta_att = eta_acc + giorni
        peso_att = _peso_da_eta(eta_att)
        bc_extra[bc.id] = {
            "eta_attuale_gg": eta_att,
            "peso_attuale_stima": peso_att,
        }

    if request.method == "POST":
        data_str = request.form.get("data_riaccasamento", str(date.today()))
        data_riaccasamento = date.fromisoformat(data_str)

        # Aggiorna box già nel ciclo
        for box_num, bc in ciclo_bc.items():
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
                eta_alla_pesatura = _eta_da_peso(nuovi_peso)
                if eta_alla_pesatura is not None and bc.data_accasamento:
                    giorni_trascorsi = (data_riaccasamento - bc.data_accasamento).days
                    bc.eta_stimata_gg = eta_alla_pesatura - giorni_trascorsi
                else:
                    bc.eta_stimata_gg = eta_alla_pesatura

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
            if b.numero in ciclo_bc:
                continue
            val_capi = request.form.get(f"capi_box_{b.id}", "").strip()
            val_peso = request.form.get(f"peso_box_{b.id}", "").strip()
            if not val_capi or int(val_capi) <= 0:
                continue
            if b.cicli.filter(BoxCiclo.stato.in_(["attivo", "in_uscita"])).first():
                continue

            nuovi_capi = int(val_capi)
            nuovi_peso = float(val_peso) if val_peso else None
            # Se peso non specificato, eredita media del ciclo
            if not nuovi_peso:
                pesi = [bc.peso_medio_iniziale for bc in ciclo_bc.values() if bc.peso_medio_iniziale]
                nuovi_peso = round(sum(pesi) / len(pesi), 2) if pesi else None
            eta = _eta_da_peso(nuovi_peso) if nuovi_peso else None

            bc_new = BoxCiclo(
                ciclo_id=ciclo.id, box_id=b.id,
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
        _rigenera_stime_ciclo(ciclo, data_da=data_riaccasamento)
        flash("Riaccasamento registrato.", "success")
        return redirect(url_for("allevamento.cicli_detail", id=id))

    return render_template("allevamento/cicli/riaccasamento.html",
                           ciclo=ciclo, box_map=box_map,
                           ciclo_bc=ciclo_bc,
                           capi_totali_prima=capi_totali_prima,
                           bc_extra=bc_extra,
                           curva_json=curva_json,
                           today=date.today())


@bp.route("/cicli/<int:id>/chiudi", methods=["POST"])
@login_required
@write_required
def cicli_chiudi(id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    if ciclo.stato == "chiuso":
        flash("Ciclo già chiuso.", "warning")
        return redirect(url_for("allevamento.cicli_detail", id=id))
    ciclo.stato = "chiuso"
    ciclo.data_chiusura = date.today()
    for bc in ciclo.box_cicli.all():
        bc.stato = "chiuso"
    db.session.commit()
    flash(f"Ciclo {ciclo.ciclo_id} chiuso.", "success")
    return redirect(url_for("allevamento.cicli_index"))


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
        data_str = request.form.get("data", str(date.today()))
        note = request.form.get("note", "").strip()
        is_scarti = request.form.get("is_scarti") == "1"
        data_ev = date.fromisoformat(data_str)

        if tipo == "uscita_macello":
            # Multi-box: uno o più box selezionati con checkbox
            box_ciclo_ids = request.form.getlist("box_ciclo_id")
            peso_totale_camion = float(request.form.get("peso_totale", 0) or 0)
            capi_per_box = {}
            for bc_id in box_ciclo_ids:
                c = int(request.form.get(f"capi_box_{bc_id}", 0) or 0)
                if c > 0:
                    capi_per_box[int(bc_id)] = c

            if not capi_per_box:
                flash("Nessun capo selezionato per l'uscita macello.", "warning")
                return redirect(url_for("allevamento.eventi_nuovo"))

            capi_totali = sum(capi_per_box.values())
            ciclo_ref = None
            for bc_id, capi in capi_per_box.items():
                bc = BoxCiclo.query.get_or_404(bc_id)
                if ciclo_ref is None:
                    ciclo_ref = bc.ciclo
                peso_box = round(peso_totale_camion * capi / capi_totali, 1) if capi_totali > 0 else None
                db.session.add(EventoCiclo(
                    box_ciclo_id=bc_id, tipo="uscita_macello", data=data_ev,
                    quantita=capi, peso_totale=peso_box, note=note,
                    operatore_id=current_user.id, is_scarti=is_scarti,
                ))
                bc.capi_presenti = max(0, (bc.capi_presenti or 0) - capi)
                if bc.capi_presenti == 0:
                    bc.stato = "chiuso"

            # Controlla se tutto il ciclo è chiuso
            if ciclo_ref and all(b.stato == "chiuso" for b in ciclo_ref.box_cicli.all()):
                ciclo_ref.stato = "chiuso"
                ciclo_ref.data_chiusura = date.today()

            db.session.commit()
            if ciclo_ref:
                _rigenera_stime_ciclo(ciclo_ref, data_da=data_ev)
            n_box = len(capi_per_box)
            flash(f"Uscita macello registrata: {capi_totali} capi da {n_box} box.", "success")
            ciclo_id = ciclo_ref.id if ciclo_ref else None
            return redirect(url_for("allevamento.cicli_detail", id=ciclo_id) if ciclo_id
                            else url_for("allevamento.cicli_index"))

        # Tutti gli altri tipi: singolo box
        box_ciclo_id = int(request.form.get("box_ciclo_id", 0))
        quantita = int(request.form.get("quantita", 0) or 0)
        peso_totale = float(request.form.get("peso_totale", 0) or 0)
        bc = BoxCiclo.query.get_or_404(box_ciclo_id)
        ev = EventoCiclo(
            box_ciclo_id=box_ciclo_id, tipo=tipo, data=data_ev,
            quantita=quantita,
            peso_totale=peso_totale if peso_totale else None,
            note=note, operatore_id=current_user.id, is_scarti=is_scarti,
        )
        db.session.add(ev)

        if tipo == "mortalita":
            bc.capi_presenti = max(0, (bc.capi_presenti or 0) - quantita)
        elif tipo == "frazionamento_out":
            bc.capi_presenti = max(0, (bc.capi_presenti or 0) - quantita)
            dest_bc_id = int(request.form.get("dest_box_ciclo_id", 0) or 0)
            if dest_bc_id:
                dest_bc = BoxCiclo.query.get(dest_bc_id)
                if dest_bc:
                    dest_bc.capi_presenti = (dest_bc.capi_presenti or 0) + quantita
                    db.session.add(EventoCiclo(
                        box_ciclo_id=dest_bc_id, tipo="frazionamento_in", data=data_ev,
                        quantita=quantita,
                        note=f"Da box {bc.box.numero} – {note}",
                        operatore_id=current_user.id,
                    ))

        db.session.commit()
        _rigenera_stime_ciclo(bc.ciclo, data_da=data_ev)
        flash(f"Evento '{tipo}' registrato ({quantita} capi).", "success")
        return redirect(url_for("allevamento.cicli_detail", id=bc.ciclo_id))

    # GET: eventuale preselect da query string
    preselect_bc = request.args.get("bc")
    return render_template("allevamento/eventi/form.html",
                           cicli_attivi=cicli_attivi, preselect_bc=preselect_bc,
                           today=date.today())


@bp.route("/eventi/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def cicli_evento_modifica(id):
    """Modifica data/quantita/peso/note di un EventoCiclo esistente."""
    ev = EventoCiclo.query.get_or_404(id)
    bc = ev.box_ciclo
    ciclo = bc.ciclo

    if request.method == "POST":
        data_str = request.form.get("data", str(ev.data))
        nuova_data = date.fromisoformat(data_str)
        nuova_quantita = int(request.form.get("quantita", ev.quantita or 0) or 0)
        nuovo_peso_str = request.form.get("peso_totale", "").strip()
        nuovo_peso = float(nuovo_peso_str) if nuovo_peso_str else None
        note = request.form.get("note", "").strip()

        # Se la quantità cambia, aggiusta capi_presenti con il delta
        old_qty = ev.quantita or 0
        if nuova_quantita != old_qty:
            delta = old_qty - nuova_quantita  # positivo = ripristino capi
            if ev.tipo in ("mortalita", "frazionamento_out", "uscita_macello"):
                bc.capi_presenti = max(0, (bc.capi_presenti or 0) + delta)
            elif ev.tipo == "frazionamento_in":
                bc.capi_presenti = max(0, (bc.capi_presenti or 0) - delta)

        old_data = ev.data
        ev.data = nuova_data
        ev.quantita = nuova_quantita
        ev.peso_totale = nuovo_peso
        ev.note = note
        db.session.commit()
        _rigenera_stime_ciclo(ciclo, data_da=min(old_data, nuova_data))
        flash("Evento aggiornato.", "success")
        return redirect(url_for("allevamento.cicli_detail", id=ciclo.id))

    return render_template("allevamento/eventi/modifica.html", ev=ev, ciclo=ciclo, today=date.today())


@bp.route("/eventi/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def cicli_evento_elimina(id):
    """Elimina un EventoCiclo e ripristina lo stato conseguente."""
    ev = EventoCiclo.query.get_or_404(id)
    bc = ev.box_ciclo
    ciclo = bc.ciclo
    data_evento = ev.data

    # Ripristina capi_presenti
    if ev.tipo in ("mortalita", "frazionamento_out", "uscita_macello"):
        bc.capi_presenti = (bc.capi_presenti or 0) + (ev.quantita or 0)
        if bc.stato == "chiuso" and bc.capi_presenti > 0:
            bc.stato = "in_uscita"
        if ciclo.stato == "chiuso":
            ciclo.stato = "attivo"
            ciclo.data_chiusura = None
    elif ev.tipo == "frazionamento_in":
        bc.capi_presenti = max(0, (bc.capi_presenti or 0) - (ev.quantita or 0))

    db.session.delete(ev)
    db.session.commit()
    _rigenera_stime_ciclo(ciclo, data_da=data_evento)
    flash("Evento eliminato.", "success")
    return redirect(url_for("allevamento.cicli_detail", id=ciclo.id))


@bp.route("/cicli/<int:id>/rigenera_stime", methods=["POST"])
@login_required
@write_required
def cicli_rigenera_stime(id):
    """Rigenera le stime teoriche dall'inizio del ciclo a oggi (solo admin)."""
    if current_user.role != "admin":
        flash("Azione riservata agli amministratori.", "danger")
        return redirect(url_for("allevamento.cicli_detail", id=id))
    ciclo = CicloProduttivo.query.get_or_404(id)
    _rigenera_stime_ciclo(ciclo)
    flash("Stime teoriche rigenerate dall'inizio del ciclo a oggi.", "success")
    return redirect(url_for("allevamento.cicli_detail", id=id))


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
    import json as _json
    oggi = date.today()
    orari_pasto = OrarioPasto.query.filter_by(attivo=True).order_by(OrarioPasto.numero).all()
    num_pasti = len(orari_pasto)
    razioni = {}
    pasti_json = {}  # {linea: {numero_pasto: {m, s, a}}} per JS
    for linea in [1, 2, 3]:
        mangime, siero, acqua, boxes_det = _calcola_razioni_linea_dettaglio(linea)
        razione_db = RazioneGiornaliera.query.filter_by(data=oggi, linea=linea).first()
        pasti_oggi = RazionePasto.query.filter_by(data=oggi, linea=linea).order_by(RazionePasto.numero_pasto).all()
        # Serializza pasti per JS
        pasti_linea = {}
        for op in orari_pasto:
            rp = next((p for p in pasti_oggi if p.numero_pasto == op.numero), None)
            pasti_linea[op.numero] = {
                "m": rp.consumo_mangime_kg if rp and rp.consumo_mangime_kg is not None else None,
                "s": rp.consumo_siero_litri if rp and rp.consumo_siero_litri is not None else None,
                "a": rp.consumo_acqua_litri if rp and rp.consumo_acqua_litri is not None else None,
            }
        pasti_json[linea] = pasti_linea
        razioni[linea] = {
            "teorica_mangime": mangime,
            "teorica_siero": siero,
            "teorica_acqua": acqua,
            "consumo_mangime": razione_db.consumo_mangime_kg if razione_db else None,
            "consumo_siero": razione_db.consumo_siero_litri if razione_db else None,
            "consumo_acqua": razione_db.consumo_acqua_litri if razione_db else None,
            "note": razione_db.note if razione_db else "",
            "pasti": pasti_oggi,
            "boxes": boxes_det,
            "n_capi": sum(b["capi"] for b in boxes_det),
        }
    return render_template("allevamento/alimentazione/index.html",
                           razioni=razioni, oggi=oggi, orari_pasto=orari_pasto,
                           num_pasti=num_pasti, pasti_json=pasti_json)


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
    oggi = date.today()

    # Filtro periodo (default: ultimi 7 giorni)
    da_str = request.args.get("da", "")
    a_str = request.args.get("a", "")
    data_da = date.fromisoformat(da_str) if da_str else oggi - timedelta(days=6)
    data_a = date.fromisoformat(a_str) if a_str else oggi

    # Inizio del ciclo attivo più vecchio (per "tutto ciclo")
    cicli_attivi = CicloProduttivo.query.filter_by(stato="attivo").all()
    data_inizio_ciclo = min((c.data_inizio for c in cicli_attivi), default=None)

    # Totali per l'intero ciclo attivo
    totali_ciclo = {1: None, 2: None, 3: None}
    if data_inizio_ciclo:
        razioni_all = RazioneGiornaliera.query.filter(
            RazioneGiornaliera.data >= data_inizio_ciclo,
            RazioneGiornaliera.data <= oggi,
        ).all()
        for linea in (1, 2, 3):
            rl = [r for r in razioni_all if r.linea == linea]
            if not rl:
                continue
            reali = [r for r in rl if not r.is_stima]
            stime = [r for r in rl if r.is_stima]
            totali_ciclo[linea] = {
                "mangime_reale": round(sum(r.consumo_mangime_kg or 0 for r in reali), 0),
                "mangime_stima": round(sum(r.consumo_mangime_kg or 0 for r in stime), 0),
                "siero_reale": round(sum(r.consumo_siero_litri or 0 for r in reali), 0),
                "siero_stima": round(sum(r.consumo_siero_litri or 0 for r in stime), 0),
                "acqua_reale": round(sum(r.consumo_acqua_litri or 0 for r in reali), 0),
                "acqua_stima": round(sum(r.acqua_teorica_litri or 0 for r in stime), 0),
                "n_reali": len(reali),
                "n_stima": len(stime),
            }

    # Razioni nel periodo filtrato
    razioni = RazioneGiornaliera.query.filter(
        RazioneGiornaliera.data >= data_da,
        RazioneGiornaliera.data <= data_a,
    ).order_by(RazioneGiornaliera.data.desc(), RazioneGiornaliera.linea).all()

    pasti = RazionePasto.query.filter(
        RazionePasto.data >= data_da,
        RazionePasto.data <= data_a,
    ).order_by(
        RazionePasto.data.desc(), RazionePasto.linea, RazionePasto.numero_pasto
    ).all()

    # Aggrega per data → una riga per giorno
    from collections import OrderedDict
    razioni_per_data = OrderedDict()
    for r in razioni:
        razioni_per_data.setdefault(r.data, []).append(r)
    pasti_per_data = {}
    for p in pasti:
        pasti_per_data.setdefault(p.data, []).append(p)

    giornate = []
    for d, rs in razioni_per_data.items():
        reali = [r for r in rs if not r.is_stima]
        stime = [r for r in rs if r.is_stima]
        tot_mangime = round(sum(r.consumo_mangime_kg or 0 for r in rs), 1)
        tot_siero = round(sum(r.consumo_siero_litri or 0 for r in rs), 1)
        # Acqua: usa reale se disponibile, altrimenti teorica
        tot_acqua = round(sum(
            (r.consumo_acqua_litri if (not r.is_stima and r.consumo_acqua_litri is not None)
             else (r.acqua_teorica_litri or 0))
            for r in rs
        ), 0)
        # Delta mangime vs teorico (solo per linee reali)
        delta_mangime = None
        if reali:
            mr = sum(r.consumo_mangime_kg or 0 for r in reali)
            mt = sum(r.razione_teorica_kg or 0 for r in reali)
            if mt > 0:
                delta_mangime = round(mr - mt, 1)
        giornate.append({
            "data": d,
            "razioni": rs,
            "pasti": pasti_per_data.get(d, []),
            "tot_mangime": tot_mangime,
            "tot_siero": tot_siero,
            "tot_acqua": int(tot_acqua),
            "delta_mangime": delta_mangime,
            "n_reali": len(reali),
            "n_stima": len(stime),
        })

    # Totali del periodo filtrato
    periodo_totali = {
        "mangime": round(sum(g["tot_mangime"] for g in giornate), 1),
        "siero": round(sum(g["tot_siero"] for g in giornate), 1),
        "acqua": int(sum(g["tot_acqua"] for g in giornate)),
        "n_reali": sum(g["n_reali"] for g in giornate),
        "n_stima": sum(g["n_stima"] for g in giornate),
    }

    # Date quick-filter da passare al template
    quick = {
        "7": oggi - timedelta(days=6),
        "30": oggi - timedelta(days=29),
        "90": oggi - timedelta(days=89),
        "ciclo": data_inizio_ciclo,
    }

    return render_template(
        "allevamento/alimentazione/storico.html",
        giornate=giornate, pasti=pasti, vista=vista,
        data_da=data_da, data_a=data_a, oggi=oggi,
        totali_ciclo=totali_ciclo,
        data_inizio_ciclo=data_inizio_ciclo,
        periodo_totali=periodo_totali,
        quick=quick,
    )


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
    """Upsert di un record Setting: crea se non esiste, aggiorna se esiste."""
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
        tipo_prodotto = request.form.get("tipo_prodotto", "").strip() or None
        note = request.form.get("note", "").strip()

        consegna = ConsegnaAlimentare(
            tipo=tipo,
            data=date.fromisoformat(data_str),
            quantita_q=quantita,
            fornitore=fornitore,
            percentuale_ss_siero=float(perc_ss) if perc_ss else None,
            tipo_prodotto=tipo_prodotto,
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

@bp.route("/report")
@login_required
def report_index():
    cicli = CicloProduttivo.query.order_by(CicloProduttivo.data_inizio.desc()).all()
    return render_template("allevamento/report/index.html", cicli=cicli)


@bp.route("/report/ciclo/<int:id>")
@login_required
def report_ciclo(id):
    ciclo = CicloProduttivo.query.get_or_404(id)
    box_cicli_all = ciclo.box_cicli.all()
    # Solo attivi per la tabella (evita duplicati se stesso box riaccasato)
    box_cicli = ciclo.box_cicli.filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"])
    ).order_by(BoxCiclo.box_id).all()
    bc_ids_all = [bc.id for bc in box_cicli_all]

    eventi = EventoCiclo.query.filter(
        EventoCiclo.box_ciclo_id.in_(bc_ids_all)
    ).order_by(EventoCiclo.data).all() if bc_ids_all else []

    # Calcolo statistiche su tutti i box_cicli (inclusi chiusi) per completezza storica
    capi_iniziali_tot = sum(bc.capi_iniziali for bc in box_cicli_all)
    capi_finali = sum(bc.capi_presenti or 0 for bc in box_cicli_all)
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

    if ciclo.data_chiusura:
        durata_gg = (ciclo.data_chiusura - ciclo.data_inizio).days
    else:
        durata_gg = (date.today() - ciclo.data_inizio).days

    # Totali consegne mangime/siero nel periodo del ciclo
    data_fine_ciclo = ciclo.data_chiusura or date.today()
    mangime_totale_q = db.session.query(db.func.sum(ConsegnaAlimentare.quantita_q))\
        .filter(ConsegnaAlimentare.tipo == "mangime",
                ConsegnaAlimentare.data >= ciclo.data_inizio,
                ConsegnaAlimentare.data <= data_fine_ciclo).scalar() or 0
    siero_totale_q = db.session.query(db.func.sum(ConsegnaAlimentare.quantita_q))\
        .filter(ConsegnaAlimentare.tipo == "siero",
                ConsegnaAlimentare.data >= ciclo.data_inizio,
                ConsegnaAlimentare.data <= data_fine_ciclo).scalar() or 0

    return render_template("allevamento/report/ciclo.html",
                           ciclo=ciclo, box_cicli=box_cicli, eventi=eventi,
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
                           durata_gg=durata_gg,
                           mangime_totale_q=mangime_totale_q,
                           siero_totale_q=siero_totale_q)


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
