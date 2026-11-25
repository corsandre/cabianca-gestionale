"""Test delle funzioni di pulizia di scripts/importa_etichette.py (catalogo dalle etichette storiche)."""
import importlib.util
import os
import unittest

_spec = importlib.util.spec_from_file_location(
    "importa_etichette", os.path.join(os.path.dirname(__file__), "..", "scripts", "importa_etichette.py"))
imp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(imp)


class TestImporta(unittest.TestCase):
    def test_taglio_al_punto_e_al_nome(self):
        self.assertEqual(imp.fino_al_punto("fichi e zucchero. Marmellata di fichi"), "fichi e zucchero.")
        self.assertEqual(imp.fino_al_punto("senape (aroma conforme al reg. CE). Mostarda"), "senape (aroma conforme al reg. CE).")
        self.assertEqual(imp.pulisci_ingredienti("meloni, zucchero e limone Marmellata di melone", "Marmellata melone"),
                         "meloni, zucchero e limone.")
        self.assertEqual(imp.pulisci_ingredienti("grano duro (Khorasan) contiene glutine", "Saragolla"),
                         "grano duro (Khorasan).")

    def test_separa_ingredienti(self):
        self.assertEqual(imp.separa_ingredienti("Ingredienti: fichi freschi e zucchero."),
                         [("fichi freschi", ""), ("zucchero", "")])
        self.assertEqual(imp.separa_ingredienti("Grana Padano (latte, sale), uova"),
                         [("Grana Padano", "latte, sale"), ("uova", "")])

    def test_allergeni_e_evidenza(self):
        self.assertEqual(imp.allergeni_di("farina di grano tenero"), ["glutine"])
        self.assertEqual(imp.allergeni_di("mortadella", "con PISTACCHI"), ["frutta_guscio"])
        self.assertEqual(imp.evidenzia("farina di grano tenero"), "farina di GRANO tenero")

    def test_sigla(self):
        self.assertEqual(imp.proponi_sigla("Cacciatorino"), "CAC")
        self.assertEqual(imp.proponi_sigla("Marmellata di fichi"), "MFI")
        self.assertEqual(imp.proponi_sigla("Ragù di salsiccia"), "RSA")


if __name__ == "__main__":
    unittest.main()
