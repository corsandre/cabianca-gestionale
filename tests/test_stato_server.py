"""
Prove dello stato del server (app/services/stato_server.py e scripts/stato_server.py).

    python3 -m unittest discover -s tests -v
"""
import importlib.util
import os
import tempfile
import unittest
from datetime import datetime

_qui = os.path.dirname(__file__)


def _carica(nome, percorso):
    spec = importlib.util.spec_from_file_location(nome, os.path.join(_qui, "..", percorso))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _carica("stato_server", "app/services/stato_server.py")
SCRIPT = _carica("stato_server_script", "scripts/stato_server.py")
GB = 1024 ** 3

DISCO = {"totale": 100 * GB, "usato": 70 * GB, "libero": 30 * GB}
SCRIPT_DATI = {
    "aggiornato": "2026-11-20T10:00:00",
    "docker": {"immagini": {"usato": 12 * GB, "recuperabile": 1 * GB},
               "cache_build": {"usato": 55 * GB, "recuperabile": 52 * GB},
               "container": {"usato": GB // 4, "recuperabile": 0}, "volumi": {"usato": GB // 8, "recuperabile": 0}},
    "servizi": {"ordini": 2 * 1024 ** 2, "social": 150 * 1024 ** 2},
    "log_sistema": 95 * 1024 ** 2,
    "container": [{"nome": "cabianca-social-postiz-1", "memoria": int(1.5 * GB), "cpu": 14.0},
                  {"nome": "cabianca-social-temporal-1", "memoria": GB // 4, "cpu": 5.0},
                  {"nome": "cabianca-gestionale-web-1", "memoria": GB // 8, "cpu": 0.1},
                  {"nome": "cabianca-gestionale-impianto-1", "memoria": GB // 10, "cpu": 0.1},
                  {"nome": "altro-1", "memoria": GB // 20, "cpu": 0}],
}


class TestiDelloScript(unittest.TestCase):
    def test_byte_da_testo(self):
        self.assertEqual(SCRIPT.byte_da_testo("12.22GB"), 12_220_000_000)
        self.assertEqual(SCRIPT.byte_da_testo("777.8MB (6%)"), 777_800_000)
        self.assertEqual(SCRIPT.byte_da_testo("93.92MiB"), int(93.92 * 1024 ** 2))
        self.assertEqual(SCRIPT.byte_da_testo("0B"), 0)
        self.assertEqual(SCRIPT.byte_da_testo(""), 0)


class Disco(unittest.TestCase):
    def test_i_segmenti_fanno_il_totale(self):
        cartelle = {"bolle": {"byte": 27 * 1024 ** 2}, "database": {"byte": 4 * 1024 ** 2}}
        seg = S.segmenti_disco(DISCO, cartelle, SCRIPT_DATI)
        self.assertEqual(sum(s["byte"] for s in seg), DISCO["totale"])
        self.assertAlmostEqual(sum(s["perc"] for s in seg), 100)
        cache = next(s for s in seg if s["chiave"] == "docker_cache")
        self.assertEqual(cache["byte"], 55 * GB)

    def test_senza_script_tutto_il_resto_in_sistema(self):
        seg = S.segmenti_disco(DISCO, {"bolle": {"byte": GB}}, {})
        self.assertFalse(any(s["chiave"].startswith("docker") for s in seg))
        self.assertEqual(next(s for s in seg if s["chiave"] == "sistema")["byte"], 69 * GB)

    def test_sistema_mai_negativo(self):
        seg = S.segmenti_disco({"totale": 10 * GB, "usato": 5 * GB, "libero": 5 * GB}, {}, SCRIPT_DATI)
        self.assertEqual(next(s for s in seg if s["chiave"] == "sistema")["byte"], 0)


class Memoria(unittest.TestCase):
    def test_container_raggruppati_per_servizio(self):
        mem = {"totale": 8 * GB, "disponibile": 4 * GB}
        seg = {s["chiave"]: s for s in S.segmenti_memoria(mem, SCRIPT_DATI)}
        self.assertEqual(seg["cabianca-social"]["byte"], int(1.5 * GB) + GB // 4)
        self.assertEqual(seg["cabianca-gestionale"]["byte"], GB // 8 + GB // 10)
        self.assertEqual(seg["altri"]["byte"], GB // 20)
        self.assertEqual(seg["libero"]["byte"], 4 * GB)
        self.assertEqual(sum(s["byte"] for s in seg.values()), 8 * GB)


class Crescita(unittest.TestCase):
    def test_con_la_storia_del_disco(self):
        storia = [{"data": f"2026-11-{g:02d}", "disco_usato": 60 * GB + (g - 1) * GB} for g in range(1, 11)]
        cr = S.crescita(storia, {}, 30 * GB)
        self.assertAlmostEqual(cr["disco_mese"], 30 * GB)        # 9 GB in 9 giorni → 30 GB al mese
        self.assertAlmostEqual(cr["mesi_al_pieno"], 1)

    def test_senza_storia_solo_i_file_del_gestionale(self):
        cr = S.crescita([], {"bolle": {"ultimi_30": GB}, "backup": {"ultimi_30": GB}}, 30 * GB)
        self.assertIsNone(cr["disco_mese"])
        self.assertEqual(cr["gestionale_mese"], 2 * GB)
        self.assertAlmostEqual(cr["mesi_al_pieno"], 15)

    def test_disco_che_cala(self):
        storia = [{"data": f"2026-11-{g:02d}", "disco_usato": 70 * GB - g * GB} for g in range(1, 9)]
        self.assertIsNone(S.crescita(storia, {}, 30 * GB)["mesi_al_pieno"])


class Avvisi(unittest.TestCase):
    MEM = {"totale": 8 * GB, "disponibile": 4 * GB, "swap_usata": 0}

    def test_cache_di_docker_da_pulire(self):
        a = S.avvisi(70, self.MEM, SCRIPT_DATI, 60)
        self.assertEqual(len(a), 1)
        self.assertIn("docker builder prune", a[0])

    def test_disco_quasi_pieno_e_memoria(self):
        a = S.avvisi(88, {"totale": 8 * GB, "disponibile": GB // 2, "swap_usata": GB}, {}, None)
        self.assertTrue(any("Disco quasi pieno" in x for x in a))
        self.assertTrue(any("Memoria quasi finita" in x for x in a))
        self.assertTrue(any("swap" in x for x in a))

    def test_livelli(self):
        self.assertEqual([S.livello(p) for p in (50, 75, 89.9, 90)], ["ok", "attenzione", "attenzione", "critico"])


class Testi(unittest.TestCase):
    def test_byte_e_durata(self):
        self.assertEqual(S.testo_byte(81 * 1024 ** 2), "81,0 MB")
        self.assertEqual(S.testo_byte(int(54.8 * GB)), "54,8 GB")
        self.assertEqual(S.testo_byte(640 * 1024), "640 kB")
        self.assertEqual(S.testo_durata(32 * 86400 + 5), "32 giorni")
        self.assertEqual(S.testo_durata(5 * 3600), "5 ore")
        self.assertEqual(S.testo_durata(30), "1 minuto")

    def test_eta_dello_script(self):
        self.assertEqual(S.eta_secondi(SCRIPT_DATI, datetime(2026, 11, 20, 10, 15)), 900)
        self.assertIsNone(S.eta_secondi({}))


class Cartelle(unittest.TestCase):
    def test_voci_del_gestionale(self):
        with tempfile.TemporaryDirectory() as d:
            up, data, bk = (os.path.join(d, x) for x in ("uploads", "data", "backups"))
            for p in (up + "/allevamento_consegne", up + "/fatture_emesse", data + "/impianto", bk):
                os.makedirs(p)
            for p, n in ((up + "/allevamento_consegne/a.jpg", 300), (up + "/x.xml.pdf", 20), (up + "/y.xml", 10),
                         (data + "/gestionale.db", 1000), (data + "/gestionale.db.pre-deploy-3.1.4", 900),
                         (data + "/stato_server.json", 5), (data + "/impianto/s.png", 50), (bk + "/b.db", 800)):
                with open(p, "wb") as f:
                    f.write(b"x" * n)
            c = S.cartelle_gestionale(up, data, bk)
        self.assertEqual(c["bolle"], {"byte": 300, "file": 1, "ultimi_30": 300})
        self.assertEqual(c["fatture_ricevute"]["byte"], 30)
        self.assertEqual(c["database"]["byte"], 1000)
        self.assertEqual(c["copie_db"]["byte"], 900)
        self.assertEqual(c["impianto"]["byte"], 50)
        self.assertEqual(c["backup"]["byte"], 800)
        self.assertEqual(c["altri_upload"]["byte"], 0)      # stato_server.json non conta


if __name__ == "__main__":
    unittest.main()
