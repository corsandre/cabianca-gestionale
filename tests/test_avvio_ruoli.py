"""Test di avvio per ruolo (app/ruoli.py) e del registro dei moduli (app/moduli), dalla 3.4.0.

Richiede Flask e le dipendenze del gestionale: si lancia con il virtualenv
    .venv/bin/python -m unittest tests.test_avvio_ruoli
Con il python di sistema (senza Flask) i test vengono saltati.

Credenziali: il .env locale può contenere token e password VERI. Prima di importare l'app li
svuotiamo nell'ambiente (load_dotenv non sovrascrive variabili già presenti), così nessun test
manda messaggi Telegram o email.
"""
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

for _v in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_SISTEMA_CHAT_ID", "SMTP_USER", "SMTP_PASSWORD",
           "IMAP_HOST", "IMAP_USER", "IMAP_PASSWORD", "CLOUD_OFFICE_USER", "CLOUD_OFFICE_PASSWORD",
           "FATTURE_EMESSE_MITTENTE"):
    os.environ[_v] = ""
os.environ["COOKIE_SECURE"] = "0"
os.environ["ATTESA_SCHEMA_SECONDI"] = "1"

try:
    import flask  # noqa: F401
    import flask_sqlalchemy  # noqa: F401
    HA_FLASK = True
except ImportError:
    HA_FLASK = False

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _togli_moduli_app():
    """Toglie da sys.modules 'app' e 'app.*' e li restituisce.

    Altri test (es. test_trattamenti.py) mettono in sys.modules un finto pacchetto 'app' con
    moduli finti: qui serve quello vero. Alla fine della classe si rimette tutto com'era.
    """
    tolti = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in tolti:
        del sys.modules[k]
    return tolti


@unittest.skipUnless(HA_FLASK, "serve Flask (usare .venv/bin/python)")
class TestAvvioRuoli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._moduli_altrui = _togli_moduli_app()

    @classmethod
    def tearDownClass(cls):
        _togli_moduli_app()
        sys.modules.update(cls._moduli_altrui)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "gestionale.db")
        from app.config import Config
        self._uri = mock.patch.object(Config, "SQLALCHEMY_DATABASE_URI", f"sqlite:///{self.db_path}")
        self._uri.start()
        self._env = mock.patch.dict(os.environ, {})
        self._env.start()
        os.environ.pop("MODULI", None)

    def tearDown(self):
        self._env.stop()
        self._uri.stop()
        self.tmp.cleanup()

    def _crea(self, ruolo, **env):
        os.environ["RUOLO"] = ruolo
        os.environ.update(env)
        import app as pacchetto
        with mock.patch.object(pacchetto, "_init_scheduler") as sched, \
                mock.patch("app.services.avvio.messaggio_avvio_sito") as msg:
            a = pacchetto.create_app()
        a.config["TESTING"] = True
        return a, sched, msg

    def _schema(self):
        import sqlite3
        con = sqlite3.connect(self.db_path)
        righe = con.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        con.close()
        return righe

    def test_scheduler_solo_servizi_e_completo(self):
        self._crea("web")                                  # crea lo schema
        for ruolo, atteso in (("web", False), ("sviluppo", False), ("impianto", False),
                              ("servizi", True), ("completo", True)):
            _, sched, _ = self._crea(ruolo)
            self.assertEqual(sched.called, atteso, ruolo)

    def test_messaggio_avvio_solo_web(self):
        _, _, msg = self._crea("web")
        self.assertTrue(msg.called)
        _, _, msg = self._crea("sviluppo")
        self.assertFalse(msg.called)

    def test_impianto_e_servizi_non_toccano_lo_schema(self):
        self._crea("web")
        prima = self._schema()
        self._crea("impianto")
        self._crea("servizi")
        self.assertEqual(prima, self._schema())

    def test_web_scrive_versione_schema(self):
        a, _, _ = self._crea("web")
        from app.models import Setting
        from app.version import VERSIONE
        with a.app_context():
            from app import db
            self.assertEqual(db.session.get(Setting, "schema_nucleo").value, VERSIONE)

    def test_ruolo_sconosciuto(self):
        os.environ["RUOLO"] = "boh"
        import app as pacchetto
        with self.assertRaises(ValueError):
            pacchetto.create_app()

    def test_salute(self):
        a, _, _ = self._crea("sviluppo")
        r = a.test_client().get("/salute")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["ruolo"], "sviluppo")

    def test_pagine_senza_errori(self):
        """Ogni pagina GET senza parametri risponde senza errore 500 (anche con i moduli caricati)."""
        a, _, _ = self._crea("sviluppo")
        from app.models import User
        from app import db
        with a.app_context():
            admin = User.query.filter_by(role="admin").first()
            uid = admin.id
        c = a.test_client()
        with c.session_transaction() as s:
            s["_user_id"] = str(uid)
            s["_fresh"] = True
        saltate = ("/logout", "/salute")
        errori = []
        for regola in a.url_map.iter_rules():
            if "GET" not in regola.methods or regola.arguments or regola.endpoint == "static":
                continue
            if regola.rule in saltate or "esporta" in regola.rule or "download" in regola.rule:
                continue
            with mock.patch("requests.get", side_effect=RuntimeError("niente rete nei test")), \
                    mock.patch("requests.post", side_effect=RuntimeError("niente rete nei test")):
                r = c.get(regola.rule)
            if r.status_code >= 500:
                errori.append(f"{regola.rule} → {r.status_code}")
        self.assertEqual(errori, [])


