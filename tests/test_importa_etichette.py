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
        # il grano saraceno non ha glutine
        self.assertEqual(imp.allergeni_di("grano Saraceno"), [])
        self.assertEqual(imp.evidenzia("grano Saraceno"), "grano Saraceno")

    def test_ricette_dalle_etichette(self):
        """Ricetta v1 con gli ingredienti dell'etichetta, quantità 0, nell'ordine dell'etichetta; rilanciabile."""
        import json, sqlite3, tempfile
        spec = importlib.util.spec_from_file_location("schema_p", os.path.join(
            os.path.dirname(__file__), "..", "app", "moduli", "prodotti", "schema.py"))
        schema = importlib.util.module_from_spec(spec); spec.loader.exec_module(schema)
        spec = importlib.util.spec_from_file_location("migr", os.path.join(
            os.path.dirname(__file__), "..", "app", "moduli", "migrazioni.py"))
        migr = importlib.util.module_from_spec(spec); spec.loader.exec_module(migr)
        with tempfile.TemporaryDirectory() as d:
            db, bozza = os.path.join(d, "p.db"), os.path.join(d, "b.json")
            migr.applica(db, schema.MIGRAZIONI, "prodotti", os.path.join(d, "bk"), copia=lambda a, b: None)
            with open(bozza, "w") as f:
                json.dump({"prodotti": [
                    {"nome": "Marmellata di fichi", "peso_netto": 212, "ingredienti": "fichi freschi e zucchero."},
                    {"nome": "Senza ingredienti", "peso_netto": None, "ingredienti": ""}]}, f)
            imp.carica(bozza, db)
            imp.ricette(bozza, db)
            imp.ricette(bozza, db)                              # la seconda volta non fa niente
            c = sqlite3.connect(db)
            righe = c.execute("SELECT m.nome, rr.quantita FROM ricette_righe rr JOIN materie_prime m "
                              "ON m.id = rr.materia_prima_id ORDER BY rr.ordine").fetchall()
            self.assertEqual(righe, [("Fichi freschi", 0), ("Zucchero", 0)])
            self.assertEqual(c.execute("SELECT count(*) FROM ricette").fetchone()[0], 1)
            self.assertIsNotNone(c.execute("SELECT ricetta_default_id FROM prodotti WHERE nome LIKE 'Marm%'").fetchone()[0])

    def test_sigla(self):
        self.assertEqual(imp.proponi_sigla("Cacciatorino"), "CAC")
        self.assertEqual(imp.proponi_sigla("Marmellata di fichi"), "MFI")
        self.assertEqual(imp.proponi_sigla("Ragù di salsiccia"), "RSA")


if __name__ == "__main__":
    unittest.main()
