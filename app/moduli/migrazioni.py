"""Migrazioni con numero di versione per i database dei moduli (dalla 3.4.0). Senza Flask, testabile.

Ogni modulo elenca le sue migrazioni nel proprio schema.py:

    MIGRAZIONI = [
        (1, "tabelle iniziali", ["CREATE TABLE ...", "CREATE TRIGGER ... END"]),
        (2, "colonna note sui lotti", ["ALTER TABLE lotti ADD COLUMN note TEXT"]),
    ]

e nella sua migra(app) chiama applica(...). Regole (README, sezione "Moduli"):
- le migrazioni AGGIUNGONO soltanto (niente DROP, niente RENAME): così tornare al codice
  precedente è sicuro senza ripristinare i dati;
- una migrazione già rilasciata non si modifica mai: si aggiunge la successiva;
- ogni istruzione SQL è un elemento separato della lista (niente executescript, che farebbe
  COMMIT da solo e romperebbe la transazione unica).

Come funziona applica():
1. tabella schema_versione (una riga per migrazione applicata);
2. BEGIN IMMEDIATE: un solo processo alla volta può migrare (gli altri aspettano);
3. se il database è PIÙ NUOVO del codice → DatabasePiuNuovo (il modulo non parte: succede dopo un
   ritorno all'immagine precedente con migrazioni nuove già applicate);
4. se ci sono migrazioni da fare e il database ha già dati, prima una copia di sicurezza
   backups/<modulo>_pre_v<N>_<data>.db;
5. tutte le migrazioni mancanti in UNA transazione: o tutte o nessuna.
"""
import os
import sqlite3
from datetime import datetime


class DatabasePiuNuovo(RuntimeError):
    """Il database ha migrazioni che questo codice non conosce: non si avvia per non rovinarlo."""


def versione_attuale(percorso_db):
    """Versione dello schema (0 se il database o la tabella non esistono). Solo lettura."""
    if not os.path.exists(percorso_db):
        return 0
    con = sqlite3.connect(f"file:{percorso_db}?mode=ro", uri=True, timeout=30)
    try:
        r = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_versione'").fetchone()
        if not r:
            return 0
        return con.execute("SELECT COALESCE(MAX(versione), 0) FROM schema_versione").fetchone()[0]
    finally:
        con.close()


def applica(percorso_db, migrazioni, nome_modulo, cartella_backup, versione_modulo="", copia=None):
    """Porta il database alla versione più alta di `migrazioni`. Restituisce (prima, dopo, copia_o_None).

    `copia(sorgente, destinazione) -> "ok"` fa la copia di sicurezza (default: backup_sqlite.copia_sqlite).
    """
    numeri = [m[0] for m in migrazioni]
    if numeri != sorted(set(numeri)) or (numeri and numeri[0] < 1):
        raise ValueError(f"{nome_modulo}: le migrazioni devono avere numeri crescenti, unici, da 1 in su")
    massima = numeri[-1] if numeri else 0

    os.makedirs(os.path.dirname(percorso_db) or ".", exist_ok=True)
    esisteva = os.path.exists(percorso_db) and os.path.getsize(percorso_db) > 0
    con = sqlite3.connect(percorso_db, timeout=30, isolation_level=None)   # transazioni a mano
    copia_fatta = None
    try:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=FULL")      # registro di legge: niente scorciatoie sulla durabilità
        con.execute("BEGIN IMMEDIATE")
        con.execute("CREATE TABLE IF NOT EXISTS schema_versione ("
                    "versione INTEGER PRIMARY KEY, descrizione TEXT, applicata_il TEXT NOT NULL, "
                    "versione_modulo TEXT)")
        prima = con.execute("SELECT COALESCE(MAX(versione), 0) FROM schema_versione").fetchone()[0]
        if prima > massima:
            con.execute("ROLLBACK")
            raise DatabasePiuNuovo(
                f"il database di {nome_modulo} è alla versione {prima}, questo codice arriva alla {massima}: "
                f"riportare il codice alla versione giusta o ripristinare backups/{nome_modulo}_pre_v*.db")
        da_fare = [m for m in migrazioni if m[0] > prima]
        if not da_fare:
            con.execute("COMMIT")
            return prima, prima, None

        if esisteva and prima > 0:
            # copia mentre teniamo il lock: nessuno scrive fra la copia e la migrazione
            if copia is None:
                from app.services.backup_sqlite import copia_sqlite as copia
            os.makedirs(cartella_backup, exist_ok=True)
            copia_fatta = os.path.join(
                cartella_backup, f"{nome_modulo}_pre_v{da_fare[0][0]}_{datetime.now():%Y%m%d_%H%M%S}.db")
            esito = copia(percorso_db, copia_fatta)
            if esito != "ok":
                con.execute("ROLLBACK")
                raise RuntimeError(f"{nome_modulo}: copia prima della migrazione non riuscita ({esito})")

        try:
            for numero, descrizione, istruzioni in da_fare:
                if callable(istruzioni):
                    istruzioni(con)
                else:
                    for sql in istruzioni:
                        con.execute(sql)
                con.execute("INSERT INTO schema_versione (versione, descrizione, applicata_il, versione_modulo) "
                            "VALUES (?, ?, ?, ?)",
                            (numero, descrizione, datetime.now().isoformat(timespec="seconds"), versione_modulo))
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
        return prima, da_fare[-1][0], copia_fatta
    finally:
        con.close()
