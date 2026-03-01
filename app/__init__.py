import os
import logging
from flask import Flask, render_template_string, flash, redirect, request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect, CSRFError

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()


def create_app():
    app = Flask(__name__)
    app.config.from_object("app.config.Config")

    # Ensure data directory exists
    os.makedirs(os.path.join(app.root_path, "..", "data"), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Fix SQLite path to be absolute
    db_uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if db_uri.startswith("sqlite:///") and not db_uri.startswith("sqlite:////"):
        db_path = db_uri.replace("sqlite:///", "")
        abs_path = os.path.join(app.root_path, "..", db_path)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.abspath(abs_path)}"

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Effettua il login per accedere."
    login_manager.login_message_category = "warning"

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Register blueprints
    from app.routes.auth import bp as auth_bp
    from app.routes.dashboard import bp as dashboard_bp
    from app.routes.prima_nota import bp as prima_nota_bp
    from app.routes.fatture import bp as fatture_bp
    from app.routes.cassa import bp as cassa_bp
    from app.routes.movimenti import bp as movimenti_bp
    from app.routes.anagrafica import bp as anagrafica_bp
    from app.routes.inventario import bp as inventario_bp
    from app.routes.categorie import bp as categorie_bp
    from app.routes.analisi import bp as analisi_bp
    from app.routes.scadenzario import bp as scadenzario_bp
    from app.routes.impostazioni import bp as impostazioni_bp
    from app.routes.banca import bp as banca_bp
    from app.routes.ricorrenti import bp as ricorrenti_bp
    from app.routes.finanza_impostazioni import bp as finanza_impostazioni_bp
    from app.routes.allevamento import bp as allevamento_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(prima_nota_bp)
    app.register_blueprint(fatture_bp)
    app.register_blueprint(cassa_bp)
    app.register_blueprint(movimenti_bp)
    app.register_blueprint(anagrafica_bp)
    app.register_blueprint(inventario_bp)
    app.register_blueprint(categorie_bp)
    app.register_blueprint(analisi_bp)
    app.register_blueprint(scadenzario_bp)
    app.register_blueprint(impostazioni_bp)
    app.register_blueprint(banca_bp)
    app.register_blueprint(ricorrenti_bp)
    app.register_blueprint(finanza_impostazioni_bp)
    app.register_blueprint(allevamento_bp)

    # Logging
    logging.basicConfig(level=logging.INFO)
    app.logger.setLevel(logging.INFO)

    # Error handlers
    ERROR_TEMPLATE = '''
    {% extends "base.html" %}
    {% block title %}Errore - Ca Bianca Gestionale{% endblock %}
    {% block content %}
    <div class="cb-card p-4 text-center" style="max-width:500px;margin:2rem auto">
        <h2 class="text-danger mb-3">{{ title }}</h2>
        <p>{{ message }}</p>
        <a href="{{ url_for('dashboard.index') }}" class="btn btn-cb mt-2">Torna al cruscotto</a>
    </div>
    {% endblock %}
    {% block public_content %}
    <div class="cb-login-container">
        <div class="cb-login-card text-center">
            <h2 class="text-danger">{{ title }}</h2>
            <p>{{ message }}</p>
            <a href="{{ url_for('auth.login') }}" class="btn btn-cb mt-2">Torna al login</a>
        </div>
    </div>
    {% endblock %}
    '''

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        import sys
        from flask_login import current_user
        try:
            is_auth = current_user.is_authenticated
            print(f"[CSRF] {e.description} | URL={request.url} | auth={is_auth} | referrer={request.referrer}", file=sys.stderr, flush=True)
            if is_auth:
                flash("Sessione scaduta: ricarica la pagina e riprova.", "warning")
                return redirect(request.referrer or request.url)
        except Exception as exc:
            print(f"[CSRF] handler exception: {exc}", file=sys.stderr, flush=True)
        return ("<h2>Sessione scaduta</h2>"
                "<p>Il modulo e' scaduto. <a href='/login'>Torna al login</a></p>"), 400

    @app.errorhandler(400)
    def handle_400(e):
        import sys
        ct = request.content_type or 'none'
        cl = request.content_length or 0
        print(f"[400] {e} | URL={request.url} | method={request.method} | content-type={ct} | content-length={cl}", file=sys.stderr, flush=True)
        return ("<h2>Richiesta non valida</h2>"
                "<p>Controlla i dati inseriti e riprova. "
                "<a href='javascript:history.back()'>Torna indietro</a></p>"), 400

    @app.errorhandler(403)
    def handle_403(e):
        return render_template_string(ERROR_TEMPLATE,
            title="Accesso negato",
            message="Non hai i permessi per questa operazione."), 403

    @app.errorhandler(404)
    def handle_404(e):
        return render_template_string(ERROR_TEMPLATE,
            title="Pagina non trovata",
            message="La pagina richiesta non esiste."), 404

    @app.errorhandler(500)
    def handle_500(e):
        app.logger.error(f"Internal error: {e}")
        return render_template_string(ERROR_TEMPLATE,
            title="Errore interno",
            message="Si e' verificato un errore. Riprova tra qualche istante."), 500

    # Template context
    BLUEPRINT_SECTION_MAP = {
        'prima_nota': 'finanza', 'fatture': 'finanza', 'cassa': 'finanza',
        'movimenti': 'finanza', 'anagrafica': 'finanza', 'inventario': 'finanza',
        'categorie': 'finanza', 'analisi': 'finanza', 'scadenzario': 'finanza',
        'banca': 'finanza', 'ricorrenti': 'finanza', 'finanza_impostazioni': 'finanza',
        'allevamento': 'allevamento',
    }

    @app.context_processor
    def inject_globals():
        current_section = BLUEPRINT_SECTION_MAP.get(request.blueprint, 'finanza')
        return {"app_name": "Ca Bianca Gestionale", "current_section": current_section}

    # Create tables and seed data on first run
    with app.app_context():
        _init_db(app)

    # Start scheduler for backups and notifications
    _init_scheduler(app)

    return app


