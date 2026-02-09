from datetime import datetime, date
from flask_login import UserMixin
from app import db


# === USERS ===

class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="operatore")  # admin, operatore, consulente
    email = db.Column(db.String(120))
    telegram_chat_id = db.Column(db.String(50))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# === CONTACTS (Clienti + Fornitori) ===

class Contact(db.Model):
    __tablename__ = "contacts"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(30), nullable=False)  # cliente_privato, cliente_b2b, scuola_ente, fornitore
    name = db.Column(db.String(200), nullable=False)
    ragione_sociale = db.Column(db.String(200))
    partita_iva = db.Column(db.String(20))
    codice_fiscale = db.Column(db.String(20))
    codice_sdi = db.Column(db.String(10))
    pec = db.Column(db.String(120))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    address = db.Column(db.String(200))
    city = db.Column(db.String(100))
    province = db.Column(db.String(5))
    cap = db.Column(db.String(10))
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    transactions = db.relationship("Transaction", backref="contact", lazy="dynamic")


# === CATEGORIES & TAGS ===

class Category(db.Model):
    __tablename__ = "categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # entrata, uscita, entrambi
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    color = db.Column(db.String(10), default="#7f8c8d")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    children = db.relationship("Category", backref=db.backref("parent", remote_side="Category.id"), lazy="dynamic")
    transactions = db.relationship("Transaction", backref="category", lazy="dynamic")


class Tag(db.Model):
    __tablename__ = "tags"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(10), default="#7f8c8d")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


transaction_tags = db.Table(
    "transaction_tags",
    db.Column("transaction_id", db.Integer, db.ForeignKey("transactions.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tags.id"), primary_key=True),
)


# === REVENUE STREAMS ===

class RevenueStream(db.Model):
    __tablename__ = "revenue_streams"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(200))
    color = db.Column(db.String(10), default="#009d5a")
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship("Transaction", backref="revenue_stream", lazy="dynamic")


# === TRANSACTIONS (Prima Nota) ===

class Transaction(db.Model):
    __tablename__ = "transactions"
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(10), nullable=False)  # entrata, uscita
    source = db.Column(db.String(10), nullable=False)  # sdi, cassa, manuale
    official = db.Column(db.Boolean, default=True)
    amount = db.Column(db.Float, nullable=False)
    iva_amount = db.Column(db.Float, default=0)
    iva_rate = db.Column(db.Float, default=0)  # 0, 4, 5, 10, 22
    net_amount = db.Column(db.Float, default=0)
    date = db.Column(db.Date, nullable=False, default=date.today)
    description = db.Column(db.String(500))
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    revenue_stream_id = db.Column(db.Integer, db.ForeignKey("revenue_streams.id"))
    payment_method = db.Column(db.String(20))  # contanti, bonifico, carta, assegno, altro
    payment_status = db.Column(db.String(20), default="da_pagare")  # da_pagare, pagato, parziale, scaduto
    payment_date = db.Column(db.Date)
    due_date = db.Column(db.Date)
    invoice_id = db.Column(db.Integer, db.ForeignKey("sdi_invoices.id"))
    notes = db.Column(db.Text)
    attachment_path = db.Column(db.String(300))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tags = db.relationship("Tag", secondary=transaction_tags, backref="transactions")
    creator = db.relationship("User", backref="transactions")


# === SDI INVOICES ===

class SdiInvoice(db.Model):
    __tablename__ = "sdi_invoices"
    id = db.Column(db.Integer, primary_key=True)
    xml_filename = db.Column(db.String(200))
    xml_path = db.Column(db.String(300))
    invoice_number = db.Column(db.String(50))
    invoice_date = db.Column(db.Date)
    sender_name = db.Column(db.String(200))
    sender_partita_iva = db.Column(db.String(20))
    sender_codice_fiscale = db.Column(db.String(20))
    receiver_name = db.Column(db.String(200))
    receiver_partita_iva = db.Column(db.String(20))
    total_amount = db.Column(db.Float)
    taxable_amount = db.Column(db.Float)
    iva_amount = db.Column(db.Float)
    invoice_type = db.Column(db.String(20))  # fattura, nota_credito
    direction = db.Column(db.String(10))  # ricevuta, emessa
    parsed_data = db.Column(db.Text)  # JSON with full parsed data
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    transactions = db.relationship("Transaction", backref="invoice", lazy="dynamic")
    uploader = db.relationship("User")


# === INVENTORY ===

class Product(db.Model):
    __tablename__ = "products"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    product_category = db.Column(db.String(100))
    unit = db.Column(db.String(20), default="pz")  # pz, kg, lt, etc.
    current_quantity = db.Column(db.Float, default=0)
    min_quantity = db.Column(db.Float, default=0)
    price = db.Column(db.Float, default=0)
    notes = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    movements = db.relationship("StockMovement", backref="product", lazy="dynamic")


class StockMovement(db.Model):
    __tablename__ = "stock_movements"
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    type = db.Column(db.String(10), nullable=False)  # carico, scarico
    quantity = db.Column(db.Float, nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"))
    notes = db.Column(db.String(300))
    date = db.Column(db.Date, default=date.today)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transaction = db.relationship("Transaction")
    creator = db.relationship("User")


# === CASH REGISTER ===

class CashRegisterDaily(db.Model):
    __tablename__ = "cash_register_daily"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, unique=True, nullable=False)
    total_amount = db.Column(db.Float, default=0)
    details = db.Column(db.Text)  # JSON
    synced_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
