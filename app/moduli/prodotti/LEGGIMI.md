# Modulo Prodotti – mappa

Ricettario, libro dei lotti ed etichette dei prodotti trasformati di Fattoria Ca' Bianca
(marmellate, mostarde, conserve, pasta ripiena, salumi…). Serve anche come registro per i controlli
NAS/ATS: tracciabilità "un passo indietro" (fornitore e lotto di ogni ingrediente, Reg. CE 178/2002)
ed etichette secondo il Reg. UE 1169/2011.

Piano completo e stato dei lavori: `docs/piano-prodotti.md`. Regole generali dei moduli: README,
«Moduli e ruoli dei processi».

## File

| File | A cosa serve |
|---|---|
| `__init__.py` | interfaccia verso il nucleo: `NOME`, `VERSIONE`, `DATABASE`, `migra`, `registra`, `stato` |
| `schema.py` | migrazioni numerate di `data/prodotti.db` (solo aggiunte, mai modificare quelle rilasciate) |
| `routes.py` | pagine `/prodotti/...`; login + sezione "prodotti" obbligatori per tutte |
| `templates/prodotti/_base.html` | base delle pagine del modulo (aggiunge `prodotti.css`) |
| `templates/prodotti/_menu.html` | gruppo PRODOTTI del menu laterale (incluso dal nucleo) |
| `static/prodotti.css` | tema oro/bronzo `.theme-prodotti` e stili del modulo |
| `services/` | logica pura, senza Flask (codice lotto, testo ingredienti, etichette…), testata in `tests/` |

## Collegamenti con il nucleo

- Utenti e permessi: `app.models.User`, sezione `"prodotti"` (Impostazioni → utenti).
- Fornitori: `app.models.Contact` con `type="fornitore"`, solo in lettura. Nei lotti il nome del fornitore
  si copia anche come testo (i due database sono file separati: niente chiavi esterne fra loro).
- Database proprio `data/prodotti.db` (bind SQLAlchemy `"prodotti"`, modelli con `__bind_key__ = "prodotti"`).
- Backup: automatico, il backup notturno salva tutti i `data/*.db`.

## Versioni

| Versione | Contenuto |
|---|---|
| 1.0.0-dev | modulo vuoto: pagina iniziale, menu, permesso, `schema` v1 (tabella `impostazioni`) |