def _pre_migrate_rename(sqlalchemy):
    """Rinomina tabelle/colonne legacy prima che create_all usi i nuovi nomi."""
    try:
        r = db.session.execute(sqlalchemy.text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lotti_produttivi'"
        ))
        if r.fetchone():
            db.session.execute(sqlalchemy.text(
                "ALTER TABLE lotti_produttivi RENAME TO cicli_produttivi"))
            db.session.execute(sqlalchemy.text(
                "ALTER TABLE cicli_produttivi RENAME COLUMN lotto_id TO ciclo_id"))
            db.session.execute(sqlalchemy.text(
                "ALTER TABLE box_cicli RENAME COLUMN lotto_id TO ciclo_id"))
            db.session.commit()
    except Exception as e:
        db.session.rollback()


def _init_db(app):
    import sqlalchemy

    _pre_migrate_rename(sqlalchemy)

    try:
        db.create_all()
    except sqlalchemy.exc.OperationalError:
        pass  # Tables already exist (race condition with multiple workers)

    # Migrazioni incrementali per colonne aggiunte dopo il primo deploy
    _migrate_columns = [
        ("auto_rules", "action_payment_method", "VARCHAR(20)"),
        ("auto_rules", "action_iva_rate", "FLOAT"),
        ("auto_rules", "action_notes", "VARCHAR(500)"),
        ("auto_rules", "action_date_offset", "INTEGER"),
        ("auto_rules", "action_date_end_prev_month", "BOOLEAN DEFAULT 0"),
        ("bank_transactions", "ignore_reason_id", "INTEGER REFERENCES ignore_reasons(id)"),
        ("transactions", "recurring_expense_id", "INTEGER REFERENCES recurring_expenses(id)"),
        ("bank_transactions", "description", "TEXT"),
        ("users", "sections", "TEXT DEFAULT '[\"finanza\"]'"),
        ("razioni_giornaliere", "consumo_acqua_litri", "REAL"),
        ("razioni_giornaliere", "acqua_teorica_litri", "REAL"),
        ("eventi_ciclo", "is_scarti", "INTEGER DEFAULT 0 NOT NULL"),
        ("box_cicli", "lotto_id", "INTEGER REFERENCES lotti(id)"),
        ("box_cicli", "lettera_nascita", "VARCHAR(1)"),
    ]
    for table, col, col_type in _migrate_columns:
        try:
            db.session.execute(sqlalchemy.text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
            db.session.commit()
        except sqlalchemy.exc.OperationalError:
            db.session.rollback()  # Column already exists

    # Backfill: ensure existing users have sections set
    try:
        db.session.execute(sqlalchemy.text("UPDATE users SET sections = '[\"finanza\"]' WHERE sections IS NULL"))
        db.session.commit()
    except sqlalchemy.exc.OperationalError:
        db.session.rollback()

    # Indici per prestazioni query frequenti
    _indexes = [
        ("ix_bt_status", "bank_transactions", "status"),
        ("ix_bt_op_date", "bank_transactions", "operation_date"),
        ("ix_bt_matched_tx", "bank_transactions", "matched_transaction_id"),
        ("ix_tx_source", "transactions", "source"),
        ("ix_tx_date", "transactions", "date"),
        ("ix_tx_payment_status", "transactions", "payment_status"),
        ("ix_tx_invoice_id", "transactions", "invoice_id"),
        ("ix_sdi_date", "sdi_invoices", "invoice_date"),
    ]
    for ix_name, table, col in _indexes:
        try:
            db.session.execute(sqlalchemy.text(
                f"CREATE INDEX IF NOT EXISTS {ix_name} ON {table}({col})"
            ))
            db.session.commit()
        except sqlalchemy.exc.OperationalError:
            db.session.rollback()

    from app.models import User, RevenueStream, Category
    import bcrypt

    # Create admin if no users exist
    try:
        user_count = User.query.count()
    except sqlalchemy.exc.OperationalError:
        return  # DB not ready yet, another worker will handle it

    if user_count == 0:
        pw = app.config["ADMIN_PASSWORD"]
        admin = User(
            username=app.config["ADMIN_USERNAME"],
            password_hash=bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode(),
            display_name=app.config["ADMIN_DISPLAY_NAME"],
            role="admin",
            active=True,
        )
        db.session.add(admin)

    # Seed revenue streams
    if RevenueStream.query.count() == 0:
        streams = [
            ("Vendita diretta", "Vendita al pubblico in azienda", "#297a38"),
            ("Attivita didattiche", "Visite scolastiche e laboratori", "#243673"),
            ("B2B", "Vendita a imprese e ristoranti", "#c6a96f"),
            ("Agriturismo", "Ristorazione aziendale ad eventi", "#fcc900"),
            ("Allevamento suini", "Attivita di ingrasso suini", "#009d5a"),
        ]
        for name, desc, color in streams:
            db.session.add(RevenueStream(name=name, description=desc, color=color))

    # Seed default categories
    if Category.query.count() == 0:
        cats = [
            ("Vendita prodotti", "entrata", "#297a38"),
            ("Servizi", "entrata", "#243673"),
            ("Fattoria Didattica", "entrata", "#243673"),
            ("Ristorazione", "entrata", "#c6a96f"),
            ("Vendita animali", "entrata", "#009d5a"),
            ("Mangimi e foraggi", "uscita", "#e74c3c"),
            ("Materie prime", "uscita", "#e67e22"),
            ("Utenze", "uscita", "#f39c12"),
            ("Manutenzione", "uscita", "#9b59b6"),
            ("Personale", "uscita", "#3498db"),
            ("Carburante", "uscita", "#1abc9c"),
            ("Assicurazioni", "uscita", "#34495e"),
            ("Consulenze", "uscita", "#95a5a6"),
            ("Attrezzature", "uscita", "#2c3e50"),
            ("Tasse e imposte", "uscita", "#c0392b"),
            ("Trasferimento interno", "entrambi", "#17a2b8"),
            ("Altro", "entrambi", "#7f8c8d"),
        ]
        for name, typ, color in cats:
            db.session.add(Category(name=name, type=typ, color=color))

    # Seed default backup settings
    from app.models import Setting
    defaults = {
        "backup_email_to": "support@cabianca.eu",
        "backup_hour": "2",
        "backup_minute": "0",
        "backup_frequency_days": "1",
        "numero_pasti": "3",
        "rapporto_ss": "10",
        "rapporto_liquido": "31",
        "cisterna_buffer_minuti": "60",
    }
    for key, value in defaults.items():
        if not Setting.query.get(key):
            db.session.add(Setting(key=key, value=value))
    db.session.commit()

    # Seed orari pasto (solo se non esistono)
    from app.models import OrarioPasto
    from datetime import time as dt_time
    try:
        if OrarioPasto.query.count() == 0:
            for n, h in [(1, 7), (2, 13), (3, 18)]:
                db.session.add(OrarioPasto(numero=n, ora=dt_time(h, 0), attivo=True))
            db.session.commit()
    except Exception:
        db.session.rollback()

    # Seed allevamento struttura fisica (solo se non esiste)
    from app.models import Capannone, Box, MagazzinoProdotto, CurvaAccrescimento, TabellaSostSiero
    try:
        if Box.query.count() == 0:
            _seed_allevamento()
    except Exception:
        db.session.rollback()

    # Migrazione: sostituisci curva accrescimento default con dati reali utente
    # Il seed default inizia da eta_giorni=60; se troviamo quello, sostituiamo tutto.
    try:
        first_curva = CurvaAccrescimento.query.order_by(CurvaAccrescimento.eta_giorni).first()
        if first_curva and first_curva.eta_giorni == 60:
            CURVA_REALE = [
                (0,   20.0, 1.00), (7,   30.0, 1.30), (14,  34.0, 1.50), (21,  38.2, 1.70),
                (28,  42.8, 1.85), (35,  47.5, 2.00), (42,  52.3, 2.00), (49,  57.2, 2.10),
                (56,  62.2, 2.20), (63,  67.3, 2.30), (70,  72.5, 2.40), (77,  77.7, 2.50),
                (84,  83.0, 2.60), (91,  88.4, 2.60), (98,  93.8, 2.70), (105, 99.3, 2.70),
                (112, 104.8, 2.80), (119, 110.3, 2.80), (126, 115.8, 2.85), (133, 121.2, 2.85),
                (140, 126.5, 2.90), (147, 131.7, 2.90), (154, 136.8, 2.90), (161, 141.8, 2.90),
                (168, 146.8, 2.95), (175, 151.6, 2.95), (182, 156.2, 2.95),
                (189, 160.6, 3.00), (196, 164.9, 3.00),
                (203, 169.1, 3.10), (210, 173.0, 3.10), (217, 174.0, 3.10),
            ]
            # percentuale_siero = kg_siero_die * perc_ss_siero(5%) / razione_kg * 100
            SIERO_REALE = [
                (0,   27,  0.00),   # sett. 1-4: nessun siero
                (28,  34,  2.70),   # sett. 5:  1.0 kg/die
                (35,  41,  3.75),   # sett. 6:  1.5 kg/die
                (42,  48,  5.00),   # sett. 7:  2.0 kg/die
                (49,  55,  5.95),   # sett. 8:  2.5 kg/die
                (56,  62,  7.95),   # sett. 9:  3.5 kg/die
                (63,  69,  9.78),   # sett. 10: 4.5 kg/die
                (70,  76, 11.46),   # sett. 11: 5.5 kg/die
                (77,  83, 13.00),   # sett. 12: 6.5 kg/die
                (84,  90, 15.38),   # sett. 13: 8.0 kg/die
                (91,  97, 17.31),   # sett. 14: 9.0 kg/die
                (98,  111, 18.52),  # sett. 15-16: 10.0 kg/die
                (112, 125, 19.64),  # sett. 17-18: 11.0 kg/die
                (126, 139, 21.05),  # sett. 19-20: 12.0 kg/die (raz=2.85)
                (140, 167, 20.69),  # sett. 21-24: 12.0 kg/die (raz=2.90)
                (168, 188, 20.34),  # sett. 25-27: 12.0 kg/die (raz=2.95)
                (189, 202, 20.00),  # sett. 28-29: 12.0 kg/die (raz=3.00)
                (203, 999, 19.35),  # sett. 30+:   12.0 kg/die (raz=3.10)
            ]
            CurvaAccrescimento.query.delete()
            TabellaSostSiero.query.delete()
            for eta, peso, razione in CURVA_REALE:
                db.session.add(CurvaAccrescimento(
                    eta_giorni=eta, peso_kg=peso, razione_kg_giorno=razione))
            for eta_min, eta_max, perc in SIERO_REALE:
                db.session.add(TabellaSostSiero(
                    eta_min=eta_min, eta_max=eta_max, percentuale_siero=perc))
            s = Setting.query.get("allevamento_perc_ss_siero")
            if s:
                s.value = "5.0"
            else:
                db.session.add(Setting(key="allevamento_perc_ss_siero", value="5.0"))
            db.session.commit()
            app.logger.info("Migrazione curva accrescimento e tabella siero: completata.")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Errore migrazione curva accrescimento: {e}")


def _seed_allevamento():
    from app.models import Capannone, Box, MagazzinoProdotto, CurvaAccrescimento, TabellaSostSiero

    # Capannoni
    caps = {}
    for numero, nome in [(1, "CAP 1"), (2, "CAP 2"), (3, "CAP 3"), (4, "CAP 4"),
                         (5, "CAP 5"), (6, "CAP 6"), (7, "CAP 7")]:
        c = Capannone(numero=numero, nome=nome)
        db.session.add(c)
        db.session.flush()
        caps[numero] = c.id

    # Box: (numero, cap_numero, linea, superficie_m2, trogolo_m)
    boxes_data = (
        # CAP 1: box 1-9, linea 1, 40 posti cad.
        [(i, 1, 1, 40.0, 13.2) for i in range(1, 10)] +
        # CAP 2: box 10-15, linea 1, 26 posti cad.
        [(i, 2, 1, 26.0, 8.6) for i in range(10, 16)] +
        # CAP 3: box 16-21, linea 1, 10 posti cad.
        [(i, 3, 1, 10.0, 3.3) for i in range(16, 22)] +
        # CAP 4: box 22-36, linea 2, 38 posti cad.
        [(i, 4, 2, 38.0, 12.5) for i in range(22, 37)] +
        # CAP 5: box 37-42, linea 3, 38 posti cad.
        [(i, 5, 3, 38.0, 12.5) for i in range(37, 43)] +
        # CAP 7: box 43-48 (31 posti), box 49 (deposito 32 posti), linea 3
        [(i, 7, 3, 31.0, 10.2) for i in range(43, 49)] +
        [(49, 7, 3, 32.0, 10.6)] +
        # CAP 6: box 50-54, linea 3, ~46 posti cad.
        [(50, 6, 3, 47.0, 15.5), (51, 6, 3, 47.0, 15.5), (52, 6, 3, 46.0, 15.2),
         (53, 6, 3, 45.0, 14.8), (54, 6, 3, 45.0, 14.8)]
    )
    for numero, cap_num, linea, sup, trogolo in boxes_data:
        db.session.add(Box(
            numero=numero,
            capannone_id=caps[cap_num],
            linea_alimentazione=linea,
            superficie_m2=sup,
            lunghezza_trogolo_m=trogolo,
        ))

    # Magazzino prodotti
    for tipo, cap_max, soglia in [("mangime", 300.0, 30.0), ("siero", 200.0, 20.0)]:
        db.session.add(MagazzinoProdotto(tipo=tipo, capacita_massima_q=cap_max, soglia_minima_q=soglia))

    # Curva accrescimento (suino pesante italiano, giorni-peso-razione)
    curva = [
        (60, 20.0, 0.80), (70, 25.0, 0.90), (80, 30.0, 1.05), (90, 35.0, 1.20),
        (100, 42.0, 1.38), (110, 48.0, 1.52), (120, 55.0, 1.67), (130, 62.0, 1.82),
        (140, 70.0, 2.00), (150, 78.0, 2.17), (160, 87.0, 2.36), (170, 95.0, 2.50),
        (180, 104.0, 2.65), (190, 112.0, 2.78), (200, 120.0, 2.88), (210, 128.0, 2.97),
        (220, 135.0, 3.04), (230, 142.0, 3.10), (240, 149.0, 3.14), (250, 155.0, 3.17),
        (260, 160.0, 3.18),
    ]
    for eta, peso, razione in curva:
        db.session.add(CurvaAccrescimento(eta_giorni=eta, peso_kg=peso, razione_kg_giorno=razione))

    # Tabella sostituzione siero
    for eta_min, eta_max, perc in [(0, 90, 35.0), (91, 150, 25.0), (151, 999, 15.0)]:
        db.session.add(TabellaSostSiero(eta_min=eta_min, eta_max=eta_max, percentuale_siero=perc))

    db.session.commit()


def _init_scheduler(app):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        # Legge ora backup da impostazioni DB
        with app.app_context():
            from app.models import Setting
            hour_s = Setting.query.get("backup_hour")
            minute_s = Setting.query.get("backup_minute")
            backup_hour = int(hour_s.value) if hour_s else 2
            backup_minute = int(minute_s.value) if minute_s else 0

        def run_backup():
            with app.app_context():
                from app.services.backup import run_backup
                run_backup()

        def check_deadlines():
            with app.app_context():
                from app.services.telegram_bot import check_and_notify_deadlines
                check_and_notify_deadlines()

        def fetch_emails():
            with app.app_context():
                from app.services.email_fetcher import fetch_sdi_emails
                fetch_sdi_emails(app)

        def sync_cassa():
            with app.app_context():
                try:
                    from app.services.cloud_office import sync_cash_register
                    count = sync_cash_register()
                    app.logger.info(f"Sync cassa automatica: {count} giorni aggiornati")
                except Exception as e:
                    app.logger.error(f"Errore sync cassa automatica: {e}")

        def generate_recurring():
            with app.app_context():
                try:
                    from app.services.recurring_generator import generate_all
                    count = generate_all()
                    if count:
                        app.logger.info(f"Spese ricorrenti: {count} transazioni generate")
                except Exception as e:
                    app.logger.error(f"Errore generazione ricorrenti: {e}")

        def generate_allevamento_alarms():
            with app.app_context():
                try:
                    from app.services.allevamento_alarms import rigenera_allarmi
                    rigenera_allarmi()
                except Exception as e:
                    app.logger.error(f"Errore generazione allarmi allevamento: {e}")

        scheduler.add_job(generate_recurring, "cron", hour=3, minute=0)
        scheduler.add_job(generate_allevamento_alarms, "cron", hour=6, minute=0)
        scheduler.add_job(run_backup, "cron", hour=backup_hour, minute=backup_minute, id="backup")
        if app.config.get("CLOUD_OFFICE_USER") and app.config.get("CLOUD_OFFICE_PASSWORD"):
            scheduler.add_job(sync_cassa, "cron", hour=4, minute=0)
        scheduler.add_job(check_deadlines, "cron", hour=8, minute=0)
        if app.config.get("IMAP_HOST") and app.config.get("IMAP_USER"):
            scheduler.add_job(fetch_emails, "cron", hour="8,14,20", minute=30)
        scheduler.start()
        app.scheduler = scheduler
    except Exception:
        pass  # Scheduler is optional, don't crash the app
