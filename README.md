# Ca Bianca Gestionale

Applicazione gestionale per **Fattoria Ca Bianca** - sistema di contabilita, fatturazione elettronica e gestione aziendale.

## Sezioni

L'applicazione e' strutturata in sezioni indipendenti, ciascuna con tema visivo dedicato e accesso per utente configurabile.

### Finanza (tema verde)

- **Cruscotto** - Panoramica entrate/uscite, grafici, scadenze
- **Prima Nota** - Registro cronologico di tutti i movimenti con filtri avanzati
- **Fatture SDI** - Upload e parsing automatico fatture elettroniche XML (FatturaPA)
- **Registratore di Cassa** - Integrazione con 4CloudOffice per corrispettivi giornalieri
- **Movimenti Manuali** - Registrazione entrate/uscite extra-contabili con allegati
- **Spese Ricorrenti** - Generazione automatica di transazioni periodiche
- **Banca** - Import CBI, riconciliazione automatica/manuale, confronto saldo banca vs contabile
- **Anagrafica** - Gestione clienti (privati, B2B, scuole) e fornitori
- **Inventario** - Prodotti, giacenze, movimenti di magazzino, alert scorte
- **Categorie & Tag** - Categorizzazione flessibile dei movimenti
- **Analisi** - Report con filtro ufficiali/extra-contabili/tutti, grafici per categoria e flusso di ricavo
- **Scadenzario** - Gestione scadenze pagamenti

### Allevamento Suini (tema rosa) — scaffold

- Sezione in sviluppo

## Funzionalita trasversali

- **Esportazione** - CSV per il commercialista
- **Notifiche Telegram** - Alert scadenze, scorte basse, backup
- **Backup automatico** - Google Drive, giornaliero
- **Multi-utente** - Ruoli (admin, operatore, consulente) + accesso per sezione configurabile
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
  routes/        # Route handlers (un file per blueprint)
    finanza_impostazioni.py   # Impostazioni sezione Finanza (flussi di ricavo)
    allevamento.py            # Sezione Allevamento Suini
    ...                       # Un file per ogni area funzionale
  templates/     # Template HTML Jinja2
    allevamento/              # Template sezione allevamento
    finanza_impostazioni/     # Template impostazioni finanza
  services/      # Servizi (SDI parser, Telegram, backup, export)
  static/        # CSS, JS, immagini, uploads
  models.py      # Modelli database SQLAlchemy
  config.py      # Configurazione da .env
  utils/
    decorators.py  # role_required, write_required, section_required
```

## Controllo accesso sezioni

Ogni utente ha un campo `sections` (JSON) che elenca le sezioni accessibili (es. `["finanza", "allevamento"]`). Gli admin hanno accesso a tutto. Il decorator `section_required` e' registrato come `before_request` su ogni blueprint di sezione.

## Licenza

Uso interno - Fattoria Ca Bianca
