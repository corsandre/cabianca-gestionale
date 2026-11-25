"""Test del modulo Prodotti dentro l'app vera (servono Flask e le dipendenze: usare .venv/bin/python).

- i modelli (models.py) rispecchiano le tabelle create dalle migrazioni (schema.py);
- le tabelle del modulo stanno in prodotti.db e NON in gestionale.db;
- le pagine del modulo rispondono (permessi, creazione di materie prime, prodotti, ricette, lotti).
Le credenziali del .env vengono svuotate come in test_avvio_ruoli.py.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_avvio_ruoli as base  # noqa: E402  (svuota le credenziali e sa isolare il pacchetto app)


@unittest.skipUnless(base.HA_FLASK, "serve Flask (usare .venv/bin/python)")
class ProdottiAppBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._moduli_altrui = base._togli_moduli_app()

    @classmethod
    def tearDownClass(cls):
        base._togli_moduli_app()
        sys.modules.update(cls._moduli_altrui)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cartella = os.path.join(self.tmp.name, "data")
        os.makedirs(self.cartella)
        from app.config import Config
        self._p = [mock.patch.object(Config, "SQLALCHEMY_DATABASE_URI",
                                     f"sqlite:///{os.path.join(self.cartella, 'gestionale.db')}"),
                   mock.patch.dict(os.environ, {"RUOLO": "sviluppo", "MODULI": "prodotti"})]
        for p in self._p:
            p.start()
        import app as pacchetto
        self.app = pacchetto.create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        from app import db
        from app.models import User
        import json
        with self.app.app_context():
            self.admin_id = User.query.filter_by(role="admin").first().id
            u = User(username="lab", password_hash="x", display_name="Laboratorio", role="operatore", active=True,
                     sections=json.dumps(["prodotti"]))
            c = User(username="cons", password_hash="x", display_name="Consulente", role="consulente", active=True,
                     sections=json.dumps(["prodotti"]))
            db.session.add_all([u, c])
            db.session.commit()
            self.operatore_id, self.consulente_id = u.id, c.id

    def tearDown(self):
        from app import db
        with self.app.app_context():
            db.session.remove()
            db.engines  # noqa: B018
            for e in db.engines.values():
                e.dispose()
        for p in reversed(self._p):
            p.stop()
        self.tmp.cleanup()

    def client(self, uid=None):
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["_user_id"] = str(uid or self.admin_id)
            s["_fresh"] = True
        return c


class TestModelliSchema(ProdottiAppBase):
    def test_modelli_rispecchiano_tabelle(self):
        from app.moduli.prodotti import models
        con = sqlite3.connect(os.path.join(self.cartella, "prodotti.db"))
        for nome in dir(models):
            cls = getattr(models, nome)
            tabella = getattr(cls, "__tablename__", None)
            if not tabella or getattr(cls, "__bind_key__", None) != "prodotti":
                continue
            nel_db = {r[1] for r in con.execute(f"PRAGMA table_info({tabella})")}
            nel_modello = {c.name for c in cls.__table__.columns}
            self.assertTrue(nel_db, f"tabella {tabella} mancante")
            self.assertEqual(nel_modello - nel_db, set(), f"{nome}: colonne del modello assenti nel database")
        con.close()

    def test_tabelle_non_finiscono_in_gestionale_db(self):
        con = sqlite3.connect(os.path.join(self.cartella, "gestionale.db"))
        tabelle = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertFalse(tabelle & {"lotti", "ricette", "prodotti", "materie_prime", "schema_versione"})


if __name__ == "__main__":
    unittest.main()
