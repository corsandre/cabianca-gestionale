"""Etichette disegnate da più thread insieme (app/moduli/prodotti/services/etichette.py).

Il 25/11/2026 due anteprime contemporanee hanno fatto cadere il sito ("free(): invalid next size", 502):
WeasyPrint non regge disegni in parallelo. Ora passano da un lucchetto. Senza il lucchetto questo test
tende a far cadere il processo. Gira solo dove c'è WeasyPrint (.venv).
"""
import importlib.util
import os
import threading
import unittest

try:
    import weasyprint  # noqa: F401
    HA_WEASYPRINT = True
except Exception:
    HA_WEASYPRINT = False

_spec = importlib.util.spec_from_file_location("etichette_srv", os.path.join(
    os.path.dirname(__file__), "..", "app", "moduli", "prodotti", "services", "etichette.py"))
et = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(et)

HTML = """<html><head><style>@page {{ size: 60mm 40mm; margin: 0 }}
.etichetta {{ width: 60mm; height: 40mm; font-family: sans-serif; font-size: {pt}pt }}</style></head>
<body><div class="etichetta"><p>{testo}</p></div></body></html>"""


@unittest.skipUnless(HA_WEASYPRINT, "serve WeasyPrint (usare .venv/bin/python)")
class TestEtichetteInParallelo(unittest.TestCase):
    def test_disegni_contemporanei(self):
        errori, fatti = [], []

        def lavoro(n):
            try:
                for i in range(4):
                    testo = ("Ingredienti: farina di GRANO tenero tipo 00, zucca, UOVA, sale. " * (1 + (n + i) % 4))
                    dati, _ = et.pdf(HTML.format(pt=8, testo=testo), "/")
                    self.assertTrue(dati.startswith(b"%PDF"))
                    et.scala_che_ci_sta(lambda s: HTML.format(pt=round(8 * s, 2), testo=testo), "/", passi=3)
                fatti.append(n)
            except Exception as e:          # pragma: no cover - solo se qualcosa si rompe
                errori.append(repr(e))

        thread = [threading.Thread(target=lavoro, args=(n,)) for n in range(6)]
        for t in thread:
            t.start()
        for t in thread:
            t.join(timeout=300)
        self.assertEqual(errori, [])
        self.assertEqual(sorted(fatti), list(range(6)))

    def test_lucchetto_rientrante(self):
        # scala_che_ci_sta tiene il lucchetto e chiama sborda, che lo riprende: non deve bloccarsi
        with et._WEASYPRINT:
            self.assertFalse(et.sborda(HTML.format(pt=6, testo="corto"), "/"))


if __name__ == "__main__":
    unittest.main()
