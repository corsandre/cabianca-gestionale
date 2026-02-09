import os
import logging
from flask import Flask, render_template_string
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
        app.logger.warning(f"CSRF error: {e.description}")
        return render_template_string(ERROR_TEMPLATE,
            title="Sessione scaduta",
            message="Il modulo e' scaduto. Torna indietro e riprova."), 400

    @app.errorhandler(400)
    def handle_400(e):
        return render_template_string(ERROR_TEMPLATE,
            title="Richiesta non valida",
            message="Controlla i dati inseriti e riprova."), 400

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
    @app.context_processor
    def inject_globals():
        return {"app_name": "Ca Bianca Gestionale"}

    # Create tables and seed data on first run
    with app.app_context():
        _init_db(app)

    # Start scheduler for backups and notifications
    _init_scheduler(app)

    return app


def _init_db(app):
    import sqlalchemy

    try:
        db.create_all()
    except sqlalchemy.exc.OperationalError:
        pass  # Tables already exist (race condition with multiple workers)

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
            ("Altro", "entrambi", "#7f8c8d"),
        ]
        for name, typ, color in cats:
            db.session.add(Category(name=name, type=typ, color=color))

    db.session.commit()


def _init_scheduler(app):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        scheduler = BackgroundScheduler()

        # Daily backup at 2:00 AM
        def run_backup():
            with app.app_context():
                from app.services.backup import run_backup
                run_backup()

        # Check deadlines every morning at 8:00 AM
        def check_deadlines():
            with app.app_context():
                from app.services.telegram_bot import check_and_notify_deadlines
                check_and_notify_deadlines()

        # Fetch fatture SDI da email (3 volte al giorno)
        def fetch_emails():
            with app.app_context():
                from app.services.email_fetcher import fetch_sdi_emails
                fetch_sdi_emails(app)

        # Sync cassa da 4CloudOffice ogni mattina alle 4:00
        def sync_cassa():
            with app.app_context():
                try:
                    from app.services.cloud_office import sync_cash_register
                    count = sync_cash_register()
                    app.logger.info(f"Sync cassa automatica: {count} giorni aggiornati")
                except Exception as e:
                    app.logger.error(f"Errore sync cassa automatica: {e}")

        scheduler.add_job(run_backup, "cron", hour=2, minute=0)
        if app.config.get("CLOUD_OFFICE_USER") and app.config.get("CLOUD_OFFICE_PASSWORD"):
            scheduler.add_job(sync_cassa, "cron", hour=4, minute=0)
        scheduler.add_job(check_deadlines, "cron", hour=8, minute=0)
        if app.config.get("IMAP_HOST") and app.config.get("IMAP_USER"):
            scheduler.add_job(fetch_emails, "cron", hour="8,14,20", minute=30)
        scheduler.start()
    except Exception:
        pass  # Scheduler is optional, don't crash the app
