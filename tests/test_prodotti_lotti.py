"""Test di app/moduli/prodotti/services/lotti.py: codice lotto, scadenza, scala della ricetta."""
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from _prodotti_services import servizi  # noqa: E402

lot = servizi("lotti")


class TestLotti(unittest.TestCase):
    def test_codice_lotto(self):
        d = date(2026, 11, 24)
        self.assertEqual(lot.codice_lotto(d, "zuc"), "L241126-ZUC")
        self.assertEqual(lot.codice_lotto(d, "ZUC", ["L241126-ZUC"]), "L241126-ZUC-2")
        self.assertEqual(lot.codice_lotto(d, "ZUC", ["l241126-zuc", "L241126-ZUC-2"]), "L241126-ZUC-3")
        self.assertEqual(lot.codice_lotto(date(2027, 1, 5), "M-A R"), "L050127-MAR")

    def test_sigle(self):
        self.assertEqual(lot.proponi_sigla("Confettura di fichi"), "CFI")
        self.assertEqual(lot.proponi_sigla("Passata"), "PAS")
        self.assertEqual(lot.proponi_sigla("Tortelli di zucca"), "TZU")
        self.assertEqual(lot.proponi_sigla(""), "")
        self.assertEqual(lot.pulisci_sigla("abcdefghilm"), "ABCDEFGH")

    def test_scadenza(self):
        self.assertEqual(lot.data_scadenza(date(2026, 11, 24), 92), date(2027, 2, 24))
        self.assertIsNone(lot.data_scadenza(date(2026, 11, 24), None))

    def test_scala_e_arrotondamento(self):
        self.assertEqual(lot.fattore_scala(40, 100), 2.5)
        self.assertEqual(lot.fattore_scala(None, 100), 1.0)
        self.assertEqual(lot.fattore_scala(0, 100), 1.0)
        # lotto con più contenitori: kg totali sulla resa in kg; senza kg, i pezzi sulla resa in pezzi
        self.assertAlmostEqual(lot.fattore_ricetta(4.8, 40, 9.6, 52), 2.0)
        self.assertEqual(lot.fattore_ricetta(None, 40, 9.6, 80), 2.0)
        self.assertEqual(lot.fattore_ricetta(4.8, 40, 0, 80), 2.0)       # salumi: peso variabile
        self.assertEqual(lot.fattore_ricetta(None, None, 9.6, 80), 1.0)
        self.assertEqual(lot.arrotonda_quantita(1234.56), 1235)
        self.assertEqual(lot.arrotonda_quantita(12.345), 12.3)

    def test_da_iso(self):
        self.assertEqual(lot.da_iso("2026-11-24T10:00:00"), date(2026, 11, 24))
        self.assertIsNone(lot.da_iso("boh"))


if __name__ == "__main__":
    unittest.main()
