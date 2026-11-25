"""Schema del database data/prodotti.db: elenco ordinato delle migrazioni del modulo Prodotti.

Le applica app/moduli/migrazioni.py (leggere lì le regole). In breve:
- una migrazione già rilasciata NON si modifica: se serve un cambiamento si aggiunge la successiva;
- solo aggiunte (CREATE TABLE, ADD COLUMN, CREATE INDEX/TRIGGER), mai DROP o RENAME;
- un'istruzione SQL per elemento della lista.

I modelli SQLAlchemy in models.py devono rispecchiare queste tabelle: le tabelle le crea questo file,
NON db.create_all().

Il registro di legge (libro lotti) è protetto dal database stesso, non solo dal codice:
- i lotti e le stampe delle etichette NON si possono cancellare (trigger *_no_delete);
- ogni modifica o cancellazione di lotti e ingredienti dei lotti finisce in `storico` con i valori di
  PRIMA e chi l'ha fatta (colonna modificato_da, scritta dall'applicazione): si può correggere un errore
  di battitura, ma resta la traccia;
- una ricetta già usata in un lotto non cambia più (le righe e i dati principali sono bloccati):
  si crea una nuova versione. Così ogni lotto resta legato alla ricetta esatta con cui è stato fatto.

Date: testo ISO (AAAA-MM-GG, o AAAA-MM-GGTHH:MM:SS per gli istanti). Booleani: 0/1.
Liste (allergeni): JSON, es. '["glutine","uova"]' con i codici di services/allergeni.py.
"""

# Produttore predefinito sulle etichette (modificabile in Impostazioni del modulo e per prodotto)
PRODUTTORE = ("Fattoria Ca' Bianca Società Agricola S.S. – Via Costa S. Caterina 1, Ossalengo, "
              "26022 Castelverde (CR), Italia")


def _storico(tabella, colonne):
    """Trigger che copiano in `storico` la riga com'era prima di una modifica o cancellazione."""
    oggetto = ", ".join(f"'{c}', OLD.{c}" for c in colonne)
    return [
        f"CREATE TRIGGER {tabella}_storico_update AFTER UPDATE ON {tabella} BEGIN "
        f"INSERT INTO storico (tabella, riga_id, azione, prima, chi, quando) VALUES "
        f"('{tabella}', OLD.id, 'modifica', json_object({oggetto}), NEW.modificato_da, "
        f"strftime('%Y-%m-%dT%H:%M:%S','now','localtime')); END",
        f"CREATE TRIGGER {tabella}_storico_delete AFTER DELETE ON {tabella} BEGIN "
        f"INSERT INTO storico (tabella, riga_id, azione, prima, chi, quando) VALUES "
        f"('{tabella}', OLD.id, 'cancellazione', json_object({oggetto}), OLD.modificato_da, "
        f"strftime('%Y-%m-%dT%H:%M:%S','now','localtime')); END",
    ]


_COLONNE_LOTTI = ["codice", "prodotto_id", "ricetta_id", "data_produzione", "data_scadenza", "pezzi_prodotti",
                  "quantita_kg", "ingredienti_testo", "allergeni", "dati_etichetta", "note", "stato",
                  "stato_motivo", "modificato_da", "modificato_il"]
_COLONNE_LOTTI_ING = ["lotto_id", "materia_prima_id", "nome", "quantita", "unita", "fornitore_id",
                      "fornitore_nome", "lotto_fornitore", "rif_documento", "produzione_propria", "ordine",
                      "modificato_da"]

_RICETTA_USATA = "EXISTS (SELECT 1 FROM lotti WHERE ricetta_id = {})"
_MSG_RICETTA = "'Ricetta già usata in un lotto: crearne una nuova versione'"

