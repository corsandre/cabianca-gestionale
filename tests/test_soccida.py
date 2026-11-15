"""
Prove del motore di calcolo della soccida (app/services/soccida.py).

Si lanciano senza Flask e senza database:

    python3 -m unittest discover -s tests -v

Il modulo viene caricato dal file, senza importare il pacchetto `app`, proprio
perché non deve dipendere dal resto dell'applicazione.

I numeri attesi vengono dall'Excel «Calcoli compenso Soccida v2» (cicli 1–6).
"""
import importlib.util
import os
import sys
import unittest
from datetime import date

_percorso = os.path.join(os.path.dirname(__file__), "..", "app", "services", "soccida.py")
_spec = importlib.util.spec_from_file_location("soccida", _percorso)
S = importlib.util.module_from_spec(_spec)
sys.modules["soccida"] = S
_spec.loader.exec_module(S)

# Fino al ciclo 5 il premio su tabella era del 10% (prezzo 1,595) più un 10% «Esselunga».
VECCHIO = S.Contratto(premio_tabella_perc=10.0)
NUOVO = S.Contratto()

# Dall'Excel: mangime (E17), carne (I41), siero (E13), giorni (B12), premi (B22), extra,
# e i risultati: indice (B19), resa (J8), minimo (E11).
CICLI = {
    1: dict(mangime=864340, carne=233258.17, siero=0, giorni=212, premi=4.66, extra=10, c=VECCHIO,
            indice=3.7055079357, resa=50755.50, minimo=56920.55),
    2: dict(mangime=727500, carne=208638.8, siero=0, giorni=264, premi=9.55, extra=10, c=VECCHIO,
            indice=3.4868873862, resa=57217.79, minimo=70882.19),
    3: dict(mangime=780100, carne=235642.62, siero=14153.25, giorni=228, premi=6.48, extra=10, c=VECCHIO,
            indice=3.3105216705, resa=72548.73, minimo=61216.44),
    4: dict(mangime=914630, carne=237220.179, siero=799.94, giorni=253, premi=9.18, extra=10, c=VECCHIO,
            indice=3.8556163470, resa=48050.54, minimo=67928.77),
    5: dict(mangime=704560, carne=232190.605, siero=20636.38, giorni=219, premi=5.63, extra=10, c=VECCHIO,
            indice=3.0344035668, resa=87452.11, minimo=58800.00),
    6: dict(mangime=699280, carne=203058.818, siero=17477.09, giorni=222, premi=8, extra=0, c=NUOVO,
            indice=3.4437312641, resa=56924.30, minimo=59605.48),
}


def _conto(n):
    d = CICLI[n]
    return S.conto(mangime_kg=d["mangime"], carne_kg=d["carne"], siero_eur=d["siero"], giorni=d["giorni"],
                   contratto=d["c"], premi_perc=d["premi"], premio_extra_perc=d["extra"], anticipi_eur=54000)


class ContoComeExcel(unittest.TestCase):
    def test_indice_e_minimo_di_tutti_i_cicli(self):
        for n, d in CICLI.items():
            c = _conto(n)
            self.assertAlmostEqual(c.indice, d["indice"], places=9, msg=f"ciclo {n}")
            self.assertAlmostEqual(c.minimo_eur, d["minimo"], places=2, msg=f"ciclo {n}")

    def test_resa_del_ciclo_6_al_centesimo(self):
        # il ciclo 6 usa la tabella attuale (1,45 € + 20%): deve tornare al centesimo
        c = _conto(6)
        self.assertAlmostEqual(c.valore_kg, 0.25956854245543781, places=12)
        self.assertAlmostEqual(c.resa_eur, 56924.295934662739, places=2)
        self.assertAlmostEqual(c.margine_eur, -20158.273517392059, places=2)   # «Guadagno netto» dell'Excel

    def test_resa_dei_cicli_con_la_vecchia_tabella(self):
        # fino al ciclo 5 l'Excel usava i centesimi della tabella arrotondati a 4 decimali
        # (0,3557 invece di 22,3 × 1,595 / 100 = 0,355685): la differenza resta entro lo 0,05%
        for n in (1, 2, 3, 4, 5):
            c = _conto(n)
            self.assertLess(abs(c.resa_eur - CICLI[n]["resa"]) / CICLI[n]["resa"], 5e-4, msg=f"ciclo {n}")

    def test_esito_dei_cicli(self):
        # ciclo 5 a premio (+8.015,73 € nell'Excel), ciclo 6 al minimo
        c5, c6 = _conto(5), _conto(6)
        self.assertTrue(c5.a_premio)
        self.assertLess(abs(c5.margine_eur - 8015.73), 20)
        self.assertAlmostEqual(c5.pagato_eur, c5.resa_eur)
        self.assertFalse(c6.a_premio)
        self.assertAlmostEqual(c6.pagato_eur, 59605.479452 + 17477.09, places=2)   # minimo + siero
        self.assertAlmostEqual(c6.netto_eur, c6.minimo_eur)                        # al netto resta il minimo
        self.assertAlmostEqual(c6.saldo_eur, 59605.479452 + 17477.09 - 54000, places=2)


