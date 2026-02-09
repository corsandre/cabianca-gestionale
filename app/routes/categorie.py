from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from app.models import Category, Tag
from app.utils.decorators import write_required, admin_required

bp = Blueprint("categorie", __name__, url_prefix="/categorie")


@bp.route("/")
@login_required
def index():
    categories = Category.query.filter_by(active=True).order_by(Category.type, Category.name).all()
    tags = Tag.query.order_by(Tag.name).all()
    return render_template("categorie/index.html", categories=categories, tags=tags)


@bp.route("/categoria/nuova", methods=["POST"])
@login_required
@write_required
def new_category():
    name = request.form.get("name", "").strip()
    cat_type = request.form.get("type", "uscita")
    color = request.form.get("color", "#7f8c8d")
    if name:
        db.session.add(Category(name=name, type=cat_type, color=color))
        db.session.commit()
        flash("Categoria creata.", "success")
    return redirect(url_for("categorie.index"))


@bp.route("/categoria/<int:id>/modifica", methods=["POST"])
@login_required
@write_required
def edit_category(id):
    cat = Category.query.get_or_404(id)
    cat.name = request.form.get("name", cat.name).strip()
    cat.type = request.form.get("type", cat.type)
    cat.color = request.form.get("color", cat.color)
    db.session.commit()
    flash("Categoria aggiornata.", "success")
    return redirect(url_for("categorie.index"))


@bp.route("/categoria/<int:id>/elimina", methods=["POST"])
@login_required
@admin_required
def delete_category(id):
    cat = Category.query.get_or_404(id)
    cat.active = False
    db.session.commit()
    flash("Categoria disattivata.", "success")
    return redirect(url_for("categorie.index"))


@bp.route("/tag/nuovo", methods=["POST"])
@login_required
@write_required
def new_tag():
    name = request.form.get("name", "").strip()
    color = request.form.get("color", "#7f8c8d")
    if name:
        db.session.add(Tag(name=name, color=color))
        db.session.commit()
        flash("Tag creato.", "success")
    return redirect(url_for("categorie.index"))


@bp.route("/tag/<int:id>/elimina", methods=["POST"])
@login_required
@admin_required
def delete_tag(id):
    tag = Tag.query.get_or_404(id)
    db.session.delete(tag)
    db.session.commit()
    flash("Tag eliminato.", "success")
    return redirect(url_for("categorie.index"))
