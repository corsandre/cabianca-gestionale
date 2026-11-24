"""Test di app/services/backup_sqlite.py: copia coerente in WAL, scelta dei backup da tenere, archivio."""
import importlib.util
import os
import sqlite3
import tarfile
import tempfile
import unittest
from datetime import datetime

_spec = importlib.util.spec_from_file_location(
    "backup_sqlite", os.path.join(os.path.dirname(__file__), "..", "app", "services", "backup_sqlite.py"))
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)


class TestCopiaSqlite(unittest.TestCase):
    def test_copia_include_le_scritture_ancora_nel_wal(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "gestionale.db")
            con = sqlite3.connect(src)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA wal_autocheckpoint=0")     # le righe restano nel -wal
            con.execute("CREATE TABLE t (x)")
            con.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100)])
            con.commit()
            self.assertTrue(os.path.getsize(src + "-wal") > 0)
            dst = os.path.join(d, "copia.db")
            self.assertEqual(bs.copia_sqlite(src, dst), "ok")
            con.close()
            copia = sqlite3.connect(dst)
            self.assertEqual(copia.execute("SELECT count(*) FROM t").fetchone()[0], 100)
            self.assertEqual(copia.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            copia.close()
            self.assertFalse(os.path.exists(dst + ".tmp"))

    def test_ripristino_con_wal_aperto_da_altri(self):
        """Un altro processo ha scritture nel -wal: il ripristino deve vincere e il DB restare integro."""
        with tempfile.TemporaryDirectory() as d:
            attivo, bk, prima = (os.path.join(d, n) for n in ("g.db", "bk.db", "prima.db"))
            con = sqlite3.connect(attivo)
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE t (x)")
            con.execute("INSERT INTO t VALUES ('vecchio')")
            con.commit()
            self.assertEqual(bs.copia_sqlite(attivo, bk), "ok")
            altro = sqlite3.connect(attivo)                 # es. il container servizi
            altro.execute("PRAGMA wal_autocheckpoint=0")
            altro.execute("INSERT INTO t VALUES ('scritto dopo il backup')")
            altro.commit()
            self.assertEqual(bs.ripristina_sqlite(bk, attivo, copia_prima=prima), "ok")
            self.assertEqual(altro.execute("SELECT x FROM t").fetchall(), [("vecchio",)])
            self.assertEqual(altro.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            altro.close()
            con.close()
            nuovo = sqlite3.connect(attivo)
            self.assertEqual(nuovo.execute("SELECT count(*) FROM t").fetchone()[0], 1)
            nuovo.close()
            salvato = sqlite3.connect(prima)                # lo stato prima del ripristino è conservato
            self.assertEqual(salvato.execute("SELECT count(*) FROM t").fetchone()[0], 2)
            salvato.close()

    def test_ripristino_rifiuta_backup_rovinato(self):
        with tempfile.TemporaryDirectory() as d:
            attivo, bk = os.path.join(d, "g.db"), os.path.join(d, "bk.db")
            sqlite3.connect(attivo).execute("CREATE TABLE t (x)").connection.commit()
            with open(bk, "wb") as f:
                f.write(b"SQLite format 3\x00" + b"\x00" * 200)
            self.assertNotEqual(bs.ripristina_sqlite(bk, attivo), "ok")
            self.assertEqual(sqlite3.connect(attivo).execute("SELECT count(*) FROM t").fetchone()[0], 0)

    def test_database_da_salvare_esclude_prove(self):
        with tempfile.TemporaryDirectory() as d:
            for f in ("gestionale.db", "prodotti.db", "_test.db", "gestionale.db-wal", "note.txt"):
                open(os.path.join(d, f), "w").close()
            nomi = [os.path.basename(p) for p in bs.database_da_salvare(d)]
            self.assertEqual(nomi, ["gestionale.db", "prodotti.db"])
            self.assertEqual(bs.database_da_salvare(os.path.join(d, "manca")), [])


class TestBackupDaEliminare(unittest.TestCase):
    def test_tiene_ultimi_7_e_primo_di_ogni_mese(self):
        # un backup al giorno dal 1/1/2026 al 24/11/2026
        nomi, giorno = [], datetime(2026, 1, 1)
        from datetime import timedelta
        while giorno <= datetime(2026, 11, 24):
            nomi.append(f"gestionale_backup_{giorno.strftime('%Y%m%d')}_020000.db")
            giorno += timedelta(days=1)
        via = set(bs.backup_da_eliminare(nomi))
        tenuti = sorted(set(nomi) - via)
        # 7 giornalieri (18-24/11) + primo di ognuno degli 11 mesi (gennaio-novembre)
        self.assertEqual(len(tenuti), 7 + 11)
        self.assertIn("gestionale_backup_20260101_020000.db", tenuti)
        self.assertIn("gestionale_backup_20261101_020000.db", tenuti)
        self.assertIn("gestionale_backup_20261124_020000.db", tenuti)
        self.assertNotIn("gestionale_backup_20261117_020000.db", tenuti)

    def test_oltre_12_mesi_si_cancella(self):
        nomi = [f"prodotti_backup_{a}{m:02d}01_020000.db" for a in (2025, 2026) for m in range(1, 13)]
        via = bs.backup_da_eliminare(nomi, giornalieri=1, mensili=12)
        self.assertEqual(len(via), 12)
        self.assertTrue(all("2025" in n for n in via))

    def test_nomi_sconosciuti_mai_toccati(self):
        self.assertEqual(bs.backup_da_eliminare(["gestionale.db.pre-deploy", "x.db"]), [])


class TestArchivio(unittest.TestCase):
    def test_archivia_cartella(self):
        with tempfile.TemporaryDirectory() as d:
            cart = os.path.join(d, "etichette")
            self.assertIsNone(bs.archivia_cartella(cart, os.path.join(d, "a.tar.gz")))
            os.makedirs(os.path.join(cart, "2026"))
            with open(os.path.join(cart, "2026", "L241126-ZUC.pdf"), "w") as f:
                f.write("pdf")
            out = bs.archivia_cartella(cart, os.path.join(d, "a.tar.gz"))
            with tarfile.open(out) as tar:
                self.assertIn("etichette/2026/L241126-ZUC.pdf", tar.getnames())

    def test_nome_backup(self):
        self.assertEqual(bs.nome_backup("/app/data/prodotti.db", datetime(2026, 11, 24, 2, 0, 5)),
                         "prodotti_backup_20261124_020005.db")


if __name__ == "__main__":
    unittest.main()
