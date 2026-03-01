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
    sections = db.Column(db.Text, default='["finanza"]')

    def has_section(self, section):
        """Returns True if user has access to the given section. Admins always have access."""
        import json
        if self.role == "admin":
            return True
        try:
            return section in json.loads(self.sections or '["finanza"]')
        except (ValueError, TypeError):
            return section == "finanza"


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


# === APP SETTINGS ===

class Setting(db.Model):
    """Impostazioni applicazione (chiave-valore)."""
    __tablename__ = "settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.String(512))


# === ALLEVAMENTO - Struttura Fisica ===

class Capannone(db.Model):
    __tablename__ = "capannoni"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), nullable=False)
    numero = db.Column(db.Integer, nullable=False, unique=True)
    note = db.Column(db.Text)

    boxes = db.relationship("Box", backref="capannone", lazy="dynamic")


class Box(db.Model):
    __tablename__ = "boxes"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.Integer, nullable=False, unique=True)
    capannone_id = db.Column(db.Integer, db.ForeignKey("capannoni.id"), nullable=False)
    linea_alimentazione = db.Column(db.Integer, nullable=False)  # 1, 2, 3
    superficie_m2 = db.Column(db.Float)
    lunghezza_trogolo_m = db.Column(db.Float)
    note = db.Column(db.Text)

    cicli = db.relationship("BoxCiclo", backref="box", lazy="dynamic")
    manutenzioni = db.relationship("ManutenzioneBox", backref="box", lazy="dynamic",
                                   foreign_keys="ManutenzioneBox.box_id")


# === ALLEVAMENTO - Cicli Produttivi ===

class CicloProduttivo(db.Model):
    __tablename__ = "cicli_produttivi"
    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.String(50), unique=True, nullable=False)  # era lotto_id
    numero_ciclo = db.Column(db.Integer)
    data_inizio = db.Column(db.Date, nullable=False)
    data_chiusura = db.Column(db.Date)
    stato = db.Column(db.String(20), default="attivo")  # attivo, chiuso
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    lotti = db.relationship("Lotto", backref="ciclo", lazy="dynamic")
    box_cicli = db.relationship("BoxCiclo", backref="ciclo", lazy="dynamic")
    creator = db.relationship("User")


class Lotto(db.Model):
    """Singola consegna di suinetti (bolla). Un ciclo ne contiene N."""
    __tablename__ = "lotti"
    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("cicli_produttivi.id"), nullable=False)
    numero_lotto = db.Column(db.Integer, nullable=False)   # 1, 2, 3... per ciclo
    data_consegna = db.Column(db.Date, nullable=False)
    peso_totale_bolla_kg = db.Column(db.Float)
    lettera_nascita = db.Column(db.String(1))              # T,C,B,A,M,P,L,E,S,R,H,D (DOP)
    fornitore = db.Column(db.String(200))
    numero_documento = db.Column(db.String(100))           # numero bolla cartacea
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    box_cicli = db.relationship("BoxCiclo", backref="lotto", lazy="dynamic")
    creator = db.relationship("User")


class BoxCiclo(db.Model):
    __tablename__ = "box_cicli"
    id = db.Column(db.Integer, primary_key=True)
    ciclo_id = db.Column(db.Integer, db.ForeignKey("cicli_produttivi.id"), nullable=False)
    lotto_id = db.Column(db.Integer, db.ForeignKey("lotti.id"))        # bolla di riferimento
    lettera_nascita = db.Column(db.String(1))                          # copia dalla bolla
    box_id = db.Column(db.Integer, db.ForeignKey("boxes.id"), nullable=False)
    data_accasamento = db.Column(db.Date, nullable=False)
    capi_iniziali = db.Column(db.Integer, nullable=False)
    peso_totale_iniziale = db.Column(db.Float)
    peso_medio_iniziale = db.Column(db.Float)
    eta_stimata_gg = db.Column(db.Integer)
    capi_presenti = db.Column(db.Integer)
    stato = db.Column(db.String(20), default="attivo")  # attivo, in_uscita, chiuso
    note = db.Column(db.Text)

    eventi = db.relationship("EventoCiclo", backref="box_ciclo", lazy="dynamic")
    trattamenti = db.relationship("TrattamentoSanitario", backref="box_ciclo", lazy="dynamic")
    inappetenze = db.relationship("InappetenzaBox", backref="box_ciclo", lazy="dynamic")


class EventoCiclo(db.Model):
    __tablename__ = "eventi_ciclo"
    id = db.Column(db.Integer, primary_key=True)
    box_ciclo_id = db.Column(db.Integer, db.ForeignKey("box_cicli.id"), nullable=False)
    tipo = db.Column(db.String(30), nullable=False)  # mortalita, frazionamento_in, frazionamento_out, uscita_macello
    data = db.Column(db.Date, nullable=False, default=date.today)
    quantita = db.Column(db.Integer)
    peso_totale = db.Column(db.Float)
    note = db.Column(db.Text)
    operatore_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_scarti = db.Column(db.Boolean, default=False, nullable=False)

    operatore = db.relationship("User")


# === ALLEVAMENTO - Sanità ===

class TrattamentoSanitario(db.Model):
    __tablename__ = "trattamenti_sanitari"
    id = db.Column(db.Integer, primary_key=True)
    box_ciclo_id = db.Column(db.Integer, db.ForeignKey("box_cicli.id"), nullable=False)
    tipo = db.Column(db.String(100))
    farmaco = db.Column(db.String(200))
    via_somministrazione = db.Column(db.String(50))  # orale, iniettiva, topica
    data_inizio = db.Column(db.Date, nullable=False, default=date.today)
    durata_giorni = db.Column(db.Integer, default=1)
    intervallo_ore = db.Column(db.Integer, default=24)
    note = db.Column(db.Text)
    operatore_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    operatore = db.relationship("User")


