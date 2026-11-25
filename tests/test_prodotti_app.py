"""Test del modulo Prodotti dentro l'app vera (servono Flask e le dipendenze: usare .venv/bin/python).

- i modelli (models.py) rispecchiano le tabelle create dalle migrazioni (schema.py);
- le tabelle del modulo stanno in prodotti.db e NON in gestionale.db;
- le pagine del modulo rispondono (permessi, creazione di materie prime, prodotti, ricette, lotti).
Le credenziali del .env vengono svuotate come in test_avvio_ruoli.py.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import test_avvio_ruoli as base  # noqa: E402  (svuota le credenziali e sa isolare il pacchetto app)


@unittest.skipUnless(base.HA_FLASK, "serve Flask (usare .venv/bin/python)")
class ProdottiAppBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._moduli_altrui = base._togli_moduli_app()

    @classmethod
    def tearDownClass(cls):
        base._togli_moduli_app()
        sys.modules.update(cls._moduli_altrui)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cartella = os.path.join(self.tmp.name, "data")
        os.makedirs(self.cartella)
        from app.config import Config
        self._p = [mock.patch.object(Config, "SQLALCHEMY_DATABASE_URI",
                                     f"sqlite:///{os.path.join(self.cartella, 'gestionale.db')}"),
                   mock.patch.dict(os.environ, {"RUOLO": "sviluppo", "MODULI": "prodotti"})]
        for p in self._p:
            p.start()
        import app as pacchetto
        self.app = pacchetto.create_app()
        self.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
        from app import db
        from app.models import User
        import json
        with self.app.app_context():
            self.admin_id = User.query.filter_by(role="admin").first().id
            u = User(username="lab", password_hash="x", display_name="Laboratorio", role="operatore", active=True,
                     sections=json.dumps(["prodotti"]))
            c = User(username="cons", password_hash="x", display_name="Consulente", role="consulente", active=True,
                     sections=json.dumps(["prodotti"]))
            db.session.add_all([u, c])
            db.session.commit()
            self.operatore_id, self.consulente_id = u.id, c.id

    def tearDown(self):
        from app import db
        with self.app.app_context():
            db.session.remove()
            db.engines  # noqa: B018
            for e in db.engines.values():
                e.dispose()
        for p in reversed(self._p):
            p.stop()
        self.tmp.cleanup()

    def client(self, uid=None):
        c = self.app.test_client()
        with c.session_transaction() as s:
            s["_user_id"] = str(uid or self.admin_id)
            s["_fresh"] = True
        return c


class TestModelliSchema(ProdottiAppBase):
    def test_modelli_rispecchiano_tabelle(self):
        from app.moduli.prodotti import models
        con = sqlite3.connect(os.path.join(self.cartella, "prodotti.db"))
        for nome in dir(models):
            cls = getattr(models, nome)
            tabella = getattr(cls, "__tablename__", None)
            if not tabella or getattr(cls, "__bind_key__", None) != "prodotti":
                continue
            nel_db = {r[1] for r in con.execute(f"PRAGMA table_info({tabella})")}
            nel_modello = {c.name for c in cls.__table__.columns}
            self.assertTrue(nel_db, f"tabella {tabella} mancante")
            self.assertEqual(nel_modello - nel_db, set(), f"{nome}: colonne del modello assenti nel database")
        con.close()

    def test_tabelle_non_finiscono_in_gestionale_db(self):
        con = sqlite3.connect(os.path.join(self.cartella, "gestionale.db"))
        tabelle = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        con.close()
        self.assertFalse(tabelle & {"lotti", "ricette", "prodotti", "materie_prime", "schema_versione"})


class TestFlussoCompleto(ProdottiAppBase):
    """Dal catalogo vuoto al secondo lotto, come lo farebbe il laboratorio."""

    def post(self, url, dati, uid=None, atteso=200):
        r = self.client(uid).post(url, json=dati)
        self.assertEqual(r.status_code, atteso, f"{url}: {r.get_data(as_text=True)[:300]}")
        return r.get_json()

    def test_flusso(self):
        op = self.operatore_id
        # materie prime (una con fornitore nuovo creato al volo, una di produzione propria)
        farina = self.post("/prodotti/materie-prime/salva", {"nome": "Farina 00", "nome_etichetta": "farina di GRANO tenero tipo 00",
                                                             "allergeni": ["glutine"], "nuovo_fornitore": "Molino Rossi"}, op)["materia"]
        self.assertEqual(farina["fornitore_nome"], "Molino Rossi")
        zucca = self.post("/prodotti/materie-prime/salva", {"nome": "Zucca", "produzione_propria": True}, op)["materia"]
        uova = self.post("/prodotti/materie-prime/salva", {"nome": "Uova", "nome_etichetta": "uova", "allergeni": ["uova"]}, op)["materia"]
        self.post("/prodotti/materie-prime/salva", {"nome": "zucca"}, op, atteso=400)      # doppione
        # prodotto
        p = self.post("/prodotti/catalogo/salva", {"nome": "Tortelli di zucca", "peso_netto": "500", "unita": "g",
                                                   "durata_giorni": "92", "formato_etichetta_id": "1"}, op)["prodotto"]
        self.assertEqual(p["sigla"], "TZU")
        # ricetta: anteprima e salvataggio
        righe = [{"materia_prima_id": farina["id"], "quantita": "1", "unita": "kg"},
                 {"materia_prima_id": zucca["id"], "quantita": "1500", "unita": "g"},
                 {"materia_prima_id": uova["id"], "quantita": "400", "unita": "g"}]
        a = self.post("/prodotti/ricette/anteprima", {"righe": righe}, op)
        self.assertEqual(a["testo"], "Ingredienti: zucca, farina di **GRANO** tenero tipo 00, **UOVA**.")
        ric = self.post("/prodotti/ricette/salva", {"prodotto_id": p["id"], "resa_pezzi": "20", "righe": righe}, op)["ricetta"]
        self.assertEqual(ric["versione"], 1)
        # il consulente non può scrivere
        self.post("/prodotti/ricette/salva", {"prodotto_id": p["id"], "righe": righe}, self.consulente_id, atteso=403)

        # nuovo lotto: dati proposti
        c = self.client(op)
        prep = c.get(f"/prodotti/lotti/prepara?prodotto_id={p['id']}&data=2026-11-24&pezzi=40").get_json()
        self.assertEqual(prep["codice"], "L241126-TZU")
        self.assertEqual(prep["scadenza"], "2027-02-24")
        self.assertEqual([r["quantita"] for r in prep["righe"]], [2, 3000, 800])          # ricetta per 20 → 40
        righe_lotto = prep["righe"]
        righe_lotto[0].update(lotto_fornitore="MR-2611", rif_documento="DDT 55")
        salvato = self.post("/prodotti/lotti/salva", {"prodotto_id": p["id"], "ricetta_id": ric["id"], "data": "2026-11-24",
                                                      "pezzi": 40, "codice": prep["codice"], "scadenza": prep["scadenza"],
                                                      "righe": righe_lotto}, op)
        self.assertIn("Uova", salvato["avviso"])                       # uova senza lotto fornitore
        # secondo lotto lo stesso giorno: codice -2 e lotto della farina ripreso dall'ultimo
        prep2 = c.get(f"/prodotti/lotti/prepara?prodotto_id={p['id']}&data=2026-11-24").get_json()
        self.assertEqual(prep2["codice"], "L241126-TZU-2")
        self.assertEqual(prep2["righe"][0]["lotto_fornitore"], "MR-2611")
        self.assertTrue(prep2["righe"][0]["precompilato"])
        self.post("/prodotti/lotti/salva", {"prodotto_id": p["id"], "data": "2026-11-24", "codice": "L241126-TZU",
                                            "righe": righe_lotto}, op, atteso=400)     # codice doppio

        # correzione del lotto: lo storico la registra
        self.post("/prodotti/lotti/salva", {"id": salvato["id"], "prodotto_id": p["id"], "ricetta_id": ric["id"],
                                            "data": "2026-11-24", "pezzi": 38, "codice": "L241126-TZU",
                                            "righe": righe_lotto[:2]}, op)
        pagina = c.get(f"/prodotti/lotti/{salvato['id']}").get_data(as_text=True)
        self.assertIn("Storico delle correzioni", pagina)
        self.assertIn("Laboratorio", pagina)

        # la ricetta ora è usata: modificarla crea la v2
        r2 = self.post("/prodotti/ricette/salva", {"id": ric["id"], "prodotto_id": p["id"], "resa_pezzi": "20", "righe": righe[:2]}, op)
        self.assertEqual(r2["ricetta"]["versione"], 2)
        self.assertIn("nuova versione", r2["messaggio"])

        # stato: il ritiro vuole il motivo
        self.post(f"/prodotti/lotti/{salvato['id']}/stato", {"stato": "ritirato"}, op, atteso=400)
        self.post(f"/prodotti/lotti/{salvato['id']}/stato", {"stato": "ritirato", "motivo": "richiamo farina"}, op)

        # etichette: anteprima, stampa archiviata, download; il consulente vede ma non stampa
        prova = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/prova", {"modalita": "unica"}, op)
        self.assertTrue(prova["immagini"][0]["src"].startswith("data:image/png;base64,"))
        self.assertEqual(prova["fogli"], 5)                        # 38 confezioni, 8 per foglio (Grande)
        self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 10}, self.consulente_id, atteso=403)
        st = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 10, "formato_id": 3,
                                                                               "modalita": "fronte_retro"}, op)
        self.assertEqual((st["n_etichette"], st["fogli"]), (20, 1))     # Piccolo: 24 per foglio
        pdf = c.get(st["url"])
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        from app import db
        from app.moduli.prodotti.models import StampaEtichetta
        with self.app.app_context():
            s = StampaEtichetta.query.one()
            import hashlib
            self.assertEqual(hashlib.sha256(pdf.data).hexdigest(), s.sha256)
            self.assertTrue(os.path.exists(os.path.join(self.cartella, "prodotti", "etichette", "2026", os.path.basename(s.pdf_path))))
            with self.assertRaises(Exception):                     # archivio intoccabile
                db.session.delete(s)
                db.session.commit()
            db.session.rollback()

        # formati: solo l'admin li modifica; un formato che esce dal foglio è rifiutato; calibrazione in PDF
        self.post("/prodotti/formati/salva", {"id": 1, "nome": "Grande", "larghezza_mm": 105, "altezza_mm": 74,
                                              "colonne": 2, "righe": 4}, op, atteso=403)
        self.post("/prodotti/formati/salva", {"nome": "Rotto", "larghezza_mm": 110, "altezza_mm": 74,
                                              "colonne": 2, "righe": 4}, atteso=400)
        self.post("/prodotti/formati/salva", {"nome": "Tondo 60", "larghezza_mm": 60, "altezza_mm": 60,
                                              "colonne": 3, "righe": 4, "margine_sup_mm": 15, "margine_sx_mm": 10,
                                              "passo_orizz_mm": 65, "passo_vert_mm": 67, "layout": "compatto"})
        self.assertTrue(self.client().get("/prodotti/formati/1/calibrazione.pdf").data.startswith(b"%PDF"))
        self.assertTrue(self.client().get("/prodotti/formati/prova-margini.pdf").data.startswith(b"%PDF"))
        self.assertIn("immagini", self.post("/prodotti/formati/2/prova", {}, op))
        self.post("/prodotti/formati/impostazioni", {"stile": "base-2026", "piede": "www.cabianca.eu"})

        # export: libro lotti e ricettario in PDF ed Excel, richiamo
        for url in ("/prodotti/lotti/esporta.pdf?dal=2026-01-01", "/prodotti/ricettario/esporta.pdf",
                    f"/prodotti/ricettario/esporta.pdf?ricetta={ric['id']}",
                    f"/prodotti/richiamo/esporta.pdf?materia={farina['id']}"):
            r = c.get(url)
            self.assertTrue(r.data.startswith(b"%PDF"), url)
        import io
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(c.get("/prodotti/lotti/esporta.xlsx").data))
        self.assertEqual(wb.sheetnames, ["Lotti", "Ingredienti"])
        self.assertEqual(wb["Ingredienti"]["I2"].value, "MR-2611")               # lotto fornitore della farina
        wb = load_workbook(io.BytesIO(c.get("/prodotti/ricettario/esporta.xlsx").data))
        self.assertEqual(wb["Ricette"].max_row, 3)                               # intestazione + v1 + v2
        pagina = c.get(f"/prodotti/richiamo?lotto=MR-26").get_data(as_text=True)
        self.assertIn("1 lotto coinvolto", pagina)
        self.post("/prodotti/richiamo/ritira", {"ids": [salvato["id"]]}, op, atteso=400)   # serve il motivo
        self.assertEqual(self.post("/prodotti/richiamo/ritira", {"ids": [salvato["id"]], "motivo": "prova"}, op)["n"], 1)

        # tutte le pagine si aprono, per operatore e consulente
        for uid in (op, self.consulente_id):
            cl = self.client(uid)
            for url in ("/prodotti/", "/prodotti/lotti", f"/prodotti/lotti/{salvato['id']}", "/prodotti/catalogo",
                        f"/prodotti/catalogo/{p['id']}", "/prodotti/ricettario", "/prodotti/materie-prime", "/prodotti/formati", "/prodotti/richiamo",
                        f"/prodotti/lotti?nuovo={p['id']}", "/prodotti/lotti?stato=ritirato&dal=2026-01-01"):
                self.assertEqual(cl.get(url).status_code, 200, url)


if __name__ == "__main__":
    unittest.main()
