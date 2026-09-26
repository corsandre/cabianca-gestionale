import logging
import threading
import time
from urllib.parse import urlparse

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
import bcrypt
from app import db
from app.models import User

bp = Blueprint("auth", __name__)
logger = logging.getLogger(__name__)

# Limite tentativi di login, in memoria (un solo worker gunicorn; si azzera al riavvio).
# Per IP: blocca chi prova password a raffica. Per utente: frena un attacco distribuito
# su tanti IP contro lo stesso account, con soglia più alta per non bloccare facilmente
# l'utente vero.
FINESTRA_SEC = 15 * 60
MAX_FALLITI_IP = 5
MAX_FALLITI_UTENTE = 20
_falliti = {}  # chiave ("ip", x) / ("utente", x) -> lista di timestamp dei fallimenti
_lock = threading.Lock()


def _recenti(chiave, ora):
    lista = [t for t in _falliti.get(chiave, []) if ora - t < FINESTRA_SEC]
    if lista:
        _falliti[chiave] = lista
    else:
        _falliti.pop(chiave, None)
    return lista


def _attesa_blocco(ip, username):
    """Secondi di attesa se IP o utente hanno superato la soglia, altrimenti 0."""
    ora = time.time()
    with _lock:
        attese = []
        for chiave, massimo in ((("ip", ip), MAX_FALLITI_IP), (("utente", username), MAX_FALLITI_UTENTE)):
            lista = _recenti(chiave, ora)
            if len(lista) >= massimo:
                attese.append(FINESTRA_SEC - (ora - lista[-massimo]))
        return max(attese, default=0)


def _registra_fallimento(ip, username):
    ora = time.time()
    with _lock:
        for chiave in (("ip", ip), ("utente", username)):
            _falliti.setdefault(chiave, []).append(ora)
        # pulizia delle chiavi scadute, così il dizionario non cresce all'infinito
        for chiave in list(_falliti):
            _recenti(chiave, ora)


def _azzera(ip, username):
    with _lock:
        _falliti.pop(("ip", ip), None)
        _falliti.pop(("utente", username), None)


def _next_sicuro(url):
    """Solo percorsi interni: evita che ?next= rimandi a un sito esterno (phishing)."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return None
    parti = urlparse(url)
    return url if not parti.scheme and not parti.netloc else None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = request.remote_addr or "?"
        chiave_utente = username.lower()

        attesa = _attesa_blocco(ip, chiave_utente)
        if attesa:
            logger.warning("Login bloccato per troppi tentativi: utente=%r ip=%s", username, ip)
            flash(f"Troppi tentativi falliti. Riprova tra {int(attesa // 60) + 1} minuti.", "danger")
            return render_template("auth/login.html"), 429

        user = User.query.filter_by(username=username, active=True).first()

        if user and bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            _azzera(ip, chiave_utente)
            login_user(user, remember=True)
            return redirect(_next_sicuro(request.args.get("next")) or url_for("dashboard.index"))

        _registra_fallimento(ip, chiave_utente)
        logger.warning("Login fallito: utente=%r ip=%s", username, ip)
        flash("Credenziali non valide.", "danger")

    return render_template("auth/login.html")


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Disconnesso con successo.", "success")
    return redirect(url_for("auth.login"))
