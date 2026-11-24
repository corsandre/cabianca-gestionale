"""Test di app/moduli/migrazioni.py: versioni, copia prima della migrazione, guardia, atomicità, trigger."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest

_BASE = os.path.join(os.path.dirname(__file__), "..", "app")


def _carica(nome, percorso):
    spec = importlib.util.spec_from_file_location(nome, percorso)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mig = _carica("migrazioni", os.path.join(_BASE, "moduli", "migrazioni.py"))
bs = _carica("backup_sqlite", os.path.join(_BASE, "services", "backup_sqlite.py"))

M1 = (1, "lotti", [
    "CREATE TABLE lotti (id INTEGER PRIMARY KEY, codice TEXT NOT NULL UNIQUE)",
    "CREATE TRIGGER lotti_no_delete BEFORE DELETE ON lotti "
    "BEGIN SELECT RAISE(ABORT, 'Il libro lotti non si cancella: annullare il lotto'); END",
])
M2 = (2, "note", ["ALTER TABLE lotti ADD COLUMN note TEXT"])


class TestMigrazioni(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = os.path.join(self.tmp.name, "data", "prodotti.db")
        self.bk = os.path.join(self.tmp.name, "backups")

    def tearDown(self):
        self.tmp.cleanup()

    def applica(self, migrazioni):
        return mig.applica(self.db, migrazioni, "prodotti", self.bk, "1.0.0", copia=bs.copia_sqlite)

    def test_db_nuovo_senza_copia(self):
        self.assertEqual(self.applica([M1]), (0, 1, None))
        self.assertEqual(mig.versione_attuale(self.db), 1)
        self.assertFalse(os.path.exists(self.bk))           # niente da salvare su un DB vuoto

    def test_idempotente(self):
        self.applica([M1])
        self.assertEqual(self.applica([M1]), (1, 1, None))

    def test_seconda_migrazione_con_copia(self):
        self.applica([M1])
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO lotti (codice) VALUES ('L241126-ZUC')")
        con.commit()
        con.close()
        prima, dopo, copia = self.applica([M1, M2])
        self.assertEqual((prima, dopo), (1, 2))
        self.assertTrue(os.path.basename(copia).startswith("prodotti_pre_v2_"))
        c = sqlite3.connect(copia)
        self.assertEqual(c.execute("SELECT codice FROM lotti").fetchall(), [("L241126-ZUC",)])
        self.assertNotIn("note", [r[1] for r in c.execute("PRAGMA table_info(lotti)")])   # copia = stato prima
        c.close()

    def test_database_piu_nuovo_del_codice(self):
        self.applica([M1, M2])
        with self.assertRaises(mig.DatabasePiuNuovo):
            self.applica([M1])

    def test_migrazione_fallita_non_lascia_mezzi_cambiamenti(self):
        self.applica([M1])
        rotta = (2, "rotta", ["ALTER TABLE lotti ADD COLUMN note TEXT", "QUESTO NON E SQL"])
        with self.assertRaises(sqlite3.OperationalError):
            self.applica([M1, rotta])
        self.assertEqual(mig.versione_attuale(self.db), 1)
        con = sqlite3.connect(self.db)
        self.assertNotIn("note", [r[1] for r in con.execute("PRAGMA table_info(lotti)")])
        con.close()

    def test_trigger_blocca_cancellazione(self):
        self.applica([M1])
        con = sqlite3.connect(self.db)
        con.execute("INSERT INTO lotti (codice) VALUES ('L1')")
        con.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            con.execute("DELETE FROM lotti")
        con.close()

    def test_numeri_non_validi(self):
        with self.assertRaises(ValueError):
            self.applica([M2, M1])
        with self.assertRaises(ValueError):
            self.applica([(0, "zero", [])])

    def test_migrazione_come_funzione(self):
        def m(con):
            con.execute("CREATE TABLE x (a)")
        self.applica([(1, "funzione", m)])
        self.assertEqual(mig.versione_attuale(self.db), 1)


if __name__ == "__main__":
    unittest.main()
