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

Gestione del ciclo produttivo per allevamento suini (7 capannoni, 54 box). Riscritta da zero (v2) con
modelli molto più semplici rispetto alla versione originaria: niente tracciabilità bolla-per-bolla DOP,
niente scheduler di allarmi/manutenzioni — solo i dati che vengono davvero usati ogni giorno in stalla.
Ogni funzione è disponibile sia da web sia (per le operazioni quotidiane) dal bot Telegram.

**Cicli**
- Un `Ciclo` è un periodo produttivo semplice (nome, data inizio/fine, attivo). Solo un ciclo attivo alla volta.
- **Panoramica** – conteggio live per capannone/box (ultimo censimento + delta di mortalità/spostamenti), giorni di
  vita e peso stimato per box, contatori uscite macello (fine ciclo / scarto-sottopeso / Ca Bianca Agriturismo),
  scorte mangime/siero

**Censimento**
- Censimenti per box (`Censimento` + `CensimentoBox`): quantità, giorni di vita, peso stimato — **tutti i censimenti
  restano consultabili e immutati** nello storico, con dettaglio per box
- Basta inserire uno tra giorni di vita e peso: l'altro si calcola in automatico dalla curva di accrescimento
- Paginato, con conteggio live proiettato a oggi (giorni/peso aggiornati anche tra un censimento e l'altro)

**Mortalità**
- Griglia settimanale per capannone + storico completo del ciclo (paginato, non solo ultimi 30gg)
- Tre azioni marcabili per evento (rimozione dal PC di alimentazione, registrazione su Webfarm, su RIFT), ciascuna
  con data/ora/operatore registrati al click

**Spostamenti**
- Entrata (da esterno) / Uscita (macello, con categoria: fine ciclo 165-180kg / scarto-sottopeso / Ca Bianca
  Agriturismo) / Interno (box→box) — il box è sempre obbligatorio, non si sposta mai un intero capannone
- Peso medio e foto bolla per entrate/uscite; contatori capi/kg per categoria di uscita, filtrabili cliccando la card
- Modificabile e cancellabile (admin) dopo la registrazione

**Consegne (mangime e siero)**
- Registro consegne con data/ora, quantità, tipo/lotto, fornitore, foto bolla — modificabile e cancellabile (admin)
- Giacenza mangime cumulativa (non si azzera tra cicli); giacenza siero per carico (la cisterna si svuota sempre
  prima del carico successivo), con confronto tra quantità dichiarata alla consegna e consumo reale pesato in cucina
- Stima "pasti/giorni residui" basata sull'ultimo pasto completo ripetuto in avanti (non una media storica)
- Data/ora stimata in cui ci sarà di nuovo spazio per un carico di mangime da riordinare (quantità configurabile)
- Ricalibrazione manuale della giacenza mangime (conteggio fisico silos, con data/ora dell'operazione)

**Alimentazione**
- Inserimento consumi reali per pasto/linea (mangime, siero, acqua); un pasto conta come completo solo quando
  tutte le linee attive hanno un valore e l'orario configurato è passato
- % di sostituzione sostanza secca del siero calcolata sul consumo reale

**Trattamenti**
- Registro trattamenti (`Medicinale`, `Trattamento`, `Somministrazione`): un corso di cura per box o intero
  capannone, con dose per capo/totale calcolata da ml/kg × peso medio × numero animali
- Evidenza delle dosi da ripetere, periodo di sospensione prima del macello
- Chiusura anticipata di un trattamento non completato, con motivazione accodata alle note

**Impostazioni**
- Struttura fisica: capannoni/box/linee alimentazione (costanti hardcoded, non modelli DB)
- Curva di accrescimento (età → peso), usata per il censimento e il conteggio live
- Medicinali disponibili per i trattamenti
- Capacità silos, soglia di riordino (in pasti, non quintali fissi — segue l'aumento del consumo), quantità per
  ordine, orari dei 3 pasti giornalieri

**Modelli dati principali** (`app/models.py`)

| Modello | Descrizione |
|---|---|
| `Ciclo` | Periodo produttivo (nome, data inizio/fine, attivo) |
| `Censimento` / `CensimentoBox` | Censimento per box, immutabile nello storico (quantità, giorni vita, peso stimato) |
| `CurvaAccrescimento` | Punti (età gg, peso kg) per interpolare l'uno dall'altro |
| `EventoMortalita` | Evento di mortalità per box/capannone, con le 3 azioni post-mortalità (data/ora/operatore) |
| `Spostamento` | Entrata/uscita/interno, con categoria_uscita, peso medio, foto bolla |
| `ConsegnaSiero` / `ConsegnaMangime` | Consegne con data/ora, quantità, foto bolla |
| `CalibrazioneGiacenza` | Ricalibrazioni manuali della giacenza mangime nel tempo |
| `UsoPasto` | Consumo reale per pasto/linea (mangime, siero, acqua) |
| `RazioneBox` | Percentuale di razione per box (impostazione manuale) |
| `Medicinale` | Farmaci disponibili (ml/kg, giorni somministrazione/sospensione) |
| `Trattamento` / `Somministrazione` | Corso di cura per box/capannone e singole dosi |

**Servizi principali** (`app/services/allevamento_scorte.py`)

| Funzione | Descrizione |
|---|---|
| `peso_da_giorni` / `giorni_da_peso` | Interpolano la curva di accrescimento nei due sensi |
| `pasto_completo` | Un pasto conta solo se l'orario è passato e tutte le linee attive hanno un valore |
| `_ultimo_consumo_pasto` | Consumo dell'ultimo pasto completo, usato per proiettare in avanti |
| `stima_esaurimento` | Simula pasto per pasto (ripetendo l'ultimo) fino a esaurimento scorta |
| `stima_spazio_carico` | Come sopra, ma fino a quando c'è spazio per un nuovo carico da riordinare |
| `giacenza_mangime` / `giacenza_siero` | Giacenza corrente (cumulativa per il mangime, per carico per il siero) |
| `ultima_calibrazione` | Ultima ricalibrazione manuale prima di un certo istante (per calcoli storici coerenti) |
| `scarto_consegna_siero` | Confronto tra siero dichiarato alla consegna e consumo reale pesato |

Bot Telegram (`app/services/allevamento_bot.py`): stesse funzioni principali via percorsi guidati
(censimento, mortalità, spostamenti, consegne, alimentazione, trattamenti), costruito come un'unica
`ConversationHandler` con stato `MAIN_MENU` a cui ogni flusso deve tornare per lasciare i bottoni del
menu funzionanti dopo la conferma.

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
