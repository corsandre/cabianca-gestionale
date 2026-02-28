from flask import Blueprint, render_template
from flask_login import login_required
from app.utils.decorators import section_required

bp = Blueprint("allevamento", __name__, url_prefix="/allevamento")
bp.before_request(section_required("allevamento"))


@bp.route("/")
@login_required
def index():
    return render_template("allevamento/index.html")


@bp.route("/impostazioni")
@login_required
def impostazioni():
    return render_template("allevamento/impostazioni.html")
