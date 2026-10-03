"""Avvisi giornalieri dell'allevamento su Telegram (gruppo allevamento).

Ogni minuto lo scheduler chiama controlla(): passato l'orario impostato (Impostazioni allevamento,
allevamento_orario_avvisi, default 07:00) manda gli avvisi del giorno una volta sola (il giorno
dell'ultimo invio è in allevamento_avvisi_inviati_il, così un riavvio non li ripete).
Avvisi: trattamenti con una dose da ripetere oggi. Se non c'è niente da dire, nessun messaggio.
"""
import html
import logging
from datetime import date, datetime

from app import db

log = logging.getLogger(__name__)
ORARIO_DEFAULT = "07:00"


def orario_avvisi():
    from app.models import Setting
    s = db.session.get(Setting, "allevamento_orario_avvisi")
    return (s.value if s and s.value else ORARIO_DEFAULT)


def trattamenti_da_ripetere():
    """Righe di testo dei trattamenti del ciclo attivo con una dose da fare oggi."""
    from app.models import Ciclo, Trattamento
    from app.routes.allevamento import _stato_trattamento
    ciclo = Ciclo.query.filter_by(attivo=True).first()
    if not ciclo:
        return []
    righe = []
    for t in Trattamento.query.filter_by(ciclo_id=ciclo.id).order_by(Trattamento.data_inizio).all():
        s = _stato_trattamento(t)
        if not s["da_ripetere"]:
            continue
        ambito = f"box {t.box_numero}" if t.box_numero else f"CAP {t.capannone_numero} (tutto)"
        dose = f", {s['dose_totale_ml']:.0f} ml in tutto".replace(".", ",") if s["dose_totale_ml"] else ""
        righe.append(f"• <b>{html.escape(t.medicinale.nome)}</b> – {ambito}: dose {s['fatte'] + 1} di {s['totali']}{dose}")
    return righe


def messaggio_del_giorno():
    righe = trattamenti_da_ripetere()
    if not righe:
        return None
    return ("💊 <b>Trattamenti da ripetere oggi</b>\n" + "\n".join(righe) +
            "\n\nPer registrarle: bot → 💊 Trattamenti → Da fare oggi.")


def controlla(adesso=None):
    from app.models import Setting
    from app.services.telegram_bot import send_telegram_message
    adesso = adesso or datetime.now()
    if adesso.strftime("%H:%M") < orario_avvisi():
        return
    s = db.session.get(Setting, "allevamento_avvisi_inviati_il")
    if s and s.value == adesso.date().isoformat():
        return
    testo = messaggio_del_giorno()
    if s:
        s.value = adesso.date().isoformat()
    else:
        db.session.add(Setting(key="allevamento_avvisi_inviati_il", value=adesso.date().isoformat()))
    db.session.commit()
    if testo:
        send_telegram_message(testo, "allevamento")
        log.info("avvisi giornalieri inviati")
