from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from app.models import Product, StockMovement
from app.utils.decorators import write_required

bp = Blueprint("inventario", __name__, url_prefix="/inventario")


@bp.route("/")
@login_required
def index():
    search = request.args.get("q", "").strip()
    query = Product.query.filter_by(active=True)
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    products = query.order_by(Product.name).all()
    return render_template("inventario/index.html", products=products)


@bp.route("/nuovo", methods=["GET", "POST"])
@login_required
@write_required
def new():
    if request.method == "POST":
        return _save_product(None)
    return render_template("inventario/form.html", p=None)


@bp.route("/<int:id>/modifica", methods=["GET", "POST"])
@login_required
@write_required
def edit(id):
    p = Product.query.get_or_404(id)
    if request.method == "POST":
        return _save_product(p)
    return render_template("inventario/form.html", p=p)


@bp.route("/<int:id>")
@login_required
def detail(id):
    p = Product.query.get_or_404(id)
    movements = StockMovement.query.filter_by(product_id=id).order_by(StockMovement.date.desc()).limit(50).all()
    return render_template("inventario/detail.html", p=p, movements=movements)


@bp.route("/<int:id>/movimento", methods=["POST"])
@login_required
@write_required
def add_movement(id):
    p = Product.query.get_or_404(id)
    mov_type = request.form.get("type", "carico")
    qty = float(request.form.get("quantity", 0))
    notes = request.form.get("notes", "").strip()
    mov_date = request.form.get("date", str(date.today()))

    if qty <= 0:
        flash("Quantita deve essere maggiore di 0.", "warning")
        return redirect(url_for("inventario.detail", id=id))

    movement = StockMovement(
        product_id=id,
        type=mov_type,
        quantity=qty,
        notes=notes,
        date=date.fromisoformat(mov_date),
        created_by=current_user.id,
    )
    db.session.add(movement)

    if mov_type == "carico":
        p.current_quantity += qty
    else:
        p.current_quantity = max(0, p.current_quantity - qty)

    db.session.commit()
    flash(f"Movimento registrato: {mov_type} {qty} {p.unit}.", "success")
    return redirect(url_for("inventario.detail", id=id))


@bp.route("/<int:id>/elimina", methods=["POST"])
@login_required
@write_required
def delete(id):
    p = Product.query.get_or_404(id)
    p.active = False
    db.session.commit()
    flash("Prodotto disattivato.", "success")
    return redirect(url_for("inventario.index"))


def _save_product(p):
    is_new = p is None
    if is_new:
        p = Product()
    p.name = request.form.get("name", "").strip()
    p.product_category = request.form.get("product_category", "").strip()
    p.unit = request.form.get("unit", "pz")
    p.min_quantity = float(request.form.get("min_quantity", 0))
    p.price = float(request.form.get("price", 0))
    p.notes = request.form.get("notes", "").strip()
    if is_new:
        p.current_quantity = float(request.form.get("current_quantity", 0))
        db.session.add(p)
    db.session.commit()
    flash("Prodotto salvato.", "success")
    return redirect(url_for("inventario.detail", id=p.id))