@unittest.skipUnless(HA_FLASK, "serve Flask (usare .venv/bin/python)")
class TestRegistroModuli(TestAvvioRuoli):
    """Moduli finti registrati al volo in MODULI_DISPONIBILI."""

    def _modulo_finto(self, nome, guasto=False):
        from flask import Blueprint
        mod = types.ModuleType(f"modulo_finto_{nome}")
        mod.NOME, mod.VERSIONE = nome, "0.1.0"
        mod.migrato = []
        bp = Blueprint(nome, __name__, url_prefix=f"/{nome}")
        bp.add_url_rule("/", nome, lambda: "ciao")

        def migra(app):
            if guasto:
                raise RuntimeError("schema rotto")
            mod.migrato.append(True)
        mod.migra = migra
        mod.registra = lambda app: app.register_blueprint(bp)
        mod.stato = lambda app: {"schema": 1}
        sys.modules[mod.__name__] = mod
        return mod

    def test_modulo_buono_e_guasto(self):
        from app import moduli
        buono = self._modulo_finto("buono")
        self._modulo_finto("rotto", guasto=True)
        with mock.patch.dict(moduli.MODULI_DISPONIBILI,
                             {"buono": "modulo_finto_buono", "rotto": "modulo_finto_rotto"}, clear=True), \
                mock.patch.object(moduli, "_avvisa") as avvisa:
            a, _, _ = self._crea("sviluppo")
            self.assertEqual(moduli.attivi(a), ["buono"])
            self.assertTrue(avvisa.called)                    # avviso Telegram per il modulo rotto
            self.assertEqual(buono.migrato, [True])
            c = a.test_client()
            self.assertEqual(c.get("/buono/").data, b"ciao")
            r = c.get("/salute")
            self.assertEqual(r.status_code, 503)              # un modulo spento = non tutto ok
            self.assertIn("schema rotto", r.get_json()["moduli"]["rotto"]["errore"])
            self.assertEqual(r.get_json()["moduli"]["buono"]["schema"], 1)

    def test_servizi_non_migra_i_moduli_e_moduli_vuoto(self):
        from app import moduli
        buono = self._modulo_finto("buono")
        with mock.patch.dict(moduli.MODULI_DISPONIBILI, {"buono": "modulo_finto_buono"}, clear=True):
            self._crea("web")
            buono.migrato.clear()
            a, _, _ = self._crea("servizi")
            self.assertEqual(buono.migrato, [])
            self.assertEqual(moduli.attivi(a), ["buono"])
            a, _, _ = self._crea("web", MODULI="")
            self.assertEqual(moduli.attivi(a), [])

    # i test della classe madre non servono due volte
    test_scheduler_solo_servizi_e_completo = None
    test_messaggio_avvio_solo_web = None
    test_impianto_e_servizi_non_toccano_lo_schema = None
    test_web_scrive_versione_schema = None
    test_ruolo_sconosciuto = None
    test_salute = None
    test_pagine_senza_errori = None


if __name__ == "__main__":
    unittest.main()
