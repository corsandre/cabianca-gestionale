from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import RevenueStream
from app.utils.decorators import admin_required, section_required

bp = Blueprint("finanza_impostazioni", __name__, url_prefix="/finanza/impostazioni")
bp.before_request(section_required("finanza"))


@bp.route("/")
@login_required
@admin_required
def index():
    streams = RevenueStream.query.order_by(RevenueStream.name).all()
    return render_template("finanza_impostazioni/index.html", streams=streams)


@bp.route("/flusso/nuovo", methods=["POST"])
@login_required
@admin_required
def new_stream():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#009d5a")
    description = request.form.get("description", "").strip()
    if name:
        db.session.add(RevenueStream(name=name, color=color, description=description))
        db.session.commit()
        flash("Flusso di ricavo creato.", "success")
    return redirect(url_for("finanza_impostazioni.index"))
