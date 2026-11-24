"""Schema del database data/prodotti.db: elenco ordinato delle migrazioni del modulo Prodotti.

Le applica app/moduli/migrazioni.py (leggere lì le regole). In breve:
- una migrazione già rilasciata NON si modifica: se serve un cambiamento si aggiunge la successiva;
- solo aggiunte (CREATE TABLE, ADD COLUMN, CREATE INDEX/TRIGGER), mai DROP o RENAME;
- un'istruzione SQL per elemento della lista.

I modelli SQLAlchemy in models.py devono rispecchiare queste tabelle: le tabelle le crea questo file,
NON db.create_all().
"""

MIGRAZIONI = [
    (1, "impostazioni del modulo", [
        # chiave/valore: stile attivo delle etichette, dati del produttore predefiniti, ...
        "CREATE TABLE impostazioni (chiave TEXT PRIMARY KEY, valore TEXT)",
    ]),
]
