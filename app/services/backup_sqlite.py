"""Copia sicura dei database SQLite e scelta dei backup da tenere (senza Flask, testabile).

Usato da app/services/backup.py (backup notturno) e da scripts/deploy.sh (copia prima del deploy).

Perché non basta copiare il file: dalla 3.3.3 i database sono in modalità WAL (vedi
app/utils/sqlite.py) e le ultime scritture possono stare ancora nel file `-wal` accanto al `.db`.
Un `cp`/`shutil.copy2` del solo `.db` darebbe una copia vecchia o incoerente. L'API di backup di
sqlite3 invece legge il database come lo vede una connessione, WAL compreso, anche mentre gli
altri processi (sito, servizi, impianto) ci scrivono.
"""
import os
import re
import sqlite3
import tarfile
from datetime import datetime


def copia_sqlite(sorgente, destinazione):
    """Copia coerente di un database SQLite in uso. Restituisce l'esito di PRAGMA integrity_check.

    La copia viene scritta in un file temporaneo e rinominata solo se è integra: un backup
    a metà non deve mai sembrare un backup buono.
    """
    tmp = destinazione + ".tmp"
    if os.path.exists(tmp):
        os.remove(tmp)
    src = sqlite3.connect(f"file:{sorgente}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        # la copia resta un file unico, senza -wal accanto: comoda da spedire e da ripristinare
        dst.execute("PRAGMA journal_mode=DELETE")
        esito = dst.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        dst.close()
        src.close()
    if esito != "ok":
        os.remove(tmp)
        return esito
    os.replace(tmp, destinazione)
    return esito


def database_da_salvare(cartella_dati):
    """Tutti i database del gestionale in data/: gestionale.db, prodotti.db e i futuri moduli.

    Esclusi i file di prova (che iniziano con "_", es. _test.db) e le copie lasciate dal deploy.
    """
    if not os.path.isdir(cartella_dati):
        return []
    return sorted(
        os.path.join(cartella_dati, f) for f in os.listdir(cartella_dati)
        if f.endswith(".db") and not f.startswith(("_", "."))
    )


_DATA_NEL_NOME = re.compile(r"_backup_(\d{8})_(\d{6})\.(db|tar\.gz)$")


def backup_da_eliminare(nomi, giornalieri=7, mensili=12):
    """Dato l'elenco dei file di backup di UN database (stesso prefisso), dice quali cancellare.

    Si tengono:
    - gli ultimi `giornalieri` backup;
    - il primo backup di ciascuno degli ultimi `mensili` mesi (memoria lunga: il libro lotti
      è un registro di legge, un errore scoperto dopo settimane deve potersi recuperare).
    I file con un nome che non riconosce non vengono mai toccati.
    """
    datati = []
    for nome in nomi:
        m = _DATA_NEL_NOME.search(nome)
        if m:
            datati.append((m.group(1) + m.group(2), nome))
    datati.sort(reverse=True)                       # dal più recente
    tenere = {nome for _, nome in datati[:giornalieri]}

    primo_del_mese = {}
    for stamp, nome in sorted(datati):              # dal più vecchio: il primo visto è il primo del mese
        primo_del_mese.setdefault(stamp[:6], nome)
    for mese in sorted(primo_del_mese, reverse=True)[:mensili]:
        tenere.add(primo_del_mese[mese])

    return sorted(nome for _, nome in datati if nome not in tenere)


def archivia_cartella(cartella, destinazione):
    """Archivio .tar.gz di una cartella (es. i PDF delle etichette). Restituisce il percorso o None."""
    if not os.path.isdir(cartella) or not os.listdir(cartella):
        return None
    with tarfile.open(destinazione, "w:gz") as tar:
        tar.add(cartella, arcname=os.path.basename(cartella.rstrip("/")))
    return destinazione


def nome_backup(percorso_db, quando=None):
    """gestionale.db → gestionale_backup_20261124_020000.db (stesso schema di nomi di prima)."""
    quando = quando or datetime.now()
    base = os.path.splitext(os.path.basename(percorso_db))[0]
    return f"{base}_backup_{quando.strftime('%Y%m%d_%H%M%S')}.db"
