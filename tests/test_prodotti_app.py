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
        # prodotto GENERICO (dalla 2.0.0 peso e foglio sono del contenitore)
        p = self.post("/prodotti/catalogo/salva", {"nome": "Tortelli di zucca", "durata_giorni": "92"}, op)["prodotto"]
        self.assertEqual(p["sigla"], "TZU")
        self.assertNotIn("peso_netto", p)
        # contenitori della migrazione 6: la busta da 500 g ha il foglio Grande; in Contenitori si aggiunge il Piccolo
        from app.moduli.prodotti.models import Contenitore
        with self.app.app_context():
            busta = Contenitore.query.filter_by(nome="Busta pasta 500 g").one()
            busta_id, busta250_id = busta.id, Contenitore.query.filter_by(nome="Busta pasta 250 g").one().id
            self.assertEqual([f.codice_foglio for f in busta.formati], ["Avery L7165"])
        pagina = self.client(op).get("/prodotti/contenitori").get_data(as_text=True)
        self.assertIn("Busta pasta 500 g", pagina)
        self.post("/prodotti/contenitori/salva", {"id": busta_id, "nome": "Busta pasta 500 g", "peso_netto": "500",
                                                  "formati": []}, op, atteso=400)          # serve almeno un foglio
        self.post("/prodotti/contenitori/salva", {"nome": "busta pasta 500 G", "formati": ["5"]}, op, atteso=400)  # doppione
        self.post("/prodotti/contenitori/salva", {"id": busta_id, "nome": "Busta pasta 500 g", "peso_netto": "500",
                                                  "unita": "g", "formati": ["5", "7"], "formato_predefinito_id": "5"}, op)
        self.post("/prodotti/contenitori/salva", {"nome": "Vaschetta", "formati": ["5"]}, self.consulente_id, atteso=403)
        # ricetta: anteprima e salvataggio
        righe = [{"materia_prima_id": farina["id"], "quantita": "1", "unita": "kg"},
                 {"materia_prima_id": zucca["id"], "quantita": "1500", "unita": "g"},
                 {"materia_prima_id": uova["id"], "quantita": "400", "unita": "g"}]
        a = self.post("/prodotti/ricette/anteprima", {"righe": righe}, op)
        self.assertEqual(a["testo"], "Ingredienti: zucca, farina di **GRANO** tenero tipo 00, **UOVA**.")
        ric = self.post("/prodotti/ricette/salva", {"prodotto_id": p["id"], "resa_pezzi": "20", "resa_kg": "10",
                                                    "righe": righe, "contenitori": [{"contenitore_id": busta_id}]}, op)["ricetta"]
        self.assertEqual(ric["versione"], 1)
        self.assertEqual([x["nome"] for x in ric["contenitori"]], ["Busta pasta 500 g"])
        # il consulente non può scrivere
        self.post("/prodotti/ricette/salva", {"prodotto_id": p["id"], "righe": righe}, self.consulente_id, atteso=403)

        # nuovo lotto: dati proposti
        c = self.client(op)
        import json as _json
        proposta = c.get(f"/prodotti/lotti/prepara?prodotto_id={p['id']}&data=2026-11-24").get_json()
        self.assertEqual(proposta["confezioni"], [{"contenitore_id": busta_id, "pezzi": 20}])   # resa della ricetta
        self.assertEqual([x["id"] for x in proposta["contenitori"]], [busta_id])             # solo i compatibili
        conf = _json.dumps([{"contenitore_id": busta_id, "pezzi": 40}])
        prep = c.get(f"/prodotti/lotti/prepara?prodotto_id={p['id']}&data=2026-11-24&confezioni={conf}").get_json()
        self.assertEqual(prep["codice"], "L241126-TZU")
        self.assertEqual(prep["scadenza"], "2027-02-24")
        self.assertEqual(prep["kg"], 20)
        self.assertEqual([r["quantita"] for r in prep["righe"]], [2, 3000, 800])          # 40 × 500 g = 20 kg, ricetta per 10 kg
        righe_lotto = prep["righe"]
        righe_lotto[0].update(lotto_fornitore="MR-2611", rif_documento="DDT 55")
        self.post("/prodotti/lotti/salva", {"prodotto_id": p["id"], "ricetta_id": ric["id"], "data": "2026-11-24",
                                            "codice": prep["codice"], "righe": righe_lotto}, op, atteso=400)  # senza confezioni
        salvato = self.post("/prodotti/lotti/salva", {"prodotto_id": p["id"], "ricetta_id": ric["id"], "data": "2026-11-24",
                                                      "confezioni": [{"contenitore_id": busta_id, "pezzi": 40}],
                                                      "codice": prep["codice"], "scadenza": prep["scadenza"],
                                                      "righe": righe_lotto}, op)
        self.assertIn("Uova", salvato["avviso"])                       # uova senza lotto fornitore
        # secondo lotto lo stesso giorno: codice -2 e lotto della farina ripreso dall'ultimo
        prep2 = c.get(f"/prodotti/lotti/prepara?prodotto_id={p['id']}&data=2026-11-24").get_json()
        self.assertEqual(prep2["codice"], "L241126-TZU-2")
        self.assertEqual(prep2["righe"][0]["lotto_fornitore"], "MR-2611")
        self.assertTrue(prep2["righe"][0]["precompilato"])
        self.post("/prodotti/lotti/salva", {"prodotto_id": p["id"], "data": "2026-11-24", "codice": "L241126-TZU",
                                            "confezioni": [{"contenitore_id": busta_id, "pezzi": 1}],
                                            "righe": righe_lotto}, op, atteso=400)     # codice doppio

        # correzione del lotto: 38 buste da 500 g e 6 da 250 g (contenitore non della ricetta: si può); lo storico la registra
        from app.moduli.prodotti.models import Lotto as _Lotto
        with self.app.app_context():
            conf_id = _Lotto.query.get(salvato["id"]).confezioni[0].id
        self.post("/prodotti/lotti/salva", {"id": salvato["id"], "prodotto_id": p["id"], "ricetta_id": ric["id"],
                                            "data": "2026-11-24", "codice": "L241126-TZU",
                                            "confezioni": [{"id": conf_id, "contenitore_id": busta_id, "pezzi": 38},
                                                           {"contenitore_id": busta250_id, "pezzi": 6}],
                                            "righe": righe_lotto[:2]}, op)
        pagina = c.get(f"/prodotti/lotti/{salvato['id']}").get_data(as_text=True)
        self.assertIn("Storico delle correzioni", pagina)
        self.assertIn("Laboratorio", pagina)
        self.assertIn("40 × Busta pasta 500 g", pagina)                   # nello storico: com'era prima
        with self.app.app_context():
            l_ = _Lotto.query.get(salvato["id"])
            self.assertEqual(l_.confezioni_testo, "38 × 500 g, 6 × 250 g")
            self.assertEqual((l_.pezzi_prodotti, l_.quantita_kg), (44, 20.5))   # 38 × 0,5 + 6 × 0,25 kg
            conf250_id = l_.confezioni[1].id

        # la ricetta ora è usata: cambiare solo i contenitori la lascia v1; cambiare le dosi crea la v2
        r1 = self.post("/prodotti/ricette/salva", {"id": ric["id"], "prodotto_id": p["id"], "resa_pezzi": "20", "resa_kg": "10",
                                                   "righe": righe, "contenitori": [{"contenitore_id": busta_id},
                                                                                   {"contenitore_id": busta250_id, "peso_netto": "240"}]}, op)
        self.assertEqual(r1["ricetta"]["versione"], 1)
        self.assertIn("Contenitori della v1", r1["messaggio"])
        self.assertEqual([x["peso_netto"] for x in r1["ricetta"]["contenitori"]], [None, 240])
        r2 = self.post("/prodotti/ricette/salva", {"id": ric["id"], "prodotto_id": p["id"], "resa_pezzi": "20", "righe": righe[:2]}, op)
        self.assertEqual(r2["ricetta"]["versione"], 2)
        self.assertIn("nuova versione", r2["messaggio"])

        # stato: il ritiro vuole il motivo
        self.post(f"/prodotti/lotti/{salvato['id']}/stato", {"stato": "ritirato"}, op, atteso=400)
        self.post(f"/prodotti/lotti/{salvato['id']}/stato", {"stato": "ritirato", "motivo": "richiamo farina"}, op)

        # etichette: anteprima, stampa archiviata, download; il consulente vede ma non stampa
        prova = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/prova", {"modalita": "unica"}, op)
        self.assertTrue(prova["immagini"][0]["src"].startswith("data:image/png;base64,"))
        self.assertEqual(prova["fogli"], 5)                        # 38 buste da 500 g, 8 per foglio (Grande, proposto)
        self.assertEqual(prova["formato_id"], 5)
        # la busta da 250 g ha solo il Grande: il Piccolo non è adatto e non si stampa
        self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"confezione_id": conf250_id, "formato_id": 7,
                                                                         "n_confezioni": 6}, op, atteso=400)
        prova250 = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/prova", {"confezione_id": conf250_id}, op)
        self.assertEqual((prova250["n_etichette"], prova250["formato_id"]), (6, 5))
        self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 10}, self.consulente_id, atteso=403)
        st = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 10, "formato_id": 7,
                                                                               "modalita": "fronte_retro"}, op)
        self.assertEqual((st["n_etichette"], st["fogli"]), (20, 1))     # Piccolo L7160: 21 per foglio
        pdf = c.get(st["url"])
        self.assertEqual(pdf.status_code, 200)
        self.assertTrue(pdf.data.startswith(b"%PDF"))
        from app import db
        from app.moduli.prodotti.models import StampaEtichetta
        with self.app.app_context():
            s = StampaEtichetta.query.one()
            self.assertEqual(_json.loads(s.dati)["etichetta"]["peso"], "500 g")     # peso dalla confezione
            self.assertEqual(s.confezione_testo, "Busta pasta 500 g")
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
        # stile classico (sfondo crema, Yeseva One): compare tra gli stili e ha il suo minimo di legge (6,8 pt)
        from app.moduli.prodotti.routes.etichette import parametri_stile, stili_disponibili
        self.assertEqual(stili_disponibili(), ["base-2026", "classico-giallo"])
        self.assertEqual(parametri_stile("classico-giallo")["altezza_x"], 0.5)
        self.assertEqual(parametri_stile("base-2026")["corpo_pt"], 6.8)
        classico = self.post("/prodotti/formati/5/prova", {"stile": "classico-giallo"}, op)
        self.assertTrue(classico["immagini"][0]["src"].startswith("data:image/png;base64,"))
        self.post("/prodotti/formati/impostazioni", {"stile": "classico-giallo", "piede": "www.cabianca.eu"})
        st2 = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 30, "formato_id": 5}, op)
        self.assertEqual(st2["fogli"], 4)                                # 30 etichette, 8 per foglio
        self.assertTrue(c.get(st2["url"]).data.startswith(b"%PDF"))
        self.post("/prodotti/formati/impostazioni", {"stile": "base-2026", "piede": "www.cabianca.eu"})

        # salumi: etichetta piegata sul cordino (fronte e retro sulla stessa etichetta del foglio Grande)
        pieg = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/prova", {"formato_id": 5, "modalita": "piegata",
                                                                              "n_confezioni": 10}, op)
        self.assertEqual([i["parte"] for i in pieg["immagini"]][:2], ["fronte", "retro"])
        self.assertEqual(len(pieg["immagini"]), 3)                       # + l'etichetta intera come si stampa
        self.assertEqual((pieg["n_etichette"], pieg["fogli"]), (10, 2))   # una etichetta per confezione
        st3 = self.post(f"/prodotti/lotti/{salvato['id']}/etichette/stampa", {"n_confezioni": 10, "formato_id": 5,
                                                                              "modalita": "piegata"}, op)
        self.assertEqual((st3["n_etichette"], st3["fogli"]), (10, 2))
        from io import BytesIO
        from pypdf import PdfReader
        pdf3 = PdfReader(BytesIO(c.get(st3["url"]).data))
        self.assertEqual(len(pdf3.pages), 2)
        self.assertAlmostEqual(float(pdf3.pages[0].mediabox.width), 595.28, places=1)   # A4

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
        self.assertIn("Elimina il lotto", self.client().get(f"/prodotti/lotti/{salvato['id']}").get_data(as_text=True))
        self.assertNotIn("Elimina il lotto", c.get(f"/prodotti/lotti/{salvato['id']}").get_data(as_text=True))

        self.assertIn("eliminaProdotto", self.client().get(f"/prodotti/catalogo/{p['id']}").get_data(as_text=True))
        self.assertNotIn("eliminaProdotto", c.get(f"/prodotti/catalogo/{p['id']}").get_data(as_text=True))
        # eliminare: solo l'admin. Un prodotto con lotti no; il lotto sì (con stampe e PDF), con il motivo
        self.post(f"/prodotti/catalogo/{p['id']}/elimina", {}, atteso=400)                  # ha lotti
        self.post(f"/prodotti/lotti/{salvato['id']}/elimina", {"motivo": "prova"}, op, atteso=403)
        self.post(f"/prodotti/lotti/{salvato['id']}/elimina", {}, atteso=400)               # manca il motivo
        from app.moduli.prodotti.models import Lotto, Prodotto, Ricetta, Storico
        with self.app.app_context():
            pdf_lotto = [os.path.join(self.cartella, "prodotti", "etichette", s.pdf_path)
                         for s in StampaEtichetta.query.filter_by(lotto_id=salvato["id"])]
        self.assertEqual(len(pdf_lotto), 3)
        self.post(f"/prodotti/lotti/{salvato['id']}/elimina", {"motivo": "lotto di prova"})
        self.assertFalse(any(os.path.exists(f) for f in pdf_lotto))
        with self.app.app_context():
            self.assertIsNone(db.session.get(Lotto, salvato["id"]))
            self.assertEqual(StampaEtichetta.query.filter_by(lotto_id=salvato["id"]).count(), 0)
            canc = Storico.query.filter_by(tabella="lotti", riga_id=salvato["id"], azione="cancellazione").one()
            self.assertIn("ELIMINATO: lotto di prova", canc.prima)
            self.assertEqual(Lotto.query.filter_by(prodotto_id=p["id"]).count(), 0)
        self.post(f"/prodotti/catalogo/{p['id']}/elimina", {}, op, atteso=403)
        self.assertEqual(self.post(f"/prodotti/catalogo/{p['id']}/elimina", {})["url"], "/prodotti/catalogo")
        with self.app.app_context():
            self.assertIsNone(db.session.get(Prodotto, p["id"]))
            self.assertEqual(Ricetta.query.filter_by(prodotto_id=p["id"]).count(), 0)


if __name__ == "__main__":
    unittest.main()
