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

### Allevamento Suini (tema rosa)

Gestione completa del ciclo produttivo per allevamento DOP Parma (7 capannoni, 54 box, 1822 posti).

**Cicli e box**
- **Panoramica** – Mappa SVG interattiva dell'allevamento: box colorati per linea/stato, click per modal con dettaglio box
- **Cicli produttivi** – Creazione ciclo con accasamento multi-box, gestione lotti (bolle DOP), riaccasamento interciclo
- **Timeline eventi** – Mortalità, frazionamenti, uscite macello (normali/scarti) con aggiornamento automatico conteggi
- **Rigenera stime** – Ricalcolo retroattivo di tutte le razioni teoriche per un ciclo (admin)

**Sanità**
- Trattamenti sanitari per box (principio attivo, dose, durata)
- Registro inappetenza per box
- Storico sanitario completo

**Alimentazione**
- Calcolo razioni teoriche per linea (mangime + siero + acqua) basato su curva di accrescimento e tabella sostituzione siero
- Inserimento consumi reali a pasto con confronto teorico/effettivo
- Storico consumo giornaliero aggregato per linea con drill-down a pasto
- Livello cisterna acqua con alert soglie

**Magazzino & Ordini**
- Registro consegne mangime con aggiornamento giacenza
- Gestione ordini con cambio stato (in attesa / confermato / consegnato)

**Allarmi**
- Job schedulato h 06:00 per verifica automatica soglie (mortalità settimanale, giacenza mangime, cisterna acqua)
- Silenziamento temporaneo e risoluzione allarmi

**Manutenzioni**
- Registro interventi per box (ordinaria/straordinaria) con scadenza e storico

**Report**
- Indice report per ciclo con statistiche: capi iniziali/finali, mortalità %, uscite macello (normali/scarti), peso effettivo, durata ciclo
- Report trattamenti sanitari
- Report movimenti (uscite macello, frazionamenti)

**Impostazioni**
- Struttura fisica: capannoni/box con capienza e linea alimentazione
- Curva di accrescimento (età → peso → razione giornaliera)
- Tabella sostituzione siero (% per fascia d'età)
- Parametri acqua, cisterna, numero pasti giornalieri

**Modelli dati principali**

| Modello | Descrizione |
|---|---|
| `CicloProduttivo` | Periodo produttivo (accasamento → macello) |
| `Lotto` | Singola bolla/consegna DOP con lettera nascita |
| `BoxCiclo` | Associazione box ↔ ciclo con conteggio capi e peso |
| `EventoCiclo` | Evento su un box: mortalita / frazionamento / uscita_macello / riaccasamento |
| `CurvaAccrescimento` | Punti (età gg, peso kg, razione kg/gg) per interpolazione |
| `TabellaSostSiero` | Fasce d'età con percentuale sostituzione siero |
| `RazioneGiornaliera` | Razione teorica/reale per linea × giorno (is_stima flag) |
| `TrattamentoSanitario` | Trattamenti sanitari per box |
| `MagazzinoProdotto` | Giacenza attuale per tipo prodotto |
| `Allarme` | Allarmi generati dallo scheduler con stato e silenziamento |

**Funzioni helper principali (`app/routes/allevamento.py`)**

| Funzione | Descrizione |
|---|---|
| `_eta_da_peso(peso_kg)` | Interpola la curva: peso → età stimata in giorni |
| `_peso_da_eta(eta_gg)` | Interpola la curva: età in giorni → peso stimato in kg |
| `_razione_da_eta(eta_gg)` | Interpola la curva: età → razione giornaliera kg/capo |
| `_perc_siero_da_eta(eta_gg)` | Tabella sostituzione: età → % siero |
| `_calcola_razioni_linea(linea)` | Razione totale teorica per una linea (mangime, siero, acqua) |
| `_calcola_razioni_linea_dettaglio(linea)` | Come sopra ma con dettaglio per box (per espansione UI) |
| `_capi_storici_data(bc, data_target)` | Capi presenti in un BoxCiclo a una data specifica (ricostruisce da eventi) |
| `_rigenera_stime_ciclo(ciclo, data_da)` | Rigenera tutte le `RazioneGiornaliera` stimate dal data_da a oggi |
| `_calcola_acqua(mangime_kg, siero_litri)` | Calcola acqua aggiuntiva rispettando rapporto SS:Liquido |
| `_genera_ciclo_id()` | Genera ID univoco formato `CICLO{aa}-{nn}-{YYYYMMDD}` |
| `_calcola_data_vendita(lettera, data_arrivo)` | Data minima vendita DOP: 9 mesi dalla nascita (lettera mese) |
| `_box_state(box, active_alarms_bc_ids)` | Stato box per mappa SVG (libero/attivo/allarme/in_uscita) |
| `_allarmi_attivi_count()` | Conta allarmi attivi non silenziati (badge menu) |
| `_get_setting_float(key, default)` | Legge un Setting dal DB e lo converte in float |
| `_set_setting(key, value)` | Upsert di un record Setting |
| `_admin_required()` | Guard helper: redirect se utente non è admin |

## Funzionalita trasversali

- **Esportazione** - CSV per il commercialista
- **Notifiche Telegram** - Alert scadenze, scorte basse, backup
- **Backup automatico** - Via email, frequenza e orario configurabili dal pannello
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
- **Backup**: SMTP (smtplib)

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
