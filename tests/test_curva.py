"""
Prove degli scaglioni della curva di accrescimento (app/services/allevamento_curva.py).

    python3 -m unittest discover -s tests -v

I punti sono quelli della curva di alimentazione del PC (foto «curva alimentazione 1/2»).
"""
import importlib.util
import os
import sys
import unittest

_percorso = os.path.join(os.path.dirname(__file__), "..", "app", "services", "allevamento_curva.py")
_spec = importlib.util.spec_from_file_location("allevamento_curva", _percorso)
C = importlib.util.module_from_spec(_spec)
sys.modules["allevamento_curva"] = C
_spec.loader.exec_module(C)

CURVA = [(0, 20.0, 1.0), (7, 30.0, 1.3), (14, 34.0, 1.5), (203, 169.1, 3.1), (210, 173.0, 3.1), (217, 174.0, 3.1)]


class Scaglioni(unittest.TestCase):
    def test_primo_punto_senza_scaglione(self):
        s = C.scaglioni(CURVA)[0]
        self.assertIsNone(s.giorni)
        self.assertIsNone(s.accrescimento_g)
        self.assertEqual(s.mangime_cumulato_kg, 0.0)

    def test_scaglione_14_giorni(self):
        s = C.scaglioni(CURVA)[2]          # da 7 a 14 giorni: 30 → 34 kg, razione 1,3 → 1,5
        self.assertEqual(s.giorni, 7)
        self.assertAlmostEqual(s.accrescimento_g, 4000 / 7)
        self.assertAlmostEqual(s.aumento_razione_g, 200 / 7)
        self.assertAlmostEqual(s.mangime_kg, 1.4 * 7)
        self.assertAlmostEqual(s.indice, 1.4 * 7 / 4)

    def test_cumulati(self):
        s = C.scaglioni(CURVA)[2]
        self.assertAlmostEqual(s.mangime_cumulato_kg, 1.15 * 7 + 1.4 * 7)
        self.assertAlmostEqual(s.indice_cumulato, (1.15 * 7 + 1.4 * 7) / 14)

    def test_razione_ferma_e_ordine(self):
        righe = C.scaglioni(list(reversed(CURVA)))
        self.assertEqual([r.eta_giorni for r in righe], [0, 7, 14, 203, 210, 217])
        self.assertAlmostEqual(righe[-1].aumento_razione_g, 0.0)
        self.assertAlmostEqual(righe[-1].indice, 3.1 * 7 / 1.0)

    def test_razione_mancante(self):
        righe = C.scaglioni([(0, 20.0, 1.0), (7, 30.0, None), (14, 34.0, 1.5)])
        self.assertAlmostEqual(righe[1].accrescimento_g, 10000 / 7)
        self.assertIsNone(righe[1].mangime_kg)
        self.assertIsNone(righe[2].mangime_kg)
        self.assertIsNone(righe[2].mangime_cumulato_kg)   # il buco non si può saltare


