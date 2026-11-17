"""
Prove del conteggio dei capi per box (app/services/allevamento_conteggio.py, applica_eventi).

    python3 -m unittest discover -s tests -v

Casi presi da quelli successi in produzione.
"""
import importlib.util
import os
import sys
import unittest
from types import SimpleNamespace as N

_percorso = os.path.join(os.path.dirname(__file__), "..", "app", "services", "allevamento_conteggio.py")
_spec = importlib.util.spec_from_file_location("allevamento_conteggio", _percorso)
C = importlib.util.module_from_spec(_spec)
sys.modules["allevamento_conteggio"] = C
_spec.loader.exec_module(C)


def morto(quantita, box=None, cap=None):
    return N(box_numero=box, capannone_numero=cap, quantita=quantita)


def sposta(tipo, quantita=0, da=None, a=None, box=()):
    return N(tipo=tipo, quantita=quantita, box_origine=da, box_destinazione=a,
             box_svuotati=[N(box_numero=b, capi=c) for b, c in box])


class Struttura(unittest.TestCase):
    def test_54_box_in_7_capannoni(self):
        self.assertEqual(sorted(C.CAP_PER_BOX), list(range(1, 55)))
        self.assertEqual(sorted(b for bs in C.BOX_PER_CAP.values() for b in bs), list(range(1, 55)))
        for cap, boxes in C.BOX_PER_CAP.items():
            self.assertTrue(all(C.CAP_PER_BOX[b] == cap for b in boxes))
        self.assertEqual(sum(C.POSTI_PER_CAP.values()), sum(C.POSTI_PER_BOX_STANDARD.values()))


class ApplicaEventi(unittest.TestCase):
    def test_senza_eventi_i_capi_del_censimento(self):
        r = C.applica_eventi({1: 30, 54: 12}, [], [])
        self.assertEqual(len(r), 54)
        self.assertEqual((r[1], r[54], r[2]), (30, 12, 0))

    def test_morto_nel_box(self):
        self.assertEqual(C.applica_eventi({5: 30}, [morto(2, box=5)], [])[5], 28)

    def test_morti_del_capannone_divisi_tra_i_box(self):
        # capannone 2 = box 10–15 (6 box): 8 morti → 2 ai primi due box, 1 agli altri
        r = C.applica_eventi({b: 20 for b in range(10, 16)}, [morto(8, cap=2)], [])
        self.assertEqual([r[b] for b in range(10, 16)], [18, 18, 19, 19, 19, 19])

    def test_spostamento_interno(self):
        r = C.applica_eventi({1: 30, 2: 10}, [], [sposta("interno", 5, da=1, a=2)])
        self.assertEqual((r[1], r[2]), (25, 15))

    def test_entrata_in_un_box_e_in_piu_box(self):
        r = C.applica_eventi({}, [], [sposta("entrata", 40, a=3), sposta("entrata", 99, box=[(22, 38), (23, 37)])])
        self.assertEqual((r[3], r[22], r[23]), (40, 38, 37))   # su più box contano le righe, non la quantità

    def test_uscita_da_un_box_e_da_piu_box(self):
        r = C.applica_eventi({40: 38, 41: 38, 42: 38}, [],
                             [sposta("uscita", 10, da=40), sposta("uscita", 99, box=[(41, 38), (42, 20)])])
        self.assertEqual((r[40], r[41], r[42]), (28, 0, 18))

    def test_ordine_indifferente_e_zero_solo_alla_fine(self):
        # 12/10, box 16: 2 capi spostati via e poi ne arrivano 3, con 1 morto in mezzo → 2, non 3
        cens = {16: 2}
        eventi_m = [morto(1, box=16)]
        eventi_s = [sposta("interno", 2, da=16, a=17), sposta("interno", 3, da=18, a=16)]
        self.assertEqual(C.applica_eventi(cens, eventi_m, eventi_s)[16], 2)

    def test_mai_negativi(self):
        r = C.applica_eventi({7: 1}, [morto(3, box=7)], [sposta("uscita", 5, da=8)])
        self.assertEqual((r[7], r[8]), (0, 0))


if __name__ == "__main__":
    unittest.main()
