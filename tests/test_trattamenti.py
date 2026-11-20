"""
Prove delle quantità dei trattamenti (app/services/allevamento_trattamenti.py, quantita()).

    python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import sys
import types
import unittest

_base = os.path.join(os.path.dirname(__file__), "..", "app", "services")
# il modulo importa solo CAPANNONI e live_count dal conteggio: basta un sostituto
_finto = types.ModuleType("app.services.allevamento_conteggio")
_finto.CAPANNONI, _finto.live_count = [1, 2, 3, 4, 5, 6, 7], lambda ciclo: {}
sys.modules.setdefault("app", types.ModuleType("app"))
sys.modules.setdefault("app.services", types.ModuleType("app.services"))
sys.modules["app.services.allevamento_conteggio"] = _finto
_spec = importlib.util.spec_from_file_location("allevamento_trattamenti", os.path.join(_base, "allevamento_trattamenti.py"))
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


class Quantita(unittest.TestCase):
    def test_dosi_piccole_con_tre_decimali(self):
        self.assertEqual(T.quantita(0.004 * 8, "g"), "0,032 g")
        self.assertEqual(T.quantita(0.0125 * 30, "ml"), "0,375 ml")

    def test_sotto_dieci_due_decimali(self):
        self.assertEqual(T.quantita(2.45, "ml"), "2,45 ml")

    def test_sopra_dieci_un_decimale(self):
        self.assertEqual(T.quantita(62.04, "g"), "62,0 g")

    def test_sopra_mille_in_kg_o_litri(self):
        self.assertEqual(T.quantita(11070, "g"), "11,07 kg")
        self.assertEqual(T.quantita(1250, "ml"), "1,25 l")
        self.assertEqual(T.quantita(1234567, "g"), "1.234,57 kg")

    def test_niente(self):
        self.assertEqual(T.quantita(None, "g"), "–")


class DoseACapo(unittest.TestCase):
    def test_per_kg_moltiplica_per_il_peso(self):
        self.assertAlmostEqual(T.dose_a_capo(0.1, 30, False), 3.0)
        self.assertIsNone(T.dose_a_capo(0.1, None, False))      # per kg senza peso: niente dose

    def test_a_capo_non_serve_il_peso(self):
        self.assertEqual(T.dose_a_capo(2, None, True), 2)          # vaccino 2 ml/capo
        self.assertEqual(T.dose_a_capo(2, 150, True), 2)

    def test_senza_dose(self):
        self.assertIsNone(T.dose_a_capo(None, 30, True))
        self.assertEqual(T.base_dose(True) + T.base_dose(False), "capokg")


class Marcatore(unittest.TestCase):
    def test_accordo_del_colore(self):
        self.assertEqual(T.testo_marcatore("rosso", "riga"), "riga rossa")
        self.assertEqual(T.testo_marcatore("nero", "s"), "S nera")
        self.assertEqual(T.testo_marcatore("blu", None), "pallino blu")
        self.assertEqual(T.testo_marcatore(None, "riga"), "")


if __name__ == "__main__":
    unittest.main()
