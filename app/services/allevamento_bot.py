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
        from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
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
        PASTO_LINEA, PASTO_NUM, PASTO_MANG, PASTO_SIERO, PASTO_ACQUA,
        CENSIMENTO_FIELD, CENSIMENTO_BOX_NEXT, CENSIMENTO_CAP_NEXT, CENSIMENTO_CONFIRM,
    ) = range(21)

    CAPANNONI = [1, 2, 3, 4, 5, 6, 7]
    BOX_PER_CAP = {
        1: list(range(1, 10)), 2: list(range(10, 16)), 3: list(range(16, 22)),
        4: list(range(22, 37)), 5: list(range(37, 43)),
        7: list(range(43, 50)), 6: list(range(50, 55)),
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
            [InlineKeyboardButton("📋 Censimento", callback_data="censimento")],
            [InlineKeyboardButton("🍽️ Registra consumo", callback_data="pasto")],
            [InlineKeyboardButton("💀 Registra morte", callback_data="mortalita")],
            [InlineKeyboardButton("🔄 Spostamento", callback_data="spostamento")],
            [InlineKeyboardButton("🚚 Consegna siero", callback_data="consegna_siero"),
             InlineKeyboardButton("🌾 Consegna mangime", callback_data="consegna_mangime")],
            [InlineKeyboardButton("📊 Stato ciclo", callback_data="stato")],
        ])

    def kb_linee():
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("🔵 Linea 1", callback_data="1"),
            InlineKeyboardButton("🔴 Linea 2", callback_data="2"),
            InlineKeyboardButton("🟢 Linea 3", callback_data="3"),
        ]])

    def kb_pasti():
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("Pasto 1", callback_data="1"),
            InlineKeyboardButton("Pasto 2", callback_data="2"),
            InlineKeyboardButton("Pasto 3", callback_data="3"),
        ]])

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

        if data == "censimento":
            with app.app_context():
                from app.models import Ciclo, Censimento
                ciclo = Ciclo.query.filter_by(attivo=True).first()
                rif = None
                if ciclo:
                    ultimo = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(
                        Censimento.data.desc(), Censimento.id.desc()
                    ).first()
                    rif = {cb.box_numero: cb.quantita for cb in ultimo.conteggi.all()} if ultimo else {}
            if rif is None:
                await q.edit_message_text("⚠️ Nessun ciclo attivo.", reply_markup=kb_main())
                return MAIN_MENU
            ctx.user_data["cens_conteggi"] = {}
            ctx.user_data["cens_cap_idx"] = 0
            ctx.user_data["cens_box_idx"] = 0
            ctx.user_data["cens_field"] = "capi"
            ctx.user_data["cens_buffer"] = ""
            ctx.user_data["cens_riferimento"] = rif
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        elif data == "pasto":
            await q.edit_message_text("🍽️ *Registra consumo*\nSeleziona la linea:", parse_mode="Markdown", reply_markup=kb_linee())
            return PASTO_LINEA
        elif data == "mortalita":
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

    # ── Registra consumo ─────────────────────────────────────────────────

    async def pasto_linea(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["pasto_linea"] = int(q.data)
        await q.edit_message_text(
            f"Linea {q.data} selezionata.\nSeleziona il pasto:", reply_markup=kb_pasti(),
        )
        return PASTO_NUM

    async def pasto_num(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        ctx.user_data["pasto_num"] = int(q.data)
        await q.edit_message_text(f"🌾 Mangime (qli)? Scrivi il numero (es: 8.5) oppure /skip:")
        return PASTO_MANG

    def _parse_float_skip(testo):
        if testo.strip().startswith("/skip"):
            return None, True
        try:
            return float(testo.strip().replace(",", ".")), True
        except ValueError:
            return None, False

    async def pasto_mang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        val, ok = _parse_float_skip(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ Inserisci un numero valido (es: 8.5) oppure /skip.")
            return PASTO_MANG
        ctx.user_data["pasto_mang"] = val
        await update.message.reply_text("🚚 Siero (qli)? Scrivi il numero oppure /skip:")
        return PASTO_SIERO

    async def pasto_siero(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        val, ok = _parse_float_skip(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ Inserisci un numero valido oppure /skip.")
            return PASTO_SIERO
        ctx.user_data["pasto_siero"] = val
        await update.message.reply_text("💧 Acqua (litri)? Scrivi il numero oppure /skip:")
        return PASTO_ACQUA

    async def pasto_acqua(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        val, ok = _parse_float_skip(update.message.text)
        if not ok:
            await update.message.reply_text("⚠️ Inserisci un numero valido oppure /skip.")
            return PASTO_ACQUA

        linea = ctx.user_data.get("pasto_linea")
        pasto = ctx.user_data.get("pasto_num")
        mang = ctx.user_data.get("pasto_mang")
        siero = ctx.user_data.get("pasto_siero")

        with app.app_context():
            from app import db
            from app.models import Ciclo
            from app.services.allevamento_pasti import registra_pasto
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await update.message.reply_text("⚠️ Nessun ciclo attivo.")
                return ConversationHandler.END
            registra_pasto(
                ciclo_id=ciclo.id, data=date.today(), pasto=pasto, linea=linea,
                mangime_qli=mang, siero_qli=siero, acqua_litri=val,
            )
            db.session.commit()

        await update.message.reply_text(
            f"✅ Pasto {pasto} — Linea {linea} registrato.\n"
            f"Mangime: {mang if mang is not None else '-'} qli, "
            f"Siero: {siero if siero is not None else '-'} qli, "
            f"Acqua: {val if val is not None else '-'} l\n\nUsa /start per continuare.",
            reply_markup=kb_main(),
        )
        return ConversationHandler.END

    # ── Censimento (percorso guidato, solo tastiera inline) ─────────────────

    CENS_CAMPI = ["capi", "giorni", "peso"]
    CENS_LABEL = {"capi": "Capi", "giorni": "Giorni di vita (età)", "peso": "Peso stimato (kg)"}

    def _cens_box_corrente(ctx):
        cap = CAPANNONI[ctx.user_data["cens_cap_idx"]]
        b = BOX_PER_CAP[cap][ctx.user_data["cens_box_idx"]]
        return cap, b

    def _cens_box_testo(ctx):
        cap, b = _cens_box_corrente(ctx)
        field = ctx.user_data["cens_field"]
        buffer = ctx.user_data["cens_buffer"]
        cap_max = POSTI_PER_BOX_STANDARD.get(b)
        righe = [f"🏠 CAP {cap} — 📦 Box {b} (max {cap_max})", f"Campo: *{CENS_LABEL[field]}*"]
        if field == "capi":
            rif = ctx.user_data["cens_riferimento"].get(b)
            if rif is not None:
                righe.append(f"Ultimo censimento: {rif}")
        righe.append(f"\nValore: `{buffer or '—'}`")
        return "\n".join(righe)

    def _cens_box_kb(ctx):
        field = ctx.user_data["cens_field"]
        cap, b = _cens_box_corrente(ctx)
        rows = [
            [InlineKeyboardButton(str(n), callback_data=f"d{n}") for n in (1, 2, 3)],
            [InlineKeyboardButton(str(n), callback_data=f"d{n}") for n in (4, 5, 6)],
            [InlineKeyboardButton(str(n), callback_data=f"d{n}") for n in (7, 8, 9)],
        ]
        row4 = []
        if field == "peso":
            row4.append(InlineKeyboardButton(".", callback_data="dot"))
        row4.append(InlineKeyboardButton("0", callback_data="d0"))
        row4.append(InlineKeyboardButton("⌫", callback_data="bksp"))
        rows.append(row4)
        row5 = []
        if field == "capi":
            rif = ctx.user_data["cens_riferimento"].get(b)
            if rif is not None:
                row5.append(InlineKeyboardButton(f"Usa {rif}", callback_data="usarif"))
        else:
            row5.append(InlineKeyboardButton("Salta ↷", callback_data="skip"))
        row5.append(InlineKeyboardButton("✓ OK", callback_data="ok"))
        rows.append(row5)
        return InlineKeyboardMarkup(rows)

    async def _mostra_campo_box(q, ctx):
        await q.edit_message_text(_cens_box_testo(ctx), parse_mode="Markdown", reply_markup=_cens_box_kb(ctx))

    async def censimento_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        data = q.data
        field = ctx.user_data["cens_field"]

        if data.startswith("d") and data[1:].isdigit():
            ctx.user_data["cens_buffer"] += data[1:]
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        if data == "dot":
            if "." not in ctx.user_data["cens_buffer"]:
                ctx.user_data["cens_buffer"] += "."
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        if data == "bksp":
            ctx.user_data["cens_buffer"] = ctx.user_data["cens_buffer"][:-1]
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        if data == "usarif":
            _, b = _cens_box_corrente(ctx)
            ctx.user_data["cens_buffer"] = str(ctx.user_data["cens_riferimento"].get(b, 0))
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        if data == "skip":
            return await _salva_campo_e_avanza(q, ctx, None)
        if data == "ok":
            buf = ctx.user_data["cens_buffer"]
            if field == "capi":
                if not buf.isdigit():
                    await q.answer("Inserisci un numero per i capi.", show_alert=True)
                    return CENSIMENTO_FIELD
                valore = int(buf)
            else:
                if not buf:
                    return await _salva_campo_e_avanza(q, ctx, None)
                try:
                    valore = int(buf) if field == "giorni" else float(buf)
                except ValueError:
                    await q.answer("Valore non valido.", show_alert=True)
                    return CENSIMENTO_FIELD
            return await _salva_campo_e_avanza(q, ctx, valore)
        return CENSIMENTO_FIELD

    async def _salva_campo_e_avanza(q, ctx, valore):
        cap, b = _cens_box_corrente(ctx)
        field = ctx.user_data["cens_field"]
        ctx.user_data["cens_conteggi"].setdefault(b, {})[field] = valore

        idx = CENS_CAMPI.index(field)
        if idx + 1 < len(CENS_CAMPI):
            ctx.user_data["cens_field"] = CENS_CAMPI[idx + 1]
            ctx.user_data["cens_buffer"] = ""
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD

        dati = ctx.user_data["cens_conteggi"][b]
        cap_max = POSTI_PER_BOX_STANDARD.get(b)
        avviso = ""
        if cap_max and dati.get("capi", 0) > cap_max:
            avviso = f"\n⚠️ Sopra capienza (max {cap_max})"
        testo = (f"✅ Box {b} completato:\n"
                 f"Capi: {dati.get('capi', 0)}\n"
                 f"Età: {dati.get('giorni') if dati.get('giorni') is not None else '—'} gg\n"
                 f"Peso: {dati.get('peso') if dati.get('peso') is not None else '—'} kg"
                 f"{avviso}")

        ultimo_box = ctx.user_data["cens_box_idx"] + 1 >= len(BOX_PER_CAP[cap])
        if ultimo_box:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📋 Riepilogo capannone", callback_data="recap")]])
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➡️ Prossimo box", callback_data="nextbox")]])
        await q.edit_message_text(testo, reply_markup=kb)
        return CENSIMENTO_BOX_NEXT

    async def censimento_box_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == "nextbox":
            ctx.user_data["cens_box_idx"] += 1
            ctx.user_data["cens_field"] = "capi"
            ctx.user_data["cens_buffer"] = ""
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD
        return await _mostra_recap_capannone(q, ctx)

    async def _mostra_recap_capannone(q, ctx):
        cap = CAPANNONI[ctx.user_data["cens_cap_idx"]]
        boxes = BOX_PER_CAP[cap]
        righe = [f"📋 *Riepilogo CAP {cap}*"]
        tot_cap = 0
        for b in boxes:
            dati = ctx.user_data["cens_conteggi"].get(b, {})
            capi = dati.get("capi", 0)
            tot_cap += capi
            extra = []
            if dati.get("giorni") is not None:
                extra.append(f"{dati['giorni']}gg")
            if dati.get("peso") is not None:
                extra.append(f"{dati['peso']}kg")
            righe.append(f"B{b}: {capi} capi" + (f" ({', '.join(extra)})" if extra else ""))
        righe.append(f"\nTotale CAP {cap}: *{tot_cap}*")
        tot_generale = sum(d.get("capi", 0) for d in ctx.user_data["cens_conteggi"].values())
        righe.append(f"Totale generale finora: *{tot_generale}*")

        ultimo_cap = ctx.user_data["cens_cap_idx"] + 1 >= len(CAPANNONI)
        if ultimo_cap:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Riepilogo finale", callback_data="finalrecap")]])
        else:
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("➡️ Prossimo capannone", callback_data="nextcap")]])
        await q.edit_message_text("\n".join(righe), parse_mode="Markdown", reply_markup=kb)
        return CENSIMENTO_CAP_NEXT

    async def censimento_cap_next(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()
        if q.data == "nextcap":
            ctx.user_data["cens_cap_idx"] += 1
            ctx.user_data["cens_box_idx"] = 0
            ctx.user_data["cens_field"] = "capi"
            ctx.user_data["cens_buffer"] = ""
            await _mostra_campo_box(q, ctx)
            return CENSIMENTO_FIELD

        tot = sum(d.get("capi", 0) for d in ctx.user_data["cens_conteggi"].values())
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Conferma e salva", callback_data="cens_ok"),
            InlineKeyboardButton("❌ Annulla", callback_data="cens_no"),
        ]])
        await q.edit_message_text(
            f"📋 *Censimento completo*\nTotale suini: *{tot}*\n\nConfermi il salvataggio?",
            parse_mode="Markdown", reply_markup=kb,
        )
        return CENSIMENTO_CONFIRM

    async def censimento_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        await q.answer()

        if q.data == "cens_no":
            ctx.user_data.pop("cens_conteggi", None)
            await q.edit_message_text("Censimento annullato. Usa /start per ricominciare.")
            return ConversationHandler.END

        conteggi = ctx.user_data.get("cens_conteggi", {})
        with app.app_context():
            from app import db
            from app.models import Ciclo, Censimento, CensimentoBox
            ciclo = Ciclo.query.filter_by(attivo=True).first()
            if not ciclo:
                await q.edit_message_text("⚠️ Nessun ciclo attivo.")
                return ConversationHandler.END
            operatore = f"telegram:{update.effective_user.first_name or update.effective_user.id}"
            cens = Censimento(ciclo_id=ciclo.id, data=date.today(), operatore=operatore)
            db.session.add(cens)
            db.session.flush()
            for b, dati in conteggi.items():
                db.session.add(CensimentoBox(
                    censimento_id=cens.id, box_numero=b,
                    quantita=dati.get("capi", 0),
                    giorni_vita=dati.get("giorni"),
                    peso_stimato_kg=dati.get("peso"),
                ))
            db.session.commit()

        tot = sum(d.get("capi", 0) for d in conteggi.values())
        await q.edit_message_text(f"✅ Censimento salvato: {tot} suini totali.\n\nUsa /start per continuare.")
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
            PASTO_LINEA: [CallbackQueryHandler(pasto_linea)],
            PASTO_NUM: [CallbackQueryHandler(pasto_num)],
            PASTO_MANG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pasto_mang),
                CommandHandler("skip", pasto_mang),
            ],
            PASTO_SIERO: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pasto_siero),
                CommandHandler("skip", pasto_siero),
            ],
            PASTO_ACQUA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, pasto_acqua),
                CommandHandler("skip", pasto_acqua),
            ],
            CENSIMENTO_FIELD: [CallbackQueryHandler(censimento_field)],
            CENSIMENTO_BOX_NEXT: [CallbackQueryHandler(censimento_box_next)],
            CENSIMENTO_CAP_NEXT: [CallbackQueryHandler(censimento_cap_next)],
            CENSIMENTO_CONFIRM: [CallbackQueryHandler(censimento_confirm)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel), CommandHandler("annulla", cancel),
            CommandHandler("start", cmd_start), CommandHandler("menu", cmd_start),
        ],
        per_message=False,
    )

    tg_app.add_handler(conv)

    import threading
    import asyncio

    async def _run_bot():
        async with tg_app:
            await tg_app.bot.set_my_commands([
                BotCommand("start", "Apri il menu principale"),
                BotCommand("menu", "Apri il menu principale"),
                BotCommand("cancel", "Annulla l'operazione in corso"),
            ])
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
