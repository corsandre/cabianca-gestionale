"""Pagine del modulo Prodotti (blueprint "prodotti", indirizzi /prodotti/...).

Le route sono divise per argomento, un file ciascuno:
    panoramica.py   /prodotti/                     pagina iniziale
    catalogo.py     /prodotti/materie-prime, /prodotti/catalogo, /prodotti/catalogo/<id>
    ricette.py      /prodotti/ricettario, editor delle ricette, anteprima dell'elenco ingredienti
    lotti.py        /prodotti/lotti (libro lotti), finestra "Nuovo lotto", richiamo
    etichette.py    generazione e archivio dei PDF delle etichette, formati
    esporta.py      export PDF/Excel di libro lotti e ricettario
comune.py contiene gli aiuti condivisi (utente, fornitori, risposte JSON).

Accesso: utente collegato e con la sezione "prodotti" (Impostazioni → utenti), controllato qui per
TUTTE le pagine. Le pagine che modificano dati usano anche @write_required (il consulente vede ma
non modifica). I file statici del modulo sono in ../static e si servono da /prodotti/static/...
"""
from flask import Blueprint
from flask_login import login_required

from app.utils.decorators import section_required

bp = Blueprint("prodotti", __name__, url_prefix="/prodotti",
               template_folder="../templates", static_folder="../static", static_url_path="/static")


@bp.before_request
@login_required
def _accesso():
    """Ogni pagina del modulo: login obbligatorio e permesso "prodotti" (altrimenti 403)."""
    return section_required("prodotti")()


@bp.app_template_filter("data_it")
def data_it(valore):
    """'2026-11-24' (o con l'ora) → '24/11/2026'; vuoto → ''. Le date nel database sono testo ISO."""
    if not valore:
        return ""
    testo = str(valore)[:10]
    parti = testo.split("-")
    return f"{parti[2]}/{parti[1]}/{parti[0]}" if len(parti) == 3 else testo


# Le pagine si registrano sul blueprint quando i file vengono importati (in fondo, per evitare import circolari)
from app.moduli.prodotti.routes import panoramica, catalogo, ricette  # noqa: E402,F401