class Tabella(unittest.TestCase):
    def test_righe_e_interpolazione(self):
        self.assertAlmostEqual(S.percentuale_tabella(3.0), 20.9)
        self.assertAlmostEqual(S.percentuale_tabella(3.05), 20.2)
        self.assertAlmostEqual(S.percentuale_tabella(3.45), (15.46 + 14.22) / 2)

    def test_sotto_la_prima_riga_si_prolunga(self):
        # stesso passo delle prime due righe: +1,4 punti ogni 0,1 di indice
        self.assertAlmostEqual(S.percentuale_tabella(2.8), 23.7)
        self.assertAlmostEqual(S.percentuale_tabella(2.5), 27.9)

    def test_sopra_l_ultima_riga_si_prolunga(self):
        # stesso passo delle ultime due righe: −0,83 punti ogni 0,1 di indice, mai sotto zero
        self.assertAlmostEqual(S.percentuale_tabella(4.0), 9.46)
        self.assertAlmostEqual(S.percentuale_tabella(4.1), 8.63)
        self.assertAlmostEqual(S.percentuale_tabella(4.7), 9.46 - 7 * 0.83)
        self.assertEqual(S.percentuale_tabella(6.0), 0.0)

    def test_nessun_salto_ai_bordi_della_tabella(self):
        for bordo in (2.9, 4.0):
            self.assertAlmostEqual(S.percentuale_tabella(bordo - 1e-9), S.percentuale_tabella(bordo + 1e-9), places=6)

    def test_righe_prolungate_per_le_impostazioni(self):
        migliori, peggiori = S.righe_prolungate()
        self.assertEqual([i for i, _ in migliori], [2.6, 2.7, 2.8])
        self.assertAlmostEqual(migliori[0][1], 26.5)            # 2,6 → 22,3 + 3 × 1,4
        self.assertAlmostEqual(S.percentuale_tabella(2.62), 26.22)
        self.assertEqual([i for i, _ in peggiori], [4.1, 4.2])
        self.assertAlmostEqual(peggiori[1][1], 7.8)

    def test_prezzo_di_tabella(self):
        self.assertAlmostEqual(NUOVO.prezzo_tabella, 1.74)
        self.assertAlmostEqual(S.valore_kg(2.9, NUOVO), 0.38802)


class Carne(unittest.TestCase):
    def test_scarti_al_50_con_calo_fisso(self):
        # ciclo 6, carico dell'11/12/2025: 44 scarti. Nell'Excel 32,972 kg a capo già dimezzati
        p = S.carne_partita([S.Carico(capi=44, peso_vivo_kg=78.86, scarto=True)], NUOVO)
        self.assertAlmostEqual(p.kg_scarti, 44 * 32.972, delta=0.5)
        self.assertEqual((p.capi_scarti, p.capi_grassi), (44, 0))

    def test_grassi_riscontrati_e_da_riscontrare(self):
        # ciclo 6, 20/04/2026: 127 capi a 173,071 kg, riscontrati 127 a 143,159 kg (resa 82,72%)
        riscontrato = S.Carico(capi=127, peso_vivo_kg=173.071, capi_riscontrati=127, peso_morto_kg=143.159)
        in_attesa = S.Carico(capi=130, peso_vivo_kg=175.0)
        self.assertAlmostEqual(S.resa_media([riscontrato, in_attesa]) * 100, 82.7169, places=3)
        p = S.carne_partita([riscontrato, in_attesa], NUOVO)
        self.assertAlmostEqual(p.kg_riscontrati, 18181.193, places=3)
        self.assertAlmostEqual(p.kg_da_riscontrare, 130 * 175.0 * p.resa_usata, places=6)
        self.assertAlmostEqual(p.resa_usata * 100, 82.7169, places=3)

    def test_senza_riscontri_vale_la_resa_di_partenza(self):
        p = S.carne_partita([S.Carico(capi=100, peso_vivo_kg=170.0)], NUOVO)
        self.assertAlmostEqual(p.kg_da_riscontrare, 100 * 170 * 0.82)


# La situazione del ciclo 05/2026 al 15/11/2026, come nella prima stima fatta a mano.
CURVA = ((0, 20.0), (175, 151.6), (182, 156.2), (189, 160.6), (196, 164.9), (203, 169.1), (210, 173.0), (217, 174.0))
OGGI = S.Situazione(
    oggi=date(2026, 11, 15), ultimo_giorno_pagato_prec=date(2026, 5, 11),
    mangime_bolle_kg=698320, giacenza_iniziale_kg=3000, giacenza_oggi_kg=31590, consumo_mangime_giorno_kg=4450,
    carichi=(S.Carico(capi=24, peso_vivo_kg=69.6, scarto=True),),
    capi_presenti=1768, eta_media_giorni=180.2, curva=CURVA,
    siero_fatturato_eur=15285.0, siero_da_fatturare_t=188.54, siero_prezzo_t=11.32, siero_giorno_t=13.5,
    anticipi_eur=45000,
)
STANDARD = S.Scenario(primo_carico=date(2026, 12, 3), ultimo_carico=date(2026, 12, 23))


