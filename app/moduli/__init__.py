"""Registro dei moduli del gestionale (dalla 3.4.0). Vedi README, sezione "Moduli".

Un modulo è un pacchetto in app/moduli/<nome>/ con codice, template, database e versione propri.
È l'UNICO punto di contatto fra il nucleo e i moduli: il nucleo non importa mai il codice di un
modulo se non da qui, e i moduli non si importano fra loro.

Ogni modulo espone nel suo __init__.py:
    NOME       nome breve (uguale alla chiave in MODULI_DISPONIBILI e alla sezione dei permessi)
    VERSIONE   versione del modulo (separata da quella del gestionale)
    migra(app) porta il suo database alla versione del codice; solleva un'eccezione se non può
    registra(app)  registra blueprint e template; chiamata solo se migra() è andata bene
    stato(app) dizionario per /salute (es. {"schema": 3})

Quali moduli caricare lo dice la variabile MODULI:
    assente o "tutti"   → tutti quelli in MODULI_DISPONIBILI
    ""                  → nessuno (per spegnere un modulo senza toccare il codice)
    "prodotti,altro"    → solo quelli elencati

Un modulo che fallisce all'avvio NON ferma il gestionale: resta spento, l'errore va nel registro
e arriva un avviso sul canale Telegram "sistema". Lo stato è in app.extensions["moduli"].
"""
import importlib
import logging
import os
import threading

log = logging.getLogger(__name__)

# nome → pacchetto. Aggiungere qui un modulo nuovo.
MODULI_DISPONIBILI = {
    "prodotti": "app.moduli.prodotti",     # ricettario, libro lotti, etichette (dalla 3.4.1)
}


def moduli_richiesti():
    valore = os.environ.get("MODULI")
    if valore is None or valore.strip().lower() == "tutti":
        return list(MODULI_DISPONIBILI)
    nomi = [n.strip().lower() for n in valore.split(",") if n.strip()]
    sconosciuti = [n for n in nomi if n not in MODULI_DISPONIBILI]
    if sconosciuti:
        log.warning("MODULI: ignoro i moduli sconosciuti %s", sconosciuti)
    return [n for n in nomi if n in MODULI_DISPONIBILI]


def configura_database(app):
    """Aggiunge a SQLALCHEMY_BINDS il database di ogni modulo richiesto che ne dichiara uno.

    Va chiamata da create_app PRIMA di db.init_app: Flask-SQLAlchemy crea i motori dei database
    una volta sola, all'init. Il file sta nella stessa cartella di gestionale.db (data/) con il
    nome dichiarato dal modulo (attributo DATABASE, es. "prodotti.db"); la chiave del bind è il
    nome del modulo, da usare nei modelli come __bind_key__.
    Se un modulo non si importa, qui si salta in silenzio: l'errore lo registra carica().
    """
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite:///"):
        return
    cartella = os.path.dirname(uri[len("sqlite:///"):])
    binds = dict(app.config.get("SQLALCHEMY_BINDS") or {})
    for nome in moduli_richiesti():
        try:
            mod = importlib.import_module(MODULI_DISPONIBILI[nome])
        except Exception:
            continue
        file_db = getattr(mod, "DATABASE", None)
        if file_db:
            binds[nome] = f"sqlite:///{os.path.join(cartella, file_db)}"
    app.config["SQLALCHEMY_BINDS"] = binds


def percorso_database(app, nome):
    """Percorso del file SQLite del modulo `nome` (per le migrazioni con sqlite3 e i backup)."""
    uri = (app.config.get("SQLALCHEMY_BINDS") or {}).get(nome, "")
    return uri[len("sqlite:///"):] if uri.startswith("sqlite:///") else None


def carica(app, migra):
    """Importa, (se migra=True) aggiorna lo schema e registra i moduli richiesti."""
    stati = app.extensions.setdefault("moduli", {})
    for nome in moduli_richiesti():
        stato = {"versione": None, "attivo": False, "errore": None}
        stati[nome] = stato
        try:
            mod = importlib.import_module(MODULI_DISPONIBILI[nome])
            stato["versione"] = getattr(mod, "VERSIONE", None)
            if migra:
                mod.migra(app)
            mod.registra(app)
            stato["attivo"] = True
            stato["modulo"] = mod
            log.info("Modulo %s %s caricato", nome, stato["versione"])
        except Exception as e:                      # un modulo guasto non deve fermare il sito
            stato["errore"] = f"{type(e).__name__}: {e}"
            log.exception("Modulo %s NON caricato", nome)
            _avvisa(app, f"⚠️ <b>Modulo {nome} non avviato</b>\n{stato['errore']}\n"
                         f"Il resto del gestionale funziona; il modulo resta spento finché non si corregge.")
    return stati


def attivi(app):
    """Nomi dei moduli caricati senza errori (per menu e permessi)."""
    return [n for n, s in app.extensions.get("moduli", {}).items() if s.get("attivo")]


def stato_per_salute(app):
    out = {}
    for nome, s in app.extensions.get("moduli", {}).items():
        voce = {"versione": s.get("versione"), "attivo": s.get("attivo"), "errore": s.get("errore")}
        mod = s.get("modulo")
        if mod is not None and hasattr(mod, "stato"):
            try:
                voce.update(mod.stato(app))
            except Exception as e:
                voce["errore_stato"] = str(e)
        out[nome] = voce
    return out


def _avvisa(app, testo):
    """Telegram in un thread: l'avvio del sito non deve aspettare la rete."""
    def invia():
        try:
            with app.app_context():
                from app.services.telegram_bot import send_telegram_message
                send_telegram_message(testo, "sistema")
        except Exception:
            pass
    threading.Thread(target=invia, daemon=True).start()
