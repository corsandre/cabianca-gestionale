"""Avvisi giornalieri dell'allevamento su Telegram (gruppo allevamento).

Ogni minuto lo scheduler chiama controlla(): passato l'orario impostato (Impostazioni allevamento,
allevamento_orario_avvisi, default 07:00) manda gli avvisi del giorno una volta sola (il giorno
dell'ultimo invio è in allevamento_avvisi_inviati_il, così un riavvio non li ripete).
Avvisi: trattamenti con una dose da ripetere oggi, raggruppati per animale (medicinali dati insieme
allo stesso animale) con il colore del marcatore e la riga da fare sulla schiena. Se non c'è niente da
dire, nessun messaggio.
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
    """Righe di testo, una per animale (o gruppo di animali), con i medicinali da dare oggi. Con il colore
    del marcatore si indica anche quale riga fare sulla schiena (una per giorno di trattamento)."""
    from app.models import Ciclo
    from app.services.allevamento_trattamenti import da_ripetere_per_animale, riga_ordinale
    ciclo = Ciclo.query.filter_by(attivo=True).first()
    if not ciclo:
        return []
    righe = []
    for g in da_ripetere_per_animale(ciclo.id):
        dosi = []
        for t, s in g["trattamenti"]:
            ml = f", {s['dose_totale_ml']:.0f} ml in tutto".replace(".", ",") if s["dose_totale_ml"] else ""
            dosi.append(f"<b>{html.escape(t.medicinale.nome)}</b> dose {s['fatte'] + 1} di {s['totali']}{ml}")
        riga = f" → fai la <b>{riga_ordinale(g['riga'])}</b>" if g["colore"] else ""
        righe.append(f"• {html.escape(g['animale'])}: " + "; ".join(dosi) + riga)
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
