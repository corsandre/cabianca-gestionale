"""/salute: stato del gestionale per gli script di deploy e per i controlli (senza login).

Usato da scripts/deploy.sh per sapere se il sito appena riavviato funziona. Restituisce solo
versioni e stato, nessun dato aziendale.
"""
from flask import Blueprint, current_app, jsonify

from app import db
from app.version import VERSIONE

bp = Blueprint("salute", __name__)


@bp.route("/salute")
def salute():
    from app import moduli
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    stato_moduli = moduli.stato_per_salute(current_app)
    tutto_ok = db_ok and all(m.get("attivo") for m in stato_moduli.values())
    return jsonify(
        ok=tutto_ok,
        gestionale=VERSIONE,
        ruolo=current_app.config.get("RUOLO"),
        database=db_ok,
        moduli=stato_moduli,
    ), (200 if tutto_ok else 503)
