"""Impostazioni di SQLite applicate a ogni nuova connessione (sito, servizi, impianto, moduli).

Registrato una volta sola da create_app() (app/__init__.py) con configura_sqlite().

Perché (dalla 3.3.3): sul database scrivono più processi insieme (sito, impianto, servizi).
- journal_mode=WAL: chi legge non blocca chi scrive e viceversa; le scritture sono più robuste a
  un'interruzione. È un'impostazione salvata nel file: basta darla una volta, ma ripeterla non costa.
  Conseguenza: accanto al .db compaiono i file -wal e -shm, e il database NON si copia più con un
  semplice cp: si usa app/services/backup_sqlite.copia_sqlite (o il backup del gestionale).
- busy_timeout=10000: se il database è occupato da un altro processo si aspetta fino a 10 secondi
  invece di fallire subito con "database is locked".
- foreign_keys=ON non viene attivato: il gestionale non è nato con i vincoli attivi e accenderli
  ora potrebbe bloccare cancellazioni che oggi funzionano.

Per tornare alla modalità di prima: `PRAGMA journal_mode=DELETE` sul file (a sito fermo).
"""
import sqlite3

from sqlalchemy import event
from sqlalchemy.engine import Engine

_registrato = False


def configura_sqlite():
    """Aggancia _imposta_connessione a tutte le connessioni SQLAlchemy (idempotente)."""
    global _registrato
    if _registrato:
        return
    event.listen(Engine, "connect", _imposta_connessione)
    _registrato = True


def _imposta_connessione(dbapi_connection, _record):
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return                      # altri database (mai usati oggi): non toccare
    cur = dbapi_connection.cursor()
    try:
        cur.execute("PRAGMA busy_timeout=10000")
        cur.execute("PRAGMA journal_mode=WAL")
    finally:
        cur.close()
