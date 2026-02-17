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
    source = db.Column(db.String(20), nullable=False)  # sdi, cassa, manuale, banca, ricorrente
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
    recurring_expense_id = db.Column(db.Integer, db.ForeignKey("recurring_expenses.id"))
    notes = db.Column(db.Text)
    attachment_path = db.Column(db.String(300))
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tags = db.relationship("Tag", secondary=transaction_tags, backref="transactions")
    creator = db.relationship("User", backref="transactions")
    recurring_template = db.relationship("RecurringExpense", backref="generated_transactions")

    @property
    def bank_match(self):
        """Ritorna il primo BankTransaction collegato, se esiste."""
        return self.bank_matches[0] if self.bank_matches else None


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


# === RECURRING EXPENSES (Templates) ===

class RecurringExpense(db.Model):
    __tablename__ = "recurring_expenses"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=True)

    # Frequenza
    frequency = db.Column(db.String(20), nullable=False, default="mensile")  # mensile, bimestrale, trimestrale, semestrale, annuale, custom
    custom_days = db.Column(db.Integer)  # solo per frequency=custom
    generation_months = db.Column(db.Integer, default=3)  # finestra di generazione
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)  # opzionale
    last_generated_date = db.Column(db.Date)

    # Template transazione
    type = db.Column(db.String(10), nullable=False, default="uscita")  # entrata, uscita
    amount = db.Column(db.Float, nullable=False)
    iva_rate = db.Column(db.Float, default=0)
    description = db.Column(db.String(500))
    contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    revenue_stream_id = db.Column(db.Integer, db.ForeignKey("revenue_streams.id"))
    payment_method = db.Column(db.String(20))
    payment_status = db.Column(db.String(20), default="da_pagare")
    due_days_offset = db.Column(db.Integer, default=0)  # giorni dopo la data per scadenza
    notes = db.Column(db.Text)
    official = db.Column(db.Boolean, default=True)

    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    contact = db.relationship("Contact")
    category = db.relationship("Category")
    revenue_stream = db.relationship("RevenueStream")
    creator = db.relationship("User")


# === BANK RECONCILIATION ===

class AutoRule(db.Model):
    """Regole automatiche unificate per categorizzazione (CBI + SDI + Cassa)."""
    __tablename__ = "auto_rules"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    active = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=0)
    applies_to = db.Column(db.String(20), default="tutti")  # tutti, banca, sdi, cassa

    # Condizioni (opzionali, combinate con AND)
    match_description = db.Column(db.String(300))
    match_counterpart = db.Column(db.String(200))
    match_partita_iva = db.Column(db.String(20))
    match_causale_abi = db.Column(db.String(10))
    match_amount_min = db.Column(db.Float)
    match_amount_max = db.Column(db.Float)
    match_direction = db.Column(db.String(10))  # C/D (CBI), ricevuta/emessa (SDI)

    # Azioni
    action_category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    action_contact_id = db.Column(db.Integer, db.ForeignKey("contacts.id"))
    action_revenue_stream_id = db.Column(db.Integer, db.ForeignKey("revenue_streams.id"))
    action_description = db.Column(db.String(500))
    action_auto_create = db.Column(db.Boolean, default=False)
    action_payment_method = db.Column(db.String(20))  # contanti, bonifico, carta, assegno, altro
    action_iva_rate = db.Column(db.Float)  # 0, 4, 5, 10, 22
    action_notes = db.Column(db.String(500))
    action_date_offset = db.Column(db.Integer)  # giorni da sottrarre alla data
    action_date_end_prev_month = db.Column(db.Boolean, default=False)  # ultimo giorno mese precedente

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    action_category = db.relationship("Category")
    action_contact = db.relationship("Contact")
    action_revenue_stream = db.relationship("RevenueStream")

    bank_transactions = db.relationship("BankTransaction", backref="matched_rule", lazy="dynamic")


class IgnoreReason(db.Model):
    """Motivi di ignorazione per movimenti bancari."""
    __tablename__ = "ignore_reasons"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    color = db.Column(db.String(10), default="#6c757d")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class BankTransaction(db.Model):
    """Movimenti bancari importati da file CBI."""
    __tablename__ = "bank_transactions"
    id = db.Column(db.Integer, primary_key=True)
    operation_date = db.Column(db.Date, nullable=False)
    value_date = db.Column(db.Date)
    amount = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(1), nullable=False)  # C=credito, D=debito
    causale_abi = db.Column(db.String(10))
    causale_description = db.Column(db.String(300))
    counterpart_name = db.Column(db.String(200))
    counterpart_address = db.Column(db.String(300))
    ordinante_abi_cab = db.Column(db.String(20))
    remittance_info = db.Column(db.Text)
    description = db.Column(db.Text)
    reference_code = db.Column(db.String(100))
    raw_data = db.Column(db.Text)
    dedup_hash = db.Column(db.String(64), unique=True)

    status = db.Column(db.String(20), default="non_riconciliato")  # non_riconciliato, riconciliato, ignorato
    matched_transaction_id = db.Column(db.Integer, db.ForeignKey("transactions.id"))
    matched_by = db.Column(db.String(20))  # auto, regola, manuale
    matched_rule_id = db.Column(db.Integer, db.ForeignKey("auto_rules.id"))
    ignore_reason_id = db.Column(db.Integer, db.ForeignKey("ignore_reasons.id"))
    import_batch_id = db.Column(db.String(50))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    matched_transaction = db.relationship("Transaction", backref="bank_matches")
    ignore_reason = db.relationship("IgnoreReason", backref="bank_transactions")


class BankBalance(db.Model):
    """Saldo bancario a una data specifica (da CBI o inserimento manuale)."""
    __tablename__ = "bank_balances"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    balance = db.Column(db.Float, nullable=False)
    balance_type = db.Column(db.String(20), default="chiusura")  # apertura, chiusura
    source = db.Column(db.String(10), default="manuale")  # cbi, manuale
    notes = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
