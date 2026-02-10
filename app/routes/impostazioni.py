from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import bcrypt
from app import db
from app.models import User, RevenueStream
from app.utils.decorators import admin_required

bp = Blueprint("impostazioni", __name__, url_prefix="/impostazioni")


@bp.route("/")
@login_required
@admin_required
def index():
    users = User.query.order_by(User.username).all()
    streams = RevenueStream.query.order_by(RevenueStream.name).all()
    return render_template("impostazioni/index.html", users=users, streams=streams)


@bp.route("/utente/nuovo", methods=["POST"])
@login_required
@admin_required
def new_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "operatore")

    if not username or not password:
        flash("Username e password sono obbligatori.", "warning")
        return redirect(url_for("impostazioni.index"))

    if User.query.filter_by(username=username).first():
        flash("Username gia in uso.", "warning")
        return redirect(url_for("impostazioni.index"))

    user = User(
        username=username,
        password_hash=bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        display_name=display_name or username,
        role=role,
        active=True,
    )
    db.session.add(user)
    db.session.commit()
    flash(f"Utente '{username}' creato.", "success")
    return redirect(url_for("impostazioni.index"))


@bp.route("/utente/<int:id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_user(id):
    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash("Non puoi disattivare te stesso.", "warning")
        return redirect(url_for("impostazioni.index"))
    user.active = not user.active
    db.session.commit()
    flash(f"Utente {'attivato' if user.active else 'disattivato'}.", "success")
    return redirect(url_for("impostazioni.index"))


@bp.route("/password", methods=["POST"])
@login_required
def change_password():
    old_pw = request.form.get("old_password", "")
    new_pw = request.form.get("new_password", "")

    if not bcrypt.checkpw(old_pw.encode(), current_user.password_hash.encode()):
        flash("Password attuale non corretta.", "danger")
        return redirect(url_for("impostazioni.index"))

    if len(new_pw) < 6:
        flash("La nuova password deve avere almeno 6 caratteri.", "warning")
        return redirect(url_for("impostazioni.index"))

    current_user.password_hash = bcrypt.hashpw(new_pw.encode(), bcrypt.gensalt()).decode()
    db.session.commit()
    flash("Password aggiornata.", "success")
    return redirect(url_for("impostazioni.index"))


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
    return redirect(url_for("impostazioni.index"))


@bp.route("/backup", methods=["POST"])
@login_required
@admin_required
def backup_now():
    try:
        from app.services.backup import run_backup
        run_backup()
        flash("Backup completato.", "success")
    except Exception as e:
        flash(f"Errore backup: {e}", "danger")
    return redirect(url_for("impostazioni.index"))
