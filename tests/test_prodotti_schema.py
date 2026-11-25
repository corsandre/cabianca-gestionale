"""Test dello schema di data/prodotti.db (app/moduli/prodotti/schema.py): protezioni del registro di legge."""
import importlib.util
import os
import sqlite3
import tempfile
import unittest

_BASE = os.path.join(os.path.dirname(__file__), "..", "app")


def _carica(nome, percorso):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(_BASE, *percorso))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mig = _carica("migrazioni", ("moduli", "migrazioni.py"))
bs = _carica("backup_sqlite", ("services", "backup_sqlite.py"))
schema = _carica("schema_prodotti", ("moduli", "prodotti", "schema.py"))


class TestSchemaProdotti(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "prodotti.db")
        mig.applica(db, schema.MIGRAZIONI, "prodotti", os.path.join(self.tmp.name, "bk"), copia=bs.copia_sqlite)
        self.c = sqlite3.connect(db)
        c = self.c
        c.execute("INSERT INTO prodotti (nome, sigla) VALUES ('Tortelli di zucca', 'ZUC')")
        c.execute("INSERT INTO materie_prime (nome, nome_etichetta) VALUES ('Zucca', 'zucca')")
        c.execute("INSERT INTO ricette (prodotto_id, versione) VALUES (1, 1)")
        c.execute("INSERT INTO ricette_righe (ricetta_id, materia_prima_id, quantita) VALUES (1, 1, 500)")
        c.execute("INSERT INTO ricette (prodotto_id, versione) VALUES (1, 2)")          # non usata
        c.execute("INSERT INTO lotti (codice, prodotto_id, ricetta_id, data_produzione) "
                  "VALUES ('L241126-ZUC', 1, 1, '2026-11-24')")
        c.execute("INSERT INTO lotti_ingredienti (lotto_id, nome, lotto_fornitore) VALUES (1, 'zucca', 'A1')")
        c.execute("INSERT INTO stampe_etichette (lotto_id, stile, n_etichette, pdf_path, sha256, dati) "
                  "VALUES (1, 'base-2026', 8, '2026/x.pdf', 'abc', '{}')")
        c.commit()

    def tearDown(self):
        self.c.close()
        self.tmp.cleanup()

    def bloccato(self, sql):
        with self.assertRaises(sqlite3.DatabaseError, msg=sql):
            self.c.execute(sql)

    def test_dati_iniziali(self):
        self.assertEqual(self.c.execute("SELECT count(*) FROM formati_etichetta").fetchone()[0], 4)
        self.assertIn("Fattoria Ca' Bianca", self.c.execute("SELECT prodotto_da FROM prodotti").fetchone()[0])
        imp = dict(self.c.execute("SELECT chiave, valore FROM impostazioni"))
        self.assertEqual(imp["stile_etichette"], "base-2026")

    def test_lotti_e_stampe_non_si_cancellano(self):
        self.bloccato("DELETE FROM lotti")
        self.bloccato("DELETE FROM stampe_etichette")
        self.bloccato("UPDATE stampe_etichette SET n_etichette = 1")

    def test_codice_lotto_unico_e_stato_valido(self):
        self.bloccato("INSERT INTO lotti (codice, prodotto_id, data_produzione) VALUES ('L241126-ZUC', 1, '2026-11-24')")
        self.bloccato("UPDATE lotti SET stato = 'boh'")

    def test_modifiche_finiscono_nello_storico(self):
        self.c.execute("UPDATE lotti SET pezzi_prodotti = 80, modificato_da = 'andrea'")
        self.c.execute("UPDATE lotti_ingredienti SET lotto_fornitore = 'A2', modificato_da = 'andrea'")
        self.c.execute("DELETE FROM lotti_ingredienti")
        righe = self.c.execute("SELECT tabella, azione, chi, json_extract(prima, '$.lotto_fornitore') "
                               "FROM storico ORDER BY id").fetchall()
        self.assertEqual(righe, [("lotti", "modifica", "andrea", None),
                                 ("lotti_ingredienti", "modifica", "andrea", "A1"),
                                 ("lotti_ingredienti", "cancellazione", "andrea", "A2")])
        self.bloccato("DELETE FROM storico")
        self.bloccato("UPDATE storico SET chi = 'altro'")

    def test_ricetta_usata_bloccata_ma_disattivabile(self):
        self.bloccato("UPDATE ricette_righe SET quantita = 1 WHERE ricetta_id = 1")
        self.bloccato("DELETE FROM ricette_righe WHERE ricetta_id = 1")
        self.bloccato("INSERT INTO ricette_righe (ricetta_id, materia_prima_id, quantita) VALUES (1, 1, 5)")
        self.bloccato("UPDATE ricette SET procedimento = 'x' WHERE id = 1")
        self.bloccato("DELETE FROM ricette WHERE id = 1")
        self.c.execute("UPDATE ricette SET attiva = 0, nome = 'vecchia' WHERE id = 1")   # permesso

    def test_ricetta_non_usata_modificabile(self):
        self.c.execute("INSERT INTO ricette_righe (ricetta_id, materia_prima_id, quantita) VALUES (2, 1, 400)")
        self.c.execute("UPDATE ricette_righe SET quantita = 450 WHERE ricetta_id = 2")
        self.c.execute("UPDATE ricette SET procedimento = 'cuocere' WHERE id = 2")
        self.c.execute("DELETE FROM ricette_righe WHERE ricetta_id = 2")
        self.c.execute("DELETE FROM ricette WHERE id = 2")


if __name__ == "__main__":
    unittest.main()