class InappetenzaBox(db.Model):
    __tablename__ = "inappetenza_box"
    id = db.Column(db.Integer, primary_key=True)
    box_ciclo_id = db.Column(db.Integer, db.ForeignKey("box_cicli.id"), nullable=False)
    percentuale_razione = db.Column(db.Float, default=100.0)
    data_inizio = db.Column(db.Date, nullable=False, default=date.today)
    data_fine = db.Column(db.Date)
    note = db.Column(db.Text)


# === ALLEVAMENTO - Alimentazione ===

class CurvaAccrescimento(db.Model):
    __tablename__ = "curva_accrescimento"
    id = db.Column(db.Integer, primary_key=True)
    eta_giorni = db.Column(db.Integer, nullable=False, unique=True)
    peso_kg = db.Column(db.Float, nullable=False)
    razione_kg_giorno = db.Column(db.Float, nullable=False)


class TabellaSostSiero(db.Model):
    __tablename__ = "tabella_sost_siero"
    id = db.Column(db.Integer, primary_key=True)
    eta_min = db.Column(db.Integer, nullable=False)
    eta_max = db.Column(db.Integer, nullable=False)
    percentuale_siero = db.Column(db.Float, nullable=False)


class RazioneGiornaliera(db.Model):
    __tablename__ = "razioni_giornaliere"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    linea = db.Column(db.Integer, nullable=False)
    razione_teorica_kg = db.Column(db.Float)
    consumo_mangime_kg = db.Column(db.Float)
    consumo_siero_litri = db.Column(db.Float)
    consumo_acqua_litri = db.Column(db.Float)
    acqua_teorica_litri = db.Column(db.Float)
    note = db.Column(db.Text)

    __table_args__ = (db.UniqueConstraint("data", "linea", name="_data_linea_uc"),)


class OrarioPasto(db.Model):
    __tablename__ = "orari_pasto"
    numero = db.Column(db.Integer, primary_key=True)  # 1, 2, 3
    ora = db.Column(db.Time, nullable=False)
    attivo = db.Column(db.Boolean, default=True)


class RazionePasto(db.Model):
    __tablename__ = "razioni_pasto"
    id = db.Column(db.Integer, primary_key=True)
    data = db.Column(db.Date, nullable=False)
    numero_pasto = db.Column(db.Integer, nullable=False)  # 1, 2, 3
    linea = db.Column(db.Integer, nullable=False)  # 1, 2, 3
    consumo_mangime_kg = db.Column(db.Float)
    consumo_siero_litri = db.Column(db.Float)
    consumo_acqua_litri = db.Column(db.Float)
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("data", "numero_pasto", "linea", name="_data_pasto_linea_uc"),)


# === ALLEVAMENTO - Magazzino & Ordini ===

class MagazzinoProdotto(db.Model):
    __tablename__ = "magazzino_prodotti"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False, unique=True)  # mangime, siero
    quantita_attuale_q = db.Column(db.Float, default=0.0)
    capacita_massima_q = db.Column(db.Float)
    soglia_minima_q = db.Column(db.Float, default=10.0)


class ConsegnaAlimentare(db.Model):
    __tablename__ = "consegne_alimentari"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # mangime, siero
    data = db.Column(db.Date, nullable=False, default=date.today)
    quantita_q = db.Column(db.Float, nullable=False)
    fornitore = db.Column(db.String(200))
    percentuale_ss_siero = db.Column(db.Float)
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User")


class OrdineAlimentare(db.Model):
    __tablename__ = "ordini_alimentari"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(20), nullable=False)  # mangime, siero
    data_ordine = db.Column(db.Date, nullable=False, default=date.today)
    quantita_q = db.Column(db.Float, nullable=False)
    fornitore = db.Column(db.String(200))
    stato = db.Column(db.String(20), default="bozza")  # bozza, inviato, confermato, validato
    data_consegna = db.Column(db.Date)
    note = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    creator = db.relationship("User")


# === ALLEVAMENTO - Allarmi & Manutenzioni ===

class Allarme(db.Model):
    __tablename__ = "allarmi"
    id = db.Column(db.Integer, primary_key=True)
    tipo = db.Column(db.String(50), nullable=False)
    messaggio = db.Column(db.String(500), nullable=False)
    riferimento_tipo = db.Column(db.String(50))
    riferimento_id = db.Column(db.Integer)
    data_creazione = db.Column(db.DateTime, default=datetime.utcnow)
    data_scadenza = db.Column(db.DateTime)
    stato = db.Column(db.String(20), default="attivo")  # attivo, risolto, silenziato
    silenziato_fino = db.Column(db.DateTime)


class ManutenzioneBox(db.Model):
    __tablename__ = "manutenzioni_box"
    id = db.Column(db.Integer, primary_key=True)
    box_id = db.Column(db.Integer, db.ForeignKey("boxes.id"))
    capannone_id = db.Column(db.Integer, db.ForeignKey("capannoni.id"))
    tipo_attivita = db.Column(db.String(200), nullable=False)
    scadenza = db.Column(db.Date)
    stato = db.Column(db.String(20), default="da_fare")  # da_fare, eseguita
    data_esecuzione = db.Column(db.Date)
    note = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    capannone = db.relationship("Capannone", backref="manutenzioni")
