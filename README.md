# Ca Bianca Gestionale

Applicazione gestionale per **Fattoria Ca Bianca** - sistema di contabilita, fatturazione elettronica e gestione aziendale.

## Funzionalita

- **Cruscotto** - Panoramica entrate/uscite, grafici, scadenze
- **Prima Nota** - Registro cronologico di tutti i movimenti con filtri avanzati
- **Fatture SDI** - Upload e parsing automatico fatture elettroniche XML (FatturaPA)
- **Registratore di Cassa** - Integrazione con 4CloudOffice per corrispettivi giornalieri
- **Movimenti Manuali** - Registrazione entrate/uscite extra-contabili con allegati
- **Anagrafica** - Gestione clienti (privati, B2B, scuole) e fornitori
- **Inventario** - Prodotti, giacenze, movimenti di magazzino, alert scorte
- **Categorie & Tag** - Categorizzazione flessibile dei movimenti
- **Analisi** - Report con filtro ufficiali/extra-contabili/tutti, grafici per categoria e flusso di ricavo
- **Scadenzario** - Gestione scadenze pagamenti
- **Riconciliazione Bancaria** - Import CBI, abbinamento automatico (regole, SDI, manuali), riconciliazione manuale a due colonne con ricerca AJAX, confronto saldo banca vs contabile, storico saldi giornalieri
- **Esportazione** - CSV per il commercialista
- **Notifiche Telegram** - Alert scadenze, scorte basse, backup
- **Backup automatico** - Google Drive, giornaliero
- **Multi-utente** - Ruoli: admin, operatore, consulente (sola lettura)
- **PWA** - Installabile su smartphone

## Requisiti

- Raspberry Pi (o qualsiasi sistema Linux) con Docker

## Installazione

```bash
git clone https://github.com/corsandre/cabianca-gestionale.git
cd cabianca-gestionale
./setup.sh
```

Lo script chiede interattivamente tutte le credenziali e configura l'applicazione.

## Comandi utili

```bash
docker compose logs -f       # Log in tempo reale
docker compose restart       # Riavvia
docker compose down          # Ferma
docker compose up -d         # Avvia
```

## Stack tecnologico

- **Backend**: Python / Flask
- **Database**: SQLite (WAL mode)
- **Frontend**: Jinja2 + Bootstrap 5 + Chart.js
- **Deploy**: Docker
- **Notifiche**: Telegram Bot API
- **Backup**: Google Drive API

## Struttura progetto

```
app/
  routes/        # Route handlers (un file per sezione)
  templates/     # Template HTML Jinja2
  services/      # Servizi (SDI parser, Telegram, backup, export)
  static/        # CSS, JS, immagini, uploads
  models.py      # Modelli database SQLAlchemy
  config.py      # Configurazione da .env
```

## Licenza

Uso interno - Fattoria Ca Bianca
