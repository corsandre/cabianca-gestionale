"""Test di app/moduli/prodotti/services/ingredienti.py e allergeni.py."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from _prodotti_services import servizi  # noqa: E402

ing = servizi("ingredienti")
all_ = servizi("allergeni")

# Ricetta dei tortelli di zucca (quantità inventate per la prova)
TORTELLI = [
    {"nome_etichetta": "farina di GRANO tenero tipo 00", "quantita": 1, "unita": "kg", "allergeni": ["glutine"]},
    {"nome_etichetta": "zucca", "quantita": 1500, "unita": "g"},
    {"nome_etichetta": "uova", "quantita": 400, "unita": "g", "allergeni": ["uova"]},
    {"nome_etichetta": "mostarda", "quantita": 150, "unita": "g", "allergeni": ["senape"],
     "composta": "frutta, zucchero, essenza di SENAPE"},
    {"nome_etichetta": "sale", "quantita": 20, "unita": "g"},
]


class TestTestoIngredienti(unittest.TestCase):
    def test_ordine_per_peso_e_grassetti(self):
        self.assertEqual(
            ing.testo_ingredienti(TORTELLI),
            "Ingredienti: zucca, farina di **GRANO** tenero tipo 00, **UOVA**, "
            "mostarda (frutta, zucchero, essenza di **SENAPE**), sale.")

    def test_allergene_senza_maiuscole_tutto_in_grassetto(self):
        self.assertEqual(ing.voce_etichetta("ricotta vaccina", ["latte"]), "**RICOTTA VACCINA**")
        self.assertEqual(ing.voce_etichetta("ricotta vaccina (LATTE)", ["latte"]), "ricotta vaccina (**LATTE**)")
        self.assertEqual(ing.voce_etichetta("amaretti", ["uova"], "contengono UOVA"), "amaretti (contengono **UOVA**)")

    def test_sigle_non_sono_allergeni(self):
        self.assertEqual(
            ing.voce_etichetta("Grana Padano DOP", ["latte", "uova"], "LATTE, sale, caglio, conservante: lisozima da UOVO"),
            "Grana Padano DOP (**LATTE**, sale, caglio, conservante: lisozima da **UOVO**)")
        self.assertEqual(ing.voce_etichetta("olio EVO"), "olio EVO")

    def test_stesso_ingrediente_sommato(self):
        righe = [{"nome_etichetta": "zucchero", "quantita": 100}, {"nome_etichetta": "fichi", "quantita": 150},
                 {"nome_etichetta": "Zucchero", "quantita": 100}]
        self.assertEqual(ing.testo_ingredienti(righe), "Ingredienti: zucchero, fichi.")

    def test_parita_resta_ordine_ricetta_e_vuoto(self):
        righe = [{"nome_etichetta": "a", "quantita": 10}, {"nome_etichetta": "b", "quantita": 10}]
        self.assertEqual(ing.testo_ingredienti(righe, prefisso=""), "a, b.")
        self.assertEqual(ing.testo_ingredienti([]), "")

    def test_allergeni_presenti_e_percentuali(self):
        self.assertEqual(ing.allergeni_presenti(TORTELLI), ["glutine", "uova", "senape"])
        self.assertEqual(all_.descrivi(["senape", "glutine", "boh"]), "glutine, senape")
        p = ing.percentuali(TORTELLI)
        self.assertEqual(p["zucca"], round(1500 * 100 / 3070, 1))

    def test_html_sicuro(self):
        self.assertEqual(ing.testo_html("farina di **GRANO** <b>"), "farina di <strong>GRANO</strong> &lt;b&gt;")


if __name__ == "__main__":
    unittest.main()