class CurvaDalPC(unittest.TestCase):
    # righe come le dà il lettore Paradox: campi a zero come 0 o None
    BOX = [{"NR": 1, "NRSUINI": 39, "NRCURVA": 2}, {"NR": 2, "NRSUINI": 42, "NRCURVA": 2},
           {"NR": 3, "NRSUINI": 0, "NRCURVA": 1}, {"NR": 4, "NRSUINI": 40, "NRCURVA": 1},
           {"NR": 99, "NRSUINI": 33, "NRCURVA": 1}, {"NR": 98, "NRSUINI": 33, "NRCURVA": 1}]   # 98, 99: box non reali
    CURVE = [{"TIPO": 0, "NR": 1, "NOME": "curva VERONESI", "DESCR": "SUINO PESANTE SP"},
             {"TIPO": 0, "NR": 2, "NOME": "RICETTA VERONESI LC", "DESCR": "SUINI PESANTE LC"},
             {"TIPO": 1, "NR": 2, "NOME": "CURVA SVEZZ2MIN", "DESCR": "PER SVEZZAMENTO"}]
    PUNTI = [{"TIPO": None, "NR": None, "HGE2": 0.0, "HGP2": 26.0, "HG2": 1.0, "HGE1": 0.0, "HGP1": 20.0, "HG1": 1.0},
             {"TIPO": 0, "NR": 2, "HGE2": 14.0, "HGP2": 34.0, "HG2": 1.5},
             {"TIPO": 0, "NR": 1, "HGE2": 7.0, "HGP2": 30.0, "HG2": 1.3},
             {"TIPO": 0, "NR": 3, "HGE2": None, "HGP2": None, "HG2": None},       # punto non usato: si ferma
             {"TIPO": 0, "NR": 4, "HGE2": 28.0, "HGP2": 42.8, "HG2": 1.85},
             {"TIPO": 1, "NR": 0, "HGE2": 0.0, "HGP2": 8.0, "HG2": 0.2}]          # svezzamento: ignorato

    def test_curva_piu_usata_dai_box_reali(self):
        c = C.curva_dal_pc(self.BOX, self.CURVE, self.PUNTI, set(range(1, 55)))
        self.assertEqual((c["nr"], c["nome"], c["descr"], c["box"]), (2, "RICETTA VERONESI LC", "SUINI PESANTE LC", 2))
        self.assertEqual(c["punti"], [(0, 26.0, 1.0), (7, 30.0, 1.3), (14, 34.0, 1.5)])

    def test_nessun_box_con_capi(self):
        self.assertIsNone(C.curva_dal_pc([{"NR": 1, "NRSUINI": 0, "NRCURVA": 2}], self.CURVE, self.PUNTI, {1}))

    def test_differenze(self):
        salvati = [(0, 20.0, 1.0), (7, 30.0, 1.3), (217, 174.0, 3.1)]
        pc = [(0, 26.0, 1.0), (7, 30.0, 1.3), (224, 181.0, 3.1)]
        self.assertEqual(C.differenze(salvati, pc),
                         [(0, (20.0, 1.0), (26.0, 1.0)), (217, (174.0, 3.1), None), (224, None, (181.0, 3.1))])
        self.assertEqual(C.differenze(pc, pc), [])


class ScartiCensimenti(unittest.TestCase):
    from datetime import date as D
    PUNTI = [(0, 26.0, 1.0), (7, 30.0, 1.3), (14, 34.0, 1.5), (203, 169.1, 3.1), (210, 173.0, 3.1)]

    def test_peso_e_eta_inversi(self):
        self.assertAlmostEqual(C.peso_da_eta(self.PUNTI, 3.5), 28.0)
        self.assertAlmostEqual(C.eta_da_peso(self.PUNTI, 28.0), 3.5)
        self.assertEqual(C.peso_da_eta(self.PUNTI, 300), 173.0)
        self.assertEqual(C.eta_da_peso(self.PUNTI, 20.0), 0.0)

    def test_arrivo_dal_primo_censimento(self):
        D = self.D
        cens = [(D(2026, 5, 19), {1: (40, 5), 2: (40, 5)}),
                (D(2026, 6, 2), {1: (40, 19), 2: (40, 21), 3: (30, 7)}),       # box 3 arriva ora
                (D(2026, 6, 9), {1: (40, 26), 2: (40, 26), 3: (30, 14)})]
        r = C.scarti_censimenti(cens, [], self.PUNTI)
        for x, atteso in zip(r, [0.0, 2.0 * 40 / 110, 0.0]):     # box 2 avanti di 2 giorni su 110 capi
            self.assertAlmostEqual(x.scarto_giorni, atteso)
        self.assertEqual(len(r[1].gruppi), 2)
        g = r[1].gruppi[0]
        self.assertEqual((g.box, g.capi, g.eta_teorica, g.scarto_giorni), ((1, 2), 80, 19.0, 1.0))
        self.assertAlmostEqual(g.scarto_kg, (C.peso_da_eta(self.PUNTI, 21) - C.peso_da_eta(self.PUNTI, 19)) / 2)

    def test_arrivo_dalle_entrate(self):
        D = self.D
        r = C.scarti_censimenti([(D(2026, 5, 26), {1: (40, 9)})], [(D(2026, 5, 19), 1, 26.0)], self.PUNTI)
        g = r[0].gruppi[0]
        self.assertTrue(g.da_entrata)
        self.assertEqual((g.eta_arrivo, g.eta_teorica, g.scarto_giorni), (0.0, 7.0, 2.0))


if __name__ == "__main__":
    unittest.main()
