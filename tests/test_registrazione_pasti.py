"""
Numero del pasto dalle letture dell'impianto (app/services/impianto/registrazione.py: numero_pasto).

    python3 -m unittest discover -s tests -v

Il modulo importa `db` da `app`: per provarlo senza Flask si mette al suo posto un modulo vuoto.
"""
import importlib.util
import os
import sys
import types
import unittest
from datetime import time

_finto = types.ModuleType("app")
_finto.db = None
sys.modules.setdefault("app", _finto)
_percorso = os.path.join(os.path.dirname(__file__), "..", "app", "services", "impianto", "registrazione.py")
_spec = importlib.util.spec_from_file_location("registrazione_prova", _percorso)
R = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(R)

ORARI = [time(7, 55), time(13, 10), time(17, 30)]


class NumeroPasto(unittest.TestCase):
    def test_orari_normali(self):
        self.assertEqual(R.numero_pasto(time(7, 55), ORARI), 1)
        self.assertEqual(R.numero_pasto(time(13, 10), ORARI), 2)
        self.assertEqual(R.numero_pasto(time(17, 30), ORARI), 3)

    def test_orario_cambiato_mentre_parte(self):
        # 17/11/2026: letto 13:05 con 13:10 in memoria → pasto 2, non 1
        self.assertEqual(R.numero_pasto(time(13, 5), ORARI), 2)

    def test_pasto_rinviato(self):
        self.assertEqual(R.numero_pasto(time(14, 39), [time(7, 55), time(12, 50), time(17, 30)]), 2)
        self.assertEqual(R.numero_pasto(time(16, 20), [time(7, 55), time(12, 50), time(17, 30)]), 2)

    def test_pasto_diviso_in_due_orari(self):
        # 27/10: 11:55 linea 1, 13:00 linee 2-3 → stesso pasto
        orari = [time(7, 55), time(11, 55), time(13, 0), time(17, 30)]
        self.assertEqual(R.numero_pasto(time(13, 0), orari), 2)
        self.assertEqual(R.numero_pasto(time(17, 30), orari), 3)

    def test_senza_orari(self):
        self.assertIsNone(R.numero_pasto(time(13, 5), []))


if __name__ == "__main__":
    unittest.main()
