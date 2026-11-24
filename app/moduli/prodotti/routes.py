"""Pagine del modulo Prodotti (blueprint "prodotti", indirizzi /prodotti/...).

Accesso: utente collegato e con la sezione "prodotti" (Impostazioni → utenti). Le pagine che
modificano dati usano anche @write_required: il consulente vede ma non modifica.
I file statici del modulo sono in static/ e si servono da /prodotti/static/...
"""
from flask import Blueprint, render_template
from flask_login import current_user, login_required

from app.utils.decorators import section_required

bp = Blueprint("prodotti", __name__, url_prefix="/prodotti",
               template_folder="templates", static_folder="static", static_url_path="/static")


@bp.before_request
@login_required
def _accesso():
    """Ogni pagina del modulo: login obbligatorio e permesso "prodotti" (altrimenti 403)."""
    return section_required("prodotti")()


@bp.route("/")
def index():
    return render_template("prodotti/index.html", utente=current_user)
