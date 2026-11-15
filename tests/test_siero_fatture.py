"""
Prove della lettura delle fatture del siero (app/services/siero_fatture_pdf.py).
Senza Flask e senza database: python3 -m unittest discover -s tests -v

Il testo è un estratto vero di `pdftotext -layout` sulla fattura Nosari di maggio 2026.
"""
import importlib.util
import os
import unittest

_percorso = os.path.join(os.path.dirname(__file__), "..", "app", "services", "siero_fatture_pdf.py")
_spec = importlib.util.spec_from_file_location("siero_fatture_pdf", _percorso)
P = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(P)

MAGGIO = """
     Cod. articolo                                      Descrizione                                      Quantità           Prezzo unitario   UM          Sconto o magg.    %IVA      Prezzo totale
                            DDT 8509 del 01-05-2026
S.ZOOTEC. PAGLIOLI          S.ZOOTEC. PAGLIOLI                                                                    19,00               9,25        TN                          10,00          175,75
(INT)
                            DDT 8510 del 04-05-2026
S.ZOOTEC. PAGLIOLI          S.ZOOTEC. PAGLIOLI                                                                    10,00               9,25        TN                          10,00           92,50
(INT)
(INT)                       INDICIZZAZIONE GASOLIO VENDITE MAGGIO 2026                                              1,00             20,88        NR                          10,00           20,88
                            2.006,99 . PREZZO . 0,72 TN 29
                                                                                             RIEPILOGHI IVA
I (esigibilità immediata)                                                           10,00                                                                            289,13                   28,91
                                                                                                                                                                                             318,04
MP12 RIBA                                                      IBAN IT61I0503456770000000001072                                                                        30-06-2026            318,04
"""


class LetturaFattura(unittest.TestCase):
    def test_carichi_ed_extra(self):
        carichi, extra = P.righe_da_testo(MAGGIO)
        self.assertEqual([(c["ddt"], c["data"], c["tonnellate"], c["importo"]) for c in carichi],
                         [("8509", "2026-05-01", 19.0, 175.75), ("8510", "2026-05-04", 10.0, 92.5)])
        self.assertEqual(len(extra), 1)
        self.assertIn("GASOLIO", extra[0]["descrizione"])
        self.assertAlmostEqual(extra[0]["importo"], 20.88)

    def test_importi_con_gasolio_e_iva_danno_il_totale(self):
        carichi, extra = P.righe_da_testo(MAGGIO)
        importi = P.importi_completi(carichi, extra, imponibile=289.13, totale=318.04)
        self.assertAlmostEqual(sum(importi), 318.04, delta=0.02)
        self.assertAlmostEqual(importi[0] / importi[1], 19 / 10, places=2)   # stesso prezzo: in proporzione alle tonnellate

    def test_testo_senza_carichi(self):
        self.assertEqual(P.righe_da_testo("Fattura di altro tipo\nTotale 100,00"), ([], []))
        self.assertEqual(P.importi_completi([], [], 0, 0), [])


if __name__ == "__main__":
    unittest.main()
