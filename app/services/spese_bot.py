"""Pulsanti e risposte del bot Telegram per le spese da descrivere (vedi spese_carta.py).

Il gruppo della finanza di solito riceve solo notifiche: qui il bot accetta soltanto i pulsanti
"spesa:..." e le risposte scritte ai propri messaggi di spesa.
"""

import logging

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler, filters

logger = logging.getLogger(__name__)


def ammesso_nel_gruppo_finanza(update: Update) -> bool:
    q = update.callback_query
    if q and (q.data or "").startswith("spesa:"):
        return True
    msg = update.effective_message
    return bool(msg and msg.text and msg.reply_to_message and msg.reply_to_message.from_user
                and msg.reply_to_message.from_user.is_bot)


def registra_gestori(tg_app, app):
    from app.services import spese_carta

    async def pulsante(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        try:
            _, rid, scelta = q.data.split(":", 2)
            utente = q.from_user.first_name or str(q.from_user.id)
            with app.app_context():
                testo = spese_carta.registra(int(rid), scelta, utente)
            await q.answer()
            await q.edit_message_text(testo, parse_mode="HTML")
        except Exception as e:
            logger.exception(f"Spese: pulsante non gestito ({q.data}): {e}")
            await q.answer("Errore: registra la spesa dal gestionale.", show_alert=True)

    async def risposta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        utente = msg.from_user.first_name or str(msg.from_user.id)
        with app.app_context():
            esito = spese_carta.aggiungi_descrizione(msg.chat_id, msg.reply_to_message.message_id, msg.text, utente)
        if esito:
            await msg.reply_text(esito)

    tg_app.add_handler(CallbackQueryHandler(pulsante, pattern=r"^spesa:"), group=1)
    tg_app.add_handler(MessageHandler(filters.REPLY & filters.TEXT & ~filters.COMMAND, risposta), group=1)
