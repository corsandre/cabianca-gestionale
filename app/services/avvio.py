"""Messaggio su Telegram (gruppo delle notifiche di sistema) a ogni avvio del gestionale.

Dice la versione, se il bot è connesso e in che modalità è il collegamento all'impianto, e perché è
ripartito: aggiornamento (versione diversa dall'ultimo avvio), server riacceso (il sistema è acceso da
pochi minuti: es. la VPS spenta dal pannello Contabo il 19/10/2026) o servizio semplicemente riavviato.
"""
import logging

log = logging.getLogger(__name__)
MINUTI_SERVER_APPENA_ACCESO = 15


def _minuti_accensione():
    """Da quanti minuti è acceso il server (nel container /proc/uptime è quello della macchina)."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0]) / 60
    except (OSError, ValueError, IndexError):
        return None


def messaggio_avvio(app):
    from app import db
    from app.models import Setting
    from app.services.allevamento_scorte import set_setting
    from app.services.impianto import modalita, NOMI_MODALITA
    from app.services.telegram_bot import send_telegram_message
    from app.version import VERSIONE
    with app.app_context():
        try:
            s = db.session.get(Setting, "versione_avviata")
            prima = s.value if s else None
            accensione = _minuti_accensione()
            if prima and prima != VERSIONE:
                perche = f"aggiornato dalla versione {prima}"
            elif accensione is not None and accensione < MINUTI_SERVER_APPENA_ACCESO:
                perche = (f"⚠️ <b>il server si è riacceso</b> {round(accensione)} minuti fa, senza aggiornamenti: "
                          f"era spento o è stato riavviato")
            elif prima:
                perche = "ripartito senza aggiornamenti (servizio riavviato)"
            else:
                perche = "aggiornato (primo avvio con questo messaggio)"
            set_setting("versione_avviata", VERSIONE)
            db.session.commit()
            send_telegram_message(f"🔄 <b>Gestionale avviato</b> – versione {VERSIONE}\n{perche}\n"
                                  f"Bot connesso · impianto: {NOMI_MODALITA.get(modalita(), modalita())}", "sistema")
        except Exception as e:
            db.session.rollback()
            log.warning("messaggio di avvio non inviato: %s", e)