MIGRAZIONI = [
    (1, "impostazioni del modulo", [
        # chiave/valore: stile attivo delle etichette, dati del produttore predefiniti, ...
        "CREATE TABLE impostazioni (chiave TEXT PRIMARY KEY, valore TEXT)",
    ]),

    (2, "ricettario, libro lotti, etichette", [
        # --- storico delle modifiche al registro (scritto solo dai trigger) ---
        "CREATE TABLE storico ("
        " id INTEGER PRIMARY KEY, tabella TEXT NOT NULL, riga_id INTEGER NOT NULL, azione TEXT NOT NULL,"
        " prima TEXT NOT NULL, chi TEXT, quando TEXT NOT NULL)",
        "CREATE INDEX ix_storico_riga ON storico (tabella, riga_id)",
        "CREATE TRIGGER storico_no_update BEFORE UPDATE ON storico "
        "BEGIN SELECT RAISE(ABORT, 'Lo storico non si modifica'); END",
        "CREATE TRIGGER storico_no_delete BEFORE DELETE ON storico "
        "BEGIN SELECT RAISE(ABORT, 'Lo storico non si cancella'); END",

        # --- materie prime (ingredienti, anche di produzione propria) ---
        "CREATE TABLE materie_prime ("
        " id INTEGER PRIMARY KEY,"
        " nome TEXT NOT NULL UNIQUE,"                 # nome interno, es. 'Farina 00'
        " nome_etichetta TEXT NOT NULL,"              # come compare in etichetta, es. 'farina di GRANO tenero tipo 00'
        " allergeni TEXT NOT NULL DEFAULT '[]',"      # codici UE (services/allergeni.py)
        " composta TEXT,"                             # sotto-ingredienti tra parentesi, es. 'frutta, zucchero, essenza di SENAPE'
        " unita TEXT NOT NULL DEFAULT 'g',"           # unità usata nelle ricette: g, ml, pz
        " fornitore_id INTEGER,"                      # Contact (fornitore) in gestionale.db
        " fornitore_nome TEXT,"                       # copia del nome: i due database sono file separati
        " produzione_propria INTEGER NOT NULL DEFAULT 0,"
        " note TEXT,"
        " attiva INTEGER NOT NULL DEFAULT 1,"
        " creato_il TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')))",

        # --- formati dei fogli A4 pretagliati ---
        "CREATE TABLE formati_etichetta ("
        " id INTEGER PRIMARY KEY, nome TEXT NOT NULL UNIQUE, uso TEXT, codice_foglio TEXT,"
        " larghezza_mm REAL NOT NULL, altezza_mm REAL NOT NULL, colonne INTEGER NOT NULL, righe INTEGER NOT NULL,"
        " margine_sup_mm REAL NOT NULL DEFAULT 0, margine_sx_mm REAL NOT NULL DEFAULT 0,"
        " passo_orizz_mm REAL, passo_vert_mm REAL,"          # distanza fra gli inizi di due etichette (vuoto = misura)
        " offset_x_mm REAL NOT NULL DEFAULT 0, offset_y_mm REAL NOT NULL DEFAULT 0,"   # calibrazione stampante
        " layout TEXT NOT NULL DEFAULT 'orizzontale',"       # orizzontale | compatto
        " attivo INTEGER NOT NULL DEFAULT 1)",
        # fogli A4 210×297 senza margini laterali; misure dei codici di riferimento (da verificare all'acquisto)
        "INSERT INTO formati_etichetta (nome, uso, codice_foglio, larghezza_mm, altezza_mm, colonne, righe,"
        " margine_sup_mm, margine_sx_mm, layout) VALUES"
        " ('Grande', 'vasetti 250–314 ml, passata 750 ml, buste pasta 500 g, farine', 'Avery 3427', 105, 74, 2, 4, 0.5, 0, 'orizzontale'),"
        " ('Medio', 'vasetti 150–156 ml', 'Avery 3653', 105, 42.3, 2, 7, 0.45, 0, 'orizzontale'),"
        " ('Piccolo', 'vasetti 100–106 ml, sacchettini', 'Avery 3474', 70, 37, 3, 8, 0.5, 0, 'compatto'),"
        " ('Salumi', 'salami, pancetta, cotechini', 'Avery 3652', 70, 42.3, 3, 7, 0.45, 0, 'compatto')",

        # --- prodotti (catalogo) ---
        "CREATE TABLE prodotti ("
        " id INTEGER PRIMARY KEY,"
        " nome TEXT NOT NULL,"                        # es. 'Tortelli di zucca'
        " sottotitolo TEXT,"                          # denominazione di vendita, es. 'Pasta artigianale ripiena all''uovo – prodotto congelato'
        " sigla TEXT NOT NULL,"                       # per il codice lotto, es. 'ZUC' → L241126-ZUC
        " categoria TEXT,"
        " peso_netto REAL, unita TEXT NOT NULL DEFAULT 'g',"    # g | ml
        " formato_etichetta_id INTEGER REFERENCES formati_etichetta(id),"
        " tipo_scadenza TEXT NOT NULL DEFAULT 'tmc',"           # tmc = 'da consumarsi preferibilmente entro' | scadenza = 'da consumarsi entro'
        " durata_giorni INTEGER,"                     # scadenza proposta = data produzione + durata
        " conservazione TEXT, modalita_uso TEXT,"
        " tracce TEXT,"                               # 'Può contenere tracce di …'
        f" prodotto_da TEXT NOT NULL DEFAULT '{PRODUTTORE.replace(chr(39), chr(39) * 2)}',"
        " lavorato_da TEXT,"                          # es. laboratorio con bollo CE per i salumi
        " dichiarazioni_extra TEXT,"                  # es. 'Frutta utilizzata: 60 g per 100 g' (confetture)
        " nutrizionale TEXT,"                         # JSON facoltativo
        " ricetta_default_id INTEGER,"
        " attivo INTEGER NOT NULL DEFAULT 1,"
        " da_verificare INTEGER NOT NULL DEFAULT 0,"  # importato dalle etichette vecchie: da ricontrollare
        " note TEXT,"
        " creato_il TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),"
        " modificato_il TEXT)",

        # --- ricettario (con versioni) ---
        "CREATE TABLE ricette ("
        " id INTEGER PRIMARY KEY,"
        " prodotto_id INTEGER NOT NULL REFERENCES prodotti(id),"
        " versione INTEGER NOT NULL,"
        " nome TEXT,"                                 # facoltativo, es. 'con meno zucchero'
        " resa_pezzi INTEGER, resa_kg REAL,"          # quanto rende una produzione di questa ricetta
        " procedimento TEXT, note_haccp TEXT,"        # cottura, pastorizzazione, temperature, punti critici
        " attiva INTEGER NOT NULL DEFAULT 1,"
        " creato_da TEXT,"
        " creato_il TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),"
        " UNIQUE (prodotto_id, versione))",
        "CREATE TABLE ricette_righe ("
        " id INTEGER PRIMARY KEY,"
        " ricetta_id INTEGER NOT NULL REFERENCES ricette(id),"
        " materia_prima_id INTEGER NOT NULL REFERENCES materie_prime(id),"
        " quantita REAL NOT NULL, unita TEXT NOT NULL DEFAULT 'g',"
        " ordine INTEGER NOT NULL DEFAULT 0, nota TEXT)",
        "CREATE INDEX ix_ricette_righe_ricetta ON ricette_righe (ricetta_id)",

        # --- libro lotti ---
        "CREATE TABLE lotti ("
        " id INTEGER PRIMARY KEY,"
        " codice TEXT NOT NULL UNIQUE,"               # es. L241126-ZUC
        " prodotto_id INTEGER NOT NULL REFERENCES prodotti(id),"
        " ricetta_id INTEGER REFERENCES ricette(id),"
        " data_produzione TEXT NOT NULL, data_scadenza TEXT,"
        " pezzi_prodotti INTEGER, quantita_kg REAL,"
        " ingredienti_testo TEXT,"                    # testo stampato in etichetta (con **grassetto** sugli allergeni)
        " allergeni TEXT NOT NULL DEFAULT '[]',"
        " dati_etichetta TEXT,"                       # JSON: copia dei dati del prodotto al momento del lotto
        " note TEXT,"
        " stato TEXT NOT NULL DEFAULT 'attivo' CHECK (stato IN ('attivo','esaurito','ritirato','annullato')),"
        " stato_motivo TEXT,"
        " creato_da TEXT,"
        " creato_il TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),"
        " modificato_da TEXT, modificato_il TEXT)",
        "CREATE INDEX ix_lotti_prodotto ON lotti (prodotto_id, data_produzione)",
        "CREATE INDEX ix_lotti_data ON lotti (data_produzione)",
        "CREATE TRIGGER lotti_no_delete BEFORE DELETE ON lotti "
        "BEGIN SELECT RAISE(ABORT, 'Il libro lotti non si cancella: annullare il lotto'); END",

        "CREATE TABLE lotti_ingredienti ("
        " id INTEGER PRIMARY KEY,"
        " lotto_id INTEGER NOT NULL REFERENCES lotti(id),"
        " materia_prima_id INTEGER REFERENCES materie_prime(id),"
        " nome TEXT NOT NULL,"                        # copia del nome della materia prima
        " quantita REAL, unita TEXT,"
        " fornitore_id INTEGER, fornitore_nome TEXT,"
        " lotto_fornitore TEXT,"                      # lotto scritto sulla confezione / DDT del fornitore
        " rif_documento TEXT,"                        # DDT o fattura di acquisto
        " produzione_propria INTEGER NOT NULL DEFAULT 0,"
        " ordine INTEGER NOT NULL DEFAULT 0,"
        " modificato_da TEXT)",
        "CREATE INDEX ix_lotti_ing_lotto ON lotti_ingredienti (lotto_id)",
        # ricerca per i richiami: "in quali lotti è finito il lotto X dello zucchero?"
        "CREATE INDEX ix_lotti_ing_richiamo ON lotti_ingredienti (materia_prima_id, lotto_fornitore)",

        # --- archivio delle etichette stampate ---
        "CREATE TABLE stampe_etichette ("
        " id INTEGER PRIMARY KEY,"
        " lotto_id INTEGER NOT NULL REFERENCES lotti(id),"
        " formato_id INTEGER REFERENCES formati_etichetta(id),"
        " stile TEXT NOT NULL,"                       # cartella dello stile con versione, es. 'base-2026'
        " n_etichette INTEGER NOT NULL,"
        " pdf_path TEXT NOT NULL,"                    # relativo a data/prodotti/etichette
        " sha256 TEXT NOT NULL,"
        " dati TEXT NOT NULL,"                        # JSON dei dati stampati: il PDF si può rigenerare identico
        " creato_da TEXT,"
        " creato_il TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')))",
        "CREATE INDEX ix_stampe_lotto ON stampe_etichette (lotto_id)",
        "CREATE TRIGGER stampe_no_delete BEFORE DELETE ON stampe_etichette "
        "BEGIN SELECT RAISE(ABORT, 'Le etichette stampate restano in archivio'); END",
        "CREATE TRIGGER stampe_no_update BEFORE UPDATE ON stampe_etichette "
        "BEGIN SELECT RAISE(ABORT, 'Le etichette stampate non si modificano'); END",

        # --- ricette usate in un lotto: bloccate ---
        "CREATE TRIGGER ricette_righe_bloccate_update BEFORE UPDATE ON ricette_righe "
        f"WHEN {_RICETTA_USATA.format('OLD.ricetta_id')} BEGIN SELECT RAISE(ABORT, {_MSG_RICETTA}); END",
        "CREATE TRIGGER ricette_righe_bloccate_delete BEFORE DELETE ON ricette_righe "
        f"WHEN {_RICETTA_USATA.format('OLD.ricetta_id')} BEGIN SELECT RAISE(ABORT, {_MSG_RICETTA}); END",
        "CREATE TRIGGER ricette_righe_bloccate_insert BEFORE INSERT ON ricette_righe "
        f"WHEN {_RICETTA_USATA.format('NEW.ricetta_id')} BEGIN SELECT RAISE(ABORT, {_MSG_RICETTA}); END",
        "CREATE TRIGGER ricette_bloccate BEFORE UPDATE OF prodotto_id, versione, resa_pezzi, resa_kg, procedimento, "
        f"note_haccp ON ricette WHEN {_RICETTA_USATA.format('OLD.id')} BEGIN SELECT RAISE(ABORT, {_MSG_RICETTA}); END",
        "CREATE TRIGGER ricette_no_delete_usate BEFORE DELETE ON ricette "
        f"WHEN {_RICETTA_USATA.format('OLD.id')} BEGIN SELECT RAISE(ABORT, {_MSG_RICETTA}); END",

        "INSERT INTO impostazioni (chiave, valore) VALUES ('stile_etichette', 'base-2026')",
        f"INSERT INTO impostazioni (chiave, valore) VALUES ('produttore', '{PRODUTTORE.replace(chr(39), chr(39) * 2)}')",
    ]
    + _storico("lotti", _COLONNE_LOTTI)
    + _storico("lotti_ingredienti", _COLONNE_LOTTI_ING)),
]
