"""
Prove del riepilogo delle fatture del siero (app/services/siero_fatture.py, calcola_riepilogo()):
numeri del ciclo, valore delle discrepanze, prezzo dell'ultima consegna fatturata.

    python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import sys
import types
import unittest
from datetime import date
from types import SimpleNamespace as N

# siero_fatture importa il database e i modelli: per calcola_riepilogo() bastano dei sostituti
_salvati = {k: sys.modules.get(k) for k in ("app", "app.models", "app.services", "app.services.siero_fatture_pdf")}
_app = types.ModuleType("app")
_app.db = None
_modelli = types.ModuleType("app.models")
for _n in ("Ciclo", "ConsegnaSiero", "SdiInvoice", "SieroFatturaRiga", "SoccidaParametri"):
    setattr(_modelli, _n, object)
_servizi = types.ModuleType("app.services")
_pdf = types.ModuleType("app.services.siero_fatture_pdf")
_servizi.siero_fatture_pdf = _pdf
sys.modules.update({"app": _app, "app.models": _modelli, "app.services": _servizi, "app.services.siero_fatture_pdf": _pdf})
_spec = importlib.util.spec_from_file_location("siero_fatture", os.path.join(os.path.dirname(__file__), "..", "app", "services", "siero_fatture.py"))
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)
for _k, _v in _salvati.items():          # rimette a posto per le altre prove
    if _v is None:
        sys.modules.pop(_k, None)
    else:
        sys.modules[_k] = _v


def consegna(id, giorno, qli, lotto=""):
    return N(id=id, data=date(2026, 10, giorno), quantita_qli=qli, lotto=lotto)


def riga(id, giorno, ddt, t, importo, consegna_id=None, come=None, fattura=1, tipo="carico"):
    return N(id=id, sdi_invoice_id=fattura, tipo=tipo, ddt=ddt, data=date(2026, 10, giorno), tonnellate=t,
             importo=importo, importo_netto=importo, consegna_id=consegna_id, come=come)


FATTURA = N(id=1, invoice_number="2026-FTC-0000703", taxable_amount=900.0, total_amount=990.0)


class Riepilogo(unittest.TestCase):
    def setUp(self):
        # 4 consegne: 1 coincide, 2 quantità diversa (28 t in bolla, 29 in fattura), 3 non fatturata, 4 dopo la fattura
        self.consegne = [consegna(1, 2, 290, "8501"), consegna(2, 10, 280, "8502"), consegna(3, 20, 300), consegna(4, 31, 250)]
        self.righe = [riga(11, 2, "8501", 29.0, 290.0, 1, "bolla"),            # 10 €/t
                      riga(12, 10, "8502", 29.0, 348.0, 2, "bolla"),           # 12 €/t, l'ultima abbinata
                      riga(13, 15, "8599", 30.0, 352.0)]                        # senza consegna
        self.per_consegna = {1: {"riga": self.righe[0], "stato": "ok", "testo": "coincide"},
                             2: {"riga": self.righe[1], "stato": "quantita", "testo": "28 t in bolla, 29 t in fattura"}}
        self.r = F.calcola_riepilogo([FATTURA], {1: self.righe}, self.consegne, self.per_consegna, [self.righe[2]], date(2026, 10, 25))

    def test_prezzo_dell_ultima_consegna_fatturata(self):
        self.assertAlmostEqual(self.r["numeri"]["prezzo_ultima"], 12.0)
        self.assertEqual(self.r["numeri"]["prezzo_ultima_data"], date(2026, 10, 10))

    def test_valore_delle_discrepanze(self):
        d = {x["tipo"]: x for x in self.r["discrepanze"]}
        self.assertEqual(set(d), {"quantita", "senza_consegna", "non_fatturata"})
        self.assertAlmostEqual(d["quantita"]["valore"], 1 * 12.0)           # 1 t in più al prezzo del carico
        self.assertAlmostEqual(d["senza_consegna"]["valore"], 352.0)        # l'importo del carico
        self.assertAlmostEqual(d["non_fatturata"]["valore"], 30 * 12.0)     # 30 t al prezzo dell'ultima
        self.assertEqual([x["data"].day for x in self.r["discrepanze"]], [10, 15, 20])   # in ordine di data

    def test_numeri_del_ciclo(self):
        n = self.r["numeri"]
        self.assertAlmostEqual(n["t_consegne"], 29 + 28 + 30)              # la consegna del 31 è dopo la fattura
        self.assertAlmostEqual(n["t_fatture"], 88)
        self.assertAlmostEqual(n["eur_consegne"], 29 * 10 + 28 * 12 + 30 * 12)
        self.assertAlmostEqual(n["eur_fatture"], 290 + 348 + 352)
        self.assertEqual((n["in_attesa"], n["t_attesa"]), (1, 25))
        self.assertAlmostEqual(n["eur_attesa"], 25 * 12.0)
        self.assertEqual((n["per_bolla"], n["per_data"], n["a_mano"]), (2, 0, 0))

    def test_esito_della_fattura(self):
        x = self.r["fatture"][0]
        self.assertEqual(len(x["carichi"]), 3)
        self.assertEqual(x["differenze"], 2)          # quantità diversa + carico senza consegna
        self.assertAlmostEqual(x["tonnellate"], 88)

    def test_senza_abbinamenti_niente_prezzo(self):
        r = F.calcola_riepilogo([FATTURA], {1: [self.righe[2]]}, [consegna(3, 20, 300)], {}, [self.righe[2]], date(2026, 10, 25))
        self.assertIsNone(r["numeri"]["prezzo_ultima"])
        self.assertIsNone(next(x for x in r["discrepanze"] if x["tipo"] == "non_fatturata")["valore"])


if __name__ == "__main__":
    unittest.main()
