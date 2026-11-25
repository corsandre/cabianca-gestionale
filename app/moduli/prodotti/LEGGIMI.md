# Modulo Prodotti – mappa

Ricettario, libro dei lotti ed etichette dei prodotti trasformati di Fattoria Ca' Bianca
(marmellate, mostarde, conserve, pasta ripiena, salumi…). Serve anche come registro per i controlli
NAS/ATS: tracciabilità "un passo indietro" (fornitore e lotto di ogni ingrediente, Reg. CE 178/2002)
ed etichette secondo il Reg. UE 1169/2011.

- Come si usa: README, sezione «Prodotti (modulo)».
- Regole dei moduli (ruoli, database, deploy): README, «Moduli e ruoli dei processi».
- Piano, decisioni e stato dei lavori: `docs/piano-prodotti.md`.

## File

| File | A cosa serve |
|---|---|
| `__init__.py` | interfaccia verso il nucleo: `NOME`, `VERSIONE`, `DATABASE`, `migra`, `registra`, `stato` |
| `schema.py` | migrazioni numerate di `data/prodotti.db` e trigger che proteggono il registro (mai modificare quelle rilasciate) |
| `models.py` | modelli SQLAlchemy (bind `prodotti`) che rispecchiano le tabelle di `schema.py` |
| **routes/** | pagine `/prodotti/...`; login + sezione "prodotti" obbligatori per tutte (`__init__.py`) |
| `routes/comune.py` | aiuti: utente, fornitori (Contact del nucleo, anche creati al volo), numeri con la virgola, JSON |
| `routes/panoramica.py` | pagina iniziale |
| `routes/catalogo.py` | materie prime e prodotti (catalogo, scheda prodotto) |
| `routes/ricette.py` | ricettario, editor con versioni, anteprima dell'elenco ingredienti |
| `routes/lotti.py` | libro lotti, finestra «Nuovo lotto» (`prepara`, `salva`), scheda lotto, stati |
| `routes/etichette.py` | anteprima e stampa archiviata delle etichette, formati, calibrazione, stile attivo |
| `routes/esporta.py` | libro lotti e ricettario in PDF ed Excel |
| `routes/richiamo.py` | ricerca dei lotti che contengono un lotto di materia prima; ritiro in blocco |
| **services/** | logica pura senza Flask, testata in `tests/test_prodotti_*.py` |
| `services/allergeni.py` | i 14 allergeni UE |
| `services/ingredienti.py` | elenco ingredienti di legge (peso decrescente, grassetto sugli allergeni) |
| `services/lotti.py` | codice lotto, sigla, scadenza, quantità scalate |
| `services/etichette.py` | posizioni sul foglio, adattamento del testo, minimo di legge, PDF/PNG con WeasyPrint |
| **templates/prodotti/** | `_base.html` (CSS/JS del modulo), `_menu.html` (incluso dal menu del nucleo), pagine e finestre `_modale_*.html` |
| `templates/prodotti/etichette/stili/<stile>/` | stili delle etichette (oggi `base-2026`, vedi il suo LEGGIMI) |
| `templates/prodotti/stampe/` | documenti PDF: libro lotti, ricettario, richiamo |
| **static/** | `prodotti.css` (tema oro), `prodotti.js` (salvataggi, finestre materia/prodotto), `ricette.js` (editor), `lotti.js` (Nuovo lotto), `fonts/` (Fira Sans, Yeseva One, licenza OFL) |

Fuori dalla cartella: `scripts/importa_etichette.py` (catalogo dalle etichette storiche),
`scripts/prova_stile_etichette.py` (fogli di prova di uno stile), `docs/import/catalogo-etichette.json`.

## Collegamenti con il nucleo

- Utenti e permessi: `app.models.User`, sezione `"prodotti"` (Impostazioni → utenti).
- Fornitori: `app.models.Contact` con `type="fornitore"`. È l'unico punto in cui il modulo scrive nel database
  del nucleo (fornitore creato al volo). Nei lotti il nome del fornitore si copia anche come testo (i due database
  sono file separati: niente chiavi esterne fra loro).
- Database proprio `data/prodotti.db`; PDF delle etichette in `data/prodotti/etichette/AAAA/`.
- Backup: automatico (il backup notturno salva tutti i `data/*.db` e la domenica archivia i PDF).

## Aggiungere una colonna o una tabella

1. Nuova voce in fondo a `MIGRAZIONI` in `schema.py` (numero successivo, solo aggiunte).
2. La colonna nel modello in `models.py`.
3. Il test `tests/test_prodotti_app.py::TestModelliSchema` controlla che modelli e tabelle coincidano.

## Versioni

| Versione | Contenuto |
|---|---|
| 1.0.0 | catalogo, ricettario con versioni, libro lotti con storico, etichette (stile base-2026), export, richiamo, import |
| 1.0.1 | etichette disegnate una alla volta (lucchetto su WeasyPrint): due anteprime contemporanee facevano cadere il sito (502, 25/11/2026) |
| 1.1.0 | stile «classico-giallo» (le etichette storiche, sfondo crema); PDF ~10 volte più veloci (logo PNG, etichetta disegnata una volta e copiata nel foglio, misure riusate); indicatore di attesa con secondi; `stile.json` per il minimo di legge di ogni stile |
| 1.2.0 | modalità «piegata sul cordino» per i salumi (fronte e retro sulla stessa etichetta del foglio Grande, ruotati verso la piega); foglio Salumi L7164 spento (migrazione 4): 3 fogli da comprare |
