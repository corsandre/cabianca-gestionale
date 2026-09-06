"""
Telegram bot per l'allevamento Ca Bianca v2.
Comandi rapidi per registrare mortalità, spostamenti e consegne direttamente da Telegram.
Richiede TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID nel .env.
"""
import logging
import os
from datetime import date

logger = logging.getLogger(__name__)


def _get_ciclo_attivo(app):
    from app import db
    from app.models import Ciclo
    with app.app_context():
        return Ciclo.query.filter_by(attivo=True).order_by(Ciclo.data_inizio.desc()).first()


def start_bot(app):
    token = app.config.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN non configurato, bot allevamento disabilitato.")
        return

    try:
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
        from telegram.ext import (
            Application, CommandHandler, CallbackQueryHandler,
            ConversationHandler, MessageHandler, filters, ContextTypes,
        )
    except ImportError:
        logger.warning("python-telegram-bot non installato, bot disabilitato.")
        return

    # Stati conversazione
    (
        MAIN_MENU,
        MORTALITA_CAP, MORTALITA_BOX, MORTALITA_QTY, MORTALITA_CAUSA,
        SPOSTAMENTO_TIPO, SPOSTAMENTO_ORIG, SPOSTAMENTO_DEST, SPOSTAMENTO_QTY,
        CONSEGNA_TIPO, CONSEGNA_QTY, CONSEGNA_EXTRA,
    ) = range(12)

    CAPANNONI = [1, 2, 3, 4, 5, 6, 7]
    BOX_PER_CAP = {
        1: list(range(1, 10)), 2: list(range(10, 16)), 3: list(range(16, 22)),
        4: list(range(22, 37)), 5: list(range(37, 43)),
        7: list(range(43, 50)), 6: list(range(50, 55)),
    }

    def kb_capannoni():
        buttons = [InlineKeyboardButton(f"CAP {c}", callback_data=str(c)) for c in CAPANNONI]
        rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
        return InlineKeyboardMarkup(rows)

    def kb_boxes(cap):
        boxes = BOX_PER_CAP.get(cap, [])
        buttons = [InlineKeyboardButton(f"B{b}", callback_data=str(b)) for b in boxes]
        buttons.append(InlineKeyboardButton("→ tutto il CAP", callback_data="0"))
        rows = [buttons[i:i+5] for i in range(0, len(buttons), 5)]
        return InlineKeyboardMarkup(rows)

    def kb_main():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("💀 Registra morte", callback_data="mortalita")],
            [InlineKeyboardButton("🔄 Spostamento", callback_data="spostamento")],
            [InlineKeyboardButton("🚚 Consegna siero", callback_data="consegna_siero"),
             InlineKeyboardButton("🌾 Consegna mangime", callback_data="consegna_mangime")],
            [InlineKeyboardButton("📊 Stato ciclo", callback_data="stato")],
        ])

    async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        with app.app_context():
            from app.models import Ciclo
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            ciclo_txt = f"Ciclo attivo: *{ciclo.nome}*" if ciclo else "⚠️ Nessun ciclo attivo."
        await update.message.reply_text(
            f"🐷 *Ca Bianca Allevamento*\n{ciclo_txt}\n\nCosa vuoi registrare?",
            parse_mode="Markdown",
            reply_markup=kb_main(),
        )
        return MAIN_MENU

    async def menu_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        data = q.data

        if data == "mortalita":
            await q.edit_message_text("💀 *Registra mortalità*\nSeleziona il capannone:", parse_mode="Markdown", reply_markup=kb_capannoni())
            return MORTALITA_CAP
        elif data == "spostamento":
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Entrata", callback_data="entrata"),
                 InlineKeyboardButton("📤 Uscita/Macello", callback_data="uscita"),
                 InlineKeyboardButton("↔️ Interno", callback_data="interno")],
            ])
            await q.edit_message_text("🔄 *Tipo spostamento:*", parse_mode="Markdown", reply_markup=kb)
            return SPOSTAMENTO_TIPO
        elif data == "consegna_siero":
            ctx.user_data["consegna_tipo"] = "siero"
            await q.edit_message_text("🚚 *Consegna siero*\nInserisci i quintali (es: 45.5):", parse_mode="Markdown")
            return CONSEGNA_QTY
        elif data == "consegna_mangime":
            ctx.user_data["consegna_tipo"] = "mangime"
            await q.edit_message_text("🌾 *Consegna mangime*\nInserisci i quintali (es: 80):", parse_mode="Markdown")
            return CONSEGNA_QTY
        elif data == "stato":
            await _send_stato(q, ctx, app)
            return MAIN_MENU

        return MAIN_MENU

    async def _send_stato(q, ctx, app):
        with app.app_context():
            from app.models import Ciclo, EventoMortalita
            from sqlalchemy import func
            from app import db
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await q.edit_message_text("Nessun ciclo attivo.", reply_markup=kb_main())
                return
            morti = db.session.query(func.sum(EventoMortalita.quantita)).filter_by(ciclo_id=ciclo.id).scalar() or 0
            testo = f"📊 *{ciclo.nome}*\nInizio: {ciclo.data_inizio.strftime('%d/%m/%Y')}\nMorti totali: {morti}\n"
        await q.edit_message_text(testo, parse_mode="Markdown", reply_markup=kb_main())

    # ── Mortalità ─────────────────────────────────────────────────────────

    async def mortalita_cap(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["mortalita_cap"] = int(q.data)
        await q.edit_message_text(
            f"CAP {q.data} selezionato.\nSeleziona il box (o 'tutto il CAP'):",
            reply_markup=kb_boxes(int(q.data)),
        )
        return MORTALITA_BOX

    async def mortalita_box(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        box = int(q.data)
        ctx.user_data["mortalita_box"] = box if box > 0 else None
        box_txt = f"Box {box}" if box > 0 else "tutto il CAP"
        await q.edit_message_text(f"📍 {box_txt}\nQuanti capi sono morti? (scrivi il numero)")
        return MORTALITA_QTY

    async def mortalita_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            qty = int(update.message.text.strip())
            if qty < 1:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Inserisci un numero intero positivo.")
            return MORTALITA_QTY
        ctx.user_data["mortalita_qty"] = qty
        await update.message.reply_text(
            f"Registrati {qty} morti.\nCausa (es: trauma, malattia) oppure /skip per saltare:"
        )
        return MORTALITA_CAUSA

    async def mortalita_causa(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        testo = update.message.text.strip()
        causa = None if testo.startswith("/skip") else testo
        await _salva_mortalita(update, ctx, app, causa)
        return ConversationHandler.END

    async def _salva_mortalita(update, ctx, app, causa):
        cap = ctx.user_data.get("mortalita_cap")
        box = ctx.user_data.get("mortalita_box")
        qty = ctx.user_data.get("mortalita_qty", 1)
        with app.app_context():
            from app import db
            from app.models import EventoMortalita, Ciclo
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await update.message.reply_text("⚠️ Nessun ciclo attivo.")
                return
            ev = EventoMortalita(
                ciclo_id=ciclo.id, data=date.today(),
                capannone_numero=cap, box_numero=box,
                quantita=qty, causa=causa, registrato_da="telegram",
            )
            db.session.add(ev)
            db.session.commit()
        box_txt = f"box {box}" if box else f"CAP {cap}"
        await update.message.reply_text(
            f"✅ Salvato: {qty} morti in {box_txt}" + (f" — {causa}" if causa else "") + "\n\nUsa /start per continuare.",
            reply_markup=kb_main(),
        )

    # ── Spostamento ───────────────────────────────────────────────────────

    async def spostamento_tipo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["spostamento_tipo"] = q.data
        if q.data == "entrata":
            await q.edit_message_text("📍 Destinazione (CAP):", reply_markup=kb_capannoni())
            return SPOSTAMENTO_DEST
        elif q.data == "uscita":
            await q.edit_message_text("📍 Origine (CAP):", reply_markup=kb_capannoni())
            return SPOSTAMENTO_ORIG
        else:
            await q.edit_message_text("📍 CAP di origine:", reply_markup=kb_capannoni())
            return SPOSTAMENTO_ORIG

    async def spostamento_orig(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["spostamento_cap_orig"] = int(q.data)
        if ctx.user_data["spostamento_tipo"] == "uscita":
            await q.edit_message_text("Quanti capi escono/vengono macellati?")
            return SPOSTAMENTO_QTY
        await q.edit_message_text("📍 CAP di destinazione:", reply_markup=kb_capannoni())
        return SPOSTAMENTO_DEST

    async def spostamento_dest(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["spostamento_cap_dest"] = int(q.data)
        await q.edit_message_text("Quanti capi vengono spostati?")
        return SPOSTAMENTO_QTY

    async def spostamento_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            qty = int(update.message.text.strip())
            if qty < 1:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Inserisci un numero intero positivo.")
            return SPOSTAMENTO_QTY

        tipo = ctx.user_data.get("spostamento_tipo")
        cap_orig = ctx.user_data.get("spostamento_cap_orig")
        cap_dest = ctx.user_data.get("spostamento_cap_dest")

        with app.app_context():
            from app import db
            from app.models import Spostamento, Ciclo
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await update.message.reply_text("⚠️ Nessun ciclo attivo.")
                return ConversationHandler.END
            s = Spostamento(
                ciclo_id=ciclo.id, data=date.today(), tipo=tipo, quantita=qty,
                capannone_origine=cap_orig, capannone_destinazione=cap_dest,
                registrato_da="telegram",
            )
            db.session.add(s)
            db.session.commit()

        label = {"entrata": "entrata", "uscita": "uscita/macello", "interno": "spostamento interno"}[tipo]
        await update.message.reply_text(f"✅ {qty} capi — {label} registrata.\n\nUsa /start per continuare.")
        return ConversationHandler.END

    # ── Consegna ──────────────────────────────────────────────────────────

    async def consegna_qty(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        try:
            qty = float(update.message.text.strip().replace(",", "."))
            if qty <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("⚠️ Inserisci un numero valido (es: 45.5).")
            return CONSEGNA_QTY
        ctx.user_data["consegna_qty"] = qty
        tipo = ctx.user_data.get("consegna_tipo", "siero")
        if tipo == "siero":
            await update.message.reply_text("Lotto / speditore (opzionale, scrivi /skip per saltare):")
        else:
            await update.message.reply_text("Tipo mangime / n° bolla (opzionale, scrivi /skip per saltare):")
        return CONSEGNA_EXTRA

    async def consegna_extra(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        testo = update.message.text.strip()
        extra = None if testo.startswith("/skip") else testo
        tipo = ctx.user_data.get("consegna_tipo", "siero")
        qty = ctx.user_data.get("consegna_qty", 0)

        with app.app_context():
            from app import db
            from app.models import ConsegnaSiero, ConsegnaMangime, Ciclo
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await update.message.reply_text("⚠️ Nessun ciclo attivo.")
                return ConversationHandler.END
            if tipo == "siero":
                db.session.add(ConsegnaSiero(
                    ciclo_id=ciclo.id, data=date.today(),
                    quantita_qli=qty, speditore=extra,
                ))
            else:
                db.session.add(ConsegnaMangime(
                    ciclo_id=ciclo.id, data=date.today(),
                    quantita_qli=qty, tipo_mangime=extra,
                ))
            db.session.commit()

        emoji = "🚚" if tipo == "siero" else "🌾"
        await update.message.reply_text(f"{emoji} {qty} qli {tipo} registrati.\n\nUsa /start per continuare.")
        return ConversationHandler.END

    async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Operazione annullata. Usa /start per ricominciare.")
        return ConversationHandler.END

    # ── Costruzione e avvio ───────────────────────────────────────────────

    tg_app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start), CommandHandler("menu", cmd_start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(menu_callback)],
            MORTALITA_CAP: [CallbackQueryHandler(mortalita_cap)],
            MORTALITA_BOX: [CallbackQueryHandler(mortalita_box)],
            MORTALITA_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, mortalita_qty)],
            MORTALITA_CAUSA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, mortalita_causa),
                CommandHandler("skip", mortalita_causa),
            ],
            SPOSTAMENTO_TIPO: [CallbackQueryHandler(spostamento_tipo)],
            SPOSTAMENTO_ORIG: [CallbackQueryHandler(spostamento_orig)],
            SPOSTAMENTO_DEST: [CallbackQueryHandler(spostamento_dest)],
            SPOSTAMENTO_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, spostamento_qty)],
            CONSEGNA_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, consegna_qty)],
            CONSEGNA_EXTRA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, consegna_extra),
                CommandHandler("skip", consegna_extra),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel), CommandHandler("annulla", cancel)],
        per_message=False,
    )

    tg_app.add_handler(conv)

    import threading
    import asyncio

    async def _run_bot():
        async with tg_app:
            await tg_app.start()
            await tg_app.updater.start_polling(drop_pending_updates=True)
            await asyncio.Event().wait()  # block until task is cancelled

    def _run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_run_bot())
        except Exception as e:
            logger.error(f"Bot loop error: {e}")
        finally:
            loop.close()

    t = threading.Thread(target=_run, daemon=True, name="allevamento-bot")
    t.start()
    logger.info("Bot Telegram allevamento avviato.")
