import json
import os
import shutil
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_required, current_user, logout_user
import bcrypt
from app import db
from app.models import User, Setting
from app.utils.decorators import admin_required

bp = Blueprint("impostazioni", __name__, url_prefix="/impostazioni")


@bp.route("/")
@login_required
@admin_required
def index():
    users = User.query.order_by(User.username).all()

    backup_settings = {
        "email_to": _get_setting("backup_email_to", "support@cabianca.eu"),
        "hour": _get_setting("backup_hour", "2"),
        "minute": _get_setting("backup_minute", "0"),
        "frequency_days": _get_setting("backup_frequency_days", "1"),
    }

    backup_dir = os.path.join(current_app.root_path, "..", "backups")
    backup_files = []
    if os.path.exists(backup_dir):
        backup_files = sorted(
            [f for f in os.listdir(backup_dir) if f.startswith("gestionale_backup_") and f.endswith(".db")],
            reverse=True,
        )

    return render_template(
        "impostazioni/index.html",
        users=users,
        backup_settings=backup_settings,
        backup_files=backup_files,
    )


def _get_setting(key, default=""):
    s = Setting.query.get(key)
    return s.value if s else default


def _save_setting(key, value):
    s = Setting.query.get(key)
    if s:
        s.value = value
    else:
        db.session.add(Setting(key=key, value=value))


@bp.route("/utente/nuovo", methods=["POST"])
@login_required
@admin_required
def new_user():
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")
    display_name = request.form.get("display_name", "").strip()
    role = request.form.get("role", "operatore")
    sections = request.form.getlist("sections") or ["finanza"]

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
        sections=json.dumps(sections),
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


@bp.route("/backup/impostazioni", methods=["POST"])
@login_required
@admin_required
def save_backup_settings():
    email_to = request.form.get("backup_email_to", "").strip()
    hour = request.form.get("backup_hour", "2")
    minute = request.form.get("backup_minute", "0")
    frequency_days = request.form.get("backup_frequency_days", "1")

    _save_setting("backup_email_to", email_to)
    _save_setting("backup_hour", hour)
    _save_setting("backup_minute", minute)
    _save_setting("backup_frequency_days", frequency_days)
    db.session.commit()

    # Rischedula il job backup con la nuova ora
    try:
        scheduler = getattr(current_app._get_current_object(), "scheduler", None)
        if scheduler:
            scheduler.reschedule_job("backup", trigger="cron", hour=int(hour), minute=int(minute))
    except Exception as e:
        current_app.logger.warning(f"Impossibile aggiornare scheduler: {e}")

    flash("Impostazioni backup salvate.", "success")
    return redirect(url_for("impostazioni.index"))


@bp.route("/backup/ripristina", methods=["POST"])
@login_required
@admin_required
def restore_backup():
    filename = request.form.get("backup_file", "")

    # Validazione sicurezza: solo file backup con nome atteso
    if not filename or not filename.startswith("gestionale_backup_") or not filename.endswith(".db"):
        flash("File non valido.", "danger")
        return redirect(url_for("impostazioni.index"))

    backup_dir = os.path.abspath(os.path.join(current_app.root_path, "..", "backups"))
    backup_path = os.path.abspath(os.path.join(backup_dir, filename))

    if not backup_path.startswith(backup_dir):
        flash("Percorso non valido.", "danger")
        return redirect(url_for("impostazioni.index"))

    if not os.path.exists(backup_path):
        flash("File di backup non trovato.", "danger")
        return redirect(url_for("impostazioni.index"))

    try:
        uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
        db_path = uri.replace("sqlite:///", "")

        db.engine.dispose()
        shutil.copy2(backup_path, db_path)

        logout_user()
        flash("Ripristino completato. Effettua nuovamente il login.", "success")
        return redirect(url_for("auth.login"))
    except Exception as e:
        flash(f"Errore durante il ripristino: {e}", "danger")
        return redirect(url_for("impostazioni.index"))
