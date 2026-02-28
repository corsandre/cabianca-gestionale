"""Generazione allarmi automatici per la sezione Allevamento Suini."""
from datetime import datetime, date, timedelta
from app import db
from app.models import (
    Allarme, BoxCiclo, TrattamentoSanitario, MagazzinoProdotto,
    ManutenzioneBox, CurvaAccrescimento, Setting
)


def _setting(key, default):
    s = Setting.query.get(key)
    return float(s.value) if s else default


def rigenera_allarmi():
    """Job giornaliero (h06:00): rigenera allarmi attivi per l'allevamento."""
    oggi = date.today()
    now = datetime.utcnow()

    # Rimuovi allarmi già risolti o generati automaticamente (non silenziati)
    Allarme.query.filter(
        Allarme.stato == "attivo",
        Allarme.silenziato_fino == None,
        Allarme.tipo.in_([
            "trattamento_in_corso", "scorta_bassa", "fine_ciclo_imminente",
            "manutenzione_scaduta", "densita_eccessiva"
        ])
    ).delete(synchronize_session=False)
    db.session.flush()

    soglia_macellazione_gg = int(_setting("allevamento_eta_macellazione_gg", 260))
    avviso_macellazione_gg = int(_setting("allevamento_avviso_macellazione_gg", 14))

    # 1. Trattamenti in corso oggi
    trattamenti_attivi = TrattamentoSanitario.query.join(BoxCiclo).filter(
        BoxCiclo.stato.in_(["attivo", "in_uscita"]),
        TrattamentoSanitario.data_inizio <= oggi,
    ).all()
    for t in trattamenti_attivi:
        fine = t.data_inizio + timedelta(days=t.durata_giorni - 1)
        if fine >= oggi:
            box_num = t.box_ciclo.box.numero if t.box_ciclo and t.box_ciclo.box else "?"
            db.session.add(Allarme(
                tipo="trattamento_in_corso",
                messaggio=f"Box {box_num}: trattamento '{t.farmaco or t.tipo}' in corso (fino al {fine.strftime('%d/%m')})",
                riferimento_tipo="trattamento",
                riferimento_id=t.id,
                data_scadenza=datetime.combine(fine, datetime.min.time()),
            ))

    # 2. Scorte sotto soglia minima
    for mp in MagazzinoProdotto.query.all():
        if mp.quantita_attuale_q < mp.soglia_minima_q:
            db.session.add(Allarme(
                tipo="scorta_bassa",
                messaggio=f"Scorta {mp.tipo} sotto soglia: {mp.quantita_attuale_q:.1f} q (min {mp.soglia_minima_q:.1f} q)",
                riferimento_tipo="magazzino",
                riferimento_id=mp.id,
            ))

    # 3. Fine ciclo imminente (età > soglia - avviso)
    curva_max = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni.desc()).first()
    for bc in BoxCiclo.query.filter_by(stato="attivo").all():
        if bc.eta_stimata_gg and bc.data_accasamento:
            eta_oggi = bc.eta_stimata_gg + (oggi - bc.data_accasamento).days
            if eta_oggi >= soglia_macellazione_gg - avviso_macellazione_gg:
                box_num = bc.box.numero if bc.box else "?"
                db.session.add(Allarme(
                    tipo="fine_ciclo_imminente",
                    messaggio=f"Box {box_num}: età stimata {eta_oggi} gg, vicino alla macellazione",
                    riferimento_tipo="box_ciclo",
                    riferimento_id=bc.id,
                ))

    # 4. Manutenzioni scadute
    for m in ManutenzioneBox.query.filter_by(stato="da_fare").all():
        if m.scadenza and m.scadenza < oggi:
            soggetto = f"Box {m.box.numero}" if m.box else (f"CAP {m.capannone.numero}" if m.capannone else "Generale")
            db.session.add(Allarme(
                tipo="manutenzione_scaduta",
                messaggio=f"{soggetto}: manutenzione scaduta il {m.scadenza.strftime('%d/%m/%Y')} – {m.tipo_attivita}",
                riferimento_tipo="manutenzione",
                riferimento_id=m.id,
            ))

    db.session.commit()
