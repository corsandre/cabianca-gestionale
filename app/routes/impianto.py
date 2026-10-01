"""Impianto di alimentazione: impostazioni del collegamento, prova, approvazione delle letture.

Collegamento opzionale (vedi services/impianto): in modalità manuale queste pagine permettono solo
di configurarlo; nessuna connessione parte da sola.
"""
import os
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app import db
from app.routes.allevamento import _check_allevamento
from app.services import impianto as I

bp = Blueprint("impianto", __name__, url_prefix="/allevamento/impianto")

CAMPI_NUMERICI = {"impianto_porta": (1, 65535), "impianto_controllo_min": (5, 1440),
                  "impianto_foto_s": (15, 600), "impianto_anticipo_min": (0, 60)}


def _solo_admin():
    _check_allevamento()
    if current_user.role != "admin":
        abort(403)


def _salva(chiave, valore):
    from app.models import Setting
    s = db.session.get(Setting, chiave)
    if s:
        s.value = valore
    else:
        db.session.add(Setting(key=chiave, value=valore))


@bp.route("/impostazioni", methods=["POST"])
@login_required
def impostazioni():
    _solo_admin()
    try:
        modalita = request.form.get("impianto_modalita", I.MANUALE)
        if modalita not in I.MODALITA:
            raise ValueError("Modalità non valida.")
        tipo = request.form.get("impianto_tipo", "em2000")
        if tipo not in I.TIPI:
            raise ValueError("Tipo di impianto non gestito.")
        chat = request.form.get("impianto_chat_pasti", "allevamento")
        if chat not in ("allevamento", "sistema", "nessuno"):
            raise ValueError("Gruppo Telegram non valido.")
        host = request.form.get("impianto_host", "").strip()
        if modalita != I.MANUALE and not host:
            raise ValueError("Per collegarsi all'impianto serve il suo indirizzo.")
        valori = {"impianto_modalita": modalita, "impianto_tipo": tipo, "impianto_chat_pasti": chat,
                  "impianto_host": host, "impianto_utente": request.form.get("impianto_utente", "").strip() or "root"}
        for campo, (mn, mx) in CAMPI_NUMERICI.items():
            v = int(request.form.get(campo, I.DEFAULTS[campo]) or I.DEFAULTS[campo])
            if not mn <= v <= mx:
                raise ValueError(f"Valore fuori intervallo per {campo.replace('impianto_', '')}: {mn}–{mx}.")
            valori[campo] = str(v)
        for k, v in valori.items():
            _salva(k, v)
        db.session.commit()
        flash(f"Impianto di alimentazione: modalità «{I.NOMI_MODALITA[modalita]}» salvata.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.impostazioni") + "#impianto")


@bp.route("/chiave", methods=["POST"])
@login_required
def chiave():
    _solo_admin()
    I.genera_chiave()
    flash("Nuova chiave di collegamento creata: aggiungi la chiave pubblica sul PC dell'impianto.", "success")
    return redirect(url_for("allevamento.impostazioni") + "#impianto")


@bp.route("/prova", methods=["POST"])
@login_required
def prova():
    """Controllo immediato chiesto dall'admin: unico caso in cui ci si collega anche in manuale."""
    _solo_admin()
    lettore = I.crea_lettore(ignora_modalita=True)
    if lettore is None:
        flash("Inserisci prima l'indirizzo dell'impianto.", "warning")
        return redirect(url_for("allevamento.impostazioni") + "#impianto")
    esito = lettore.controllo()
    lettore.chiudi()
    if not esito.raggiungibile:
        flash(f"Impianto non raggiungibile: {esito.errore}", "danger")
    else:
        os.makedirs(I.cartella_dati(), exist_ok=True)
        with open(os.path.join(I.cartella_dati(), "ultima_prova.png"), "wb") as f:
            f.write(esito.immagine_png)
        l = esito.lettura
        orari = ", ".join(o.strftime("%H:%M") for o in esito.orari) or "non letti"
        flash(f"Collegamento riuscito alle {datetime.now():%H:%M}: {I.NOMI_FASI.get(l.fase, l.fase)}, ora dell'impianto "
              f"{l.ora_pc or '?'}, prossimo pasto {l.prossimo_pasto or '?'}, orari {orari}.", "success")
    return redirect(url_for("allevamento.impostazioni") + "#impianto")


@bp.route("/immagine/<path:nome>")
@login_required
def immagine(nome):
    """Fotografie dello schermo: ultima prova o anomalie (solo dentro la cartella dell'impianto)."""
    _check_allevamento()
    base = I.cartella_dati()
    percorso = os.path.abspath(os.path.join(base, nome))
    if not percorso.startswith(base + os.sep) or not percorso.endswith(".png") or not os.path.exists(percorso):
        abort(404)
    return send_file(percorso, mimetype="image/png")


def _lettura_o_404(lid):
    from app.models import ImpiantoLinea
    l = db.session.get(ImpiantoLinea, lid)
    if not l:
        abort(404)
    return l


@bp.route("/linea/<int:lid>/approva", methods=["POST"])
@login_required
def approva(lid):
    _check_allevamento()
    from app.services.impianto.registrazione import registra
    l = _lettura_o_404(lid)
    try:
        if l.stato != "proposta":
            raise ValueError("Questa lettura è già stata decisa.")
        operatore = current_user.display_name or current_user.username
        if registra(l, operatore=operatore, sovrascrivi_manuali=True) is None:
            raise ValueError(l.note or "Lettura non registrata.")
        db.session.commit()
        flash(f"Pasto {l.pasto}, linea {l.linea}: valori del PC registrati.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Errore: {e}", "danger")
    return redirect(url_for("allevamento.alimentazione", data=l.data.isoformat()))


@bp.route("/linea/<int:lid>/scarta", methods=["POST"])
@login_required
def scarta(lid):
    _check_allevamento()
    from app.services.impianto.registrazione import scarta as scarta_lettura
    l = _lettura_o_404(lid)
    if l.stato == "proposta":
        scarta_lettura(l, current_user.display_name or current_user.username)
        db.session.commit()
        flash(f"Pasto {l.pasto}, linea {l.linea}: lettura del PC scartata.", "success")
    return redirect(url_for("allevamento.alimentazione", data=l.data.isoformat()))