class StimaDelCicloInCorso(unittest.TestCase):
    def test_conto_previsto(self):
        st = S.stima(OGGI, STANDARD, NUOVO)
        self.assertAlmostEqual(st.giorni_equivalenti, 28)          # (18 + 38) / 2
        self.assertAlmostEqual(st.capi_macello, 1740)
        self.assertAlmostEqual(st.peso_uscita_kg, 172.0, delta=0.05)
        self.assertAlmostEqual(st.mangime_finora_kg, 669730)
        self.assertAlmostEqual(st.mangime_residuo_kg, 124600)
        self.assertEqual(st.conto.giorni, 226)
        self.assertAlmostEqual(st.conto.indice, 3.189, delta=0.002)
        self.assertAlmostEqual(st.conto.margine_eur, 3085, delta=150)
        self.assertEqual((st.carichi_previsti, st.giorni_minimi_carico, st.finestra_giorni), (14, 7, 20))

    def test_un_giorno_in_piu_peggiora(self):
        base = S.stima(OGGI, STANDARD, NUOVO).conto.margine_eur
        dopo = S.stima(OGGI, STANDARD, NUOVO, S.Variazione(ultimo_giorni=7)).conto.margine_eur
        prima = S.stima(OGGI, STANDARD, NUOVO, S.Variazione(ultimo_giorni=-7)).conto.margine_eur
        self.assertLess(dopo, base)
        self.assertGreater(prima, base)

    def test_simulazione_stabile_e_plausibile(self):
        a = S.simula(OGGI, STANDARD, NUOVO, n=2000)
        b = S.simula(OGGI, STANDARD, NUOVO, n=2000)
        self.assertEqual(a.probabilita, b.probabilita)             # stesso seme, stesso risultato
        self.assertTrue(0.5 < a.probabilita < 0.75, a.probabilita)
        self.assertTrue(a.sfavorevole_eur < a.atteso_eur < a.favorevole_eur)

    def test_date_confermate_restringono_l_intervallo(self):
        larga = S.simula(OGGI, STANDARD, NUOVO, n=2000)
        stretta = S.simula(OGGI, S.con_scenario(STANDARD, date_confermate=True), NUOVO, n=2000)
        self.assertLess(stretta.favorevole_eur - stretta.sfavorevole_eur, larga.favorevole_eur - larga.sfavorevole_eur)

    def test_leve_ordinate_per_peso(self):
        l = S.leve(OGGI, STANDARD, NUOVO)
        pesi = [max(abs(x[2]), abs(x[4])) for x in l]
        self.assertEqual(pesi, sorted(pesi, reverse=True))
        self.assertEqual(l[0][0], "Ultimo carico, 7 giorni")

    def test_pareggio(self):
        c = S.stima(OGGI, STANDARD, NUOVO).conto
        p = S.indice_pareggio(c, NUOVO)
        self.assertGreater(p, c.indice)                            # oggi siamo sotto il pareggio: a premio
        self.assertAlmostEqual(p, 3.24, delta=0.03)


class CicloFinito(unittest.TestCase):
    def test_a_ciclo_finito_la_stima_e_il_conto(self):
        # tutto partito e riscontrato: niente da prevedere, niente incertezza sulle date
        carichi = (S.Carico(capi=1429, peso_vivo_kg=171.96, capi_riscontrati=1429, peso_morto_kg=203058.818 / 1429),)
        fine = S.Situazione(
            oggi=date(2026, 5, 12), ultimo_giorno_pagato_prec=date(2025, 10, 1),
            mangime_bolle_kg=692280, giacenza_iniziale_kg=10000, giacenza_oggi_kg=3000, consumo_mangime_giorno_kg=0,
            carichi=carichi, capi_presenti=0, siero_fatturato_eur=17477.09, anticipi_eur=54000,
        )
        sce = S.Scenario(primo_carico=date(2026, 4, 20), ultimo_carico=date(2026, 5, 11), premi_perc=8)
        st = S.stima(fine, sce, NUOVO)
        self.assertAlmostEqual(st.conto.resa_eur, 56924.30, places=1)
        self.assertEqual(st.conto.giorni, 222)
        self.assertEqual(st.mangime_residuo_kg, 0)
        sim = S.simula(fine, sce, NUOVO, n=500, premi_noti=True)
        self.assertEqual(sim.probabilita, 0.0)                     # ciclo 6: sotto il minimo, senza dubbi


if __name__ == "__main__":
    unittest.main()
