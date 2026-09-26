# Ca Bianca Gestionale

Applicazione gestionale per **Fattoria Ca Bianca**: contabilità, fatturazione elettronica, banca, magazzino e
gestione dell'allevamento suini. Web app Flask in Docker, usabile da PC e da smartphone (PWA), con un bot Telegram
per le operazioni quotidiane di stalla.

---

## Indice

- [Architettura e ambienti](#architettura-e-ambienti)
- [Sezioni](#sezioni)
  - [Finanza](#finanza-tema-verde)
  - [Allevamento Suini](#allevamento-suini-tema-rosa)
- [Bot Telegram](#bot-telegram)
- [Funzionalità trasversali](#funzionalità-trasversali)
- [Utenti, ruoli e accesso alle sezioni](#utenti-ruoli-e-accesso-alle-sezioni)
- [Attività pianificate](#attività-pianificate)
- [Backup e ripristino](#backup-e-ripristino)
- [Sicurezza](#sicurezza)
- [Configurazione (.env)](#configurazione-env)
- [Installazione](#installazione)
- [Deploy di un aggiornamento](#deploy-di-un-aggiornamento)
- [Database e migrazioni](#database-e-migrazioni)
- [Struttura del progetto](#struttura-del-progetto)
- [Convenzioni di sviluppo](#convenzioni-di-sviluppo)
- [Risoluzione problemi](#risoluzione-problemi)
- [Stack tecnologico](#stack-tecnologico)

---

## Architettura e ambienti

```
Internet ──HTTPS──▶ Caddy (VPS, certificati automatici) ──▶ 127.0.0.1:8080 ──▶ container Docker "web"
                                                                              ├─ Gunicorn (1 worker, 2 thread)
                                                                              ├─ Flask app
                                                                              ├─ APScheduler (job notturni)
                                                                              └─ Bot Telegram allevamento (thread)
                                                     volumi: data/ (SQLite)  backups/  app/static/uploads/
```

- **Produzione**: VPS Linux (Ubuntu) dietro **Caddy** come reverse proxy HTTPS. Il container pubblica la porta solo
  su `127.0.0.1` (`APP_BIND=127.0.0.1`), perché Docker scrive regole iptables proprie che scavalcano `ufw`: con
  `0.0.0.0` la porta 8080 sarebbe raggiungibile dall'esterno anche a firewall attivo. Sul firewall sono aperte
  solo SSH, 80 e 443.
- **Un'unica istanza attiva.** Il bot Telegram usa il long polling (`getUpdates`): due istanze con lo stesso
  `TELEGRAM_BOT_TOKEN` si rubano a vicenda i messaggi (errore `409 Conflict` nei log) e i dati inviati dal bot
  possono finire nel database sbagliato. Macchine di sviluppo o vecchi server (es. il Raspberry usato prima del
  VPS) **non devono avviare il container** con il token di produzione. Per provare il codice in locale si usa una
  copia del DB e `docker compose run` senza avviare il bot (vedi [Deploy](#deploy-di-un-aggiornamento)).
- Tutto il codice, i template e gli static sono **copiati nell'immagine** al build: ogni modifica richiede un
  rebuild; `docker compose restart` non aggiorna nulla.

---

## Sezioni

L'applicazione è divisa in sezioni indipendenti, ciascuna con il proprio tema visivo e accesso configurabile per
utente (vedi [Utenti](#utenti-ruoli-e-accesso-alle-sezioni)).

### Finanza (tema verde)

| Pagina | URL | Descrizione |
|---|---|---|
| Cruscotto | `/` | Panoramica entrate/uscite, grafici, scadenze imminenti |
| Prima Nota | `/prima-nota` | Registro cronologico di tutti i movimenti, filtri avanzati |
| Fatture SDI | `/fatture` | Upload e parsing automatico di fatture elettroniche XML (FatturaPA, anche `.p7m`) e PDF (formato TeamSystem); recupero automatico dalla casella email via IMAP |
| Registratore di cassa | `/cassa` | Sincronizzazione corrispettivi giornalieri da 4CloudOffice (manuale o notturna) |
| Movimenti manuali | `/movimenti` | Entrate/uscite extra-contabili con allegati |
| Spese ricorrenti | `/ricorrenti` | Modelli di spesa periodica, generazione automatica delle transazioni |
| Banca | `/banca` | Import estratti conto CBI, riconciliazione automatica (punteggio su importo/data/nome) e manuale, movimenti sospesi e ignorati con motivazione, regole automatiche, saldo banca vs contabile |
| Anagrafica | `/anagrafica` | Clienti (privati, B2B, scuole) e fornitori |
| Inventario | `/inventario` | Prodotti, giacenze, movimenti di magazzino, alert scorte basse |
| Categorie & Tag | `/categorie` | Categorizzazione flessibile dei movimenti |
| Analisi | `/analisi` | Report con filtro ufficiali / extra-contabili / tutti, grafici per categoria e flusso di ricavo, esportazione CSV |
| Scadenzario | `/scadenzario` | Scadenze pagamenti, segna come pagato |
| Impostazioni finanza | `/finanza/impostazioni` | Flussi di ricavo |

**Regole automatiche banca** (`AutoRule`, `app/services/rules_engine.py`): condizioni su descrizione/importo/fonte
che assegnano categoria, contatto, metodo di pagamento, aliquota IVA, note, spostamento data, oppure ignorano il
movimento con un motivo. Possono essere riapplicate in blocco ai movimenti esistenti.

### Allevamento Suini (tema rosa)

Gestione del ciclo produttivo dell'allevamento: 7 capannoni, 54 box, 3 linee di alimentazione
(linea 1 blu: CAP 1-2-3, linea 2 rossa: CAP 4, linea 3 verde: CAP 5-6-7).
Riscritta da zero (**v2**) con modelli molto più semplici della versione originaria: niente tracciabilità
bolla-per-bolla DOP, niente scheduler di allarmi/manutenzioni, solo i dati che si usano davvero ogni giorno in
stalla. Le operazioni quotidiane sono disponibili anche dal [bot Telegram](#bot-telegram).

Capannoni e box **non sono tabelle del DB**: sono costanti in `app/routes/allevamento.py` (`CAPANNONI`,
`BOX_PER_CAP`, `CAP_PER_BOX`, `POSTI_PER_CAP`), duplicate in `app/services/allevamento_bot.py`. Se cambia la
struttura fisica vanno aggiornate in entrambi i file.

#### Cicli e panoramica (`/allevamento/`)
- Un `Ciclo` è un periodo produttivo (nome, data inizio/fine, attivo). **Un solo ciclo attivo alla volta**; si apre
  e si chiude da Impostazioni. Quasi tutte le registrazioni sono legate al ciclo attivo.
- Panoramica: conteggio live per capannone/box (ultimo censimento + delta di mortalità e spostamenti), giorni di
  vita e peso stimato per box proiettati a oggi, contatori uscite macello per categoria, giacenze mangime e siero.

#### Censimento (`/allevamento/censimento`)
- Censimenti per box (`Censimento` + `CensimentoBox`): quantità, giorni di vita, peso stimato.
- Basta inserire uno tra giorni di vita e peso: l'altro si ricava dalla **curva di accrescimento**.
- I censimenti sono **immutabili** e restano consultabili nello storico paginato, con dettaglio per box.

#### Mortalità (`/allevamento/mortalita`)
- Griglia settimanale per capannone + storico completo del ciclo (paginato).
- Per ogni evento tre azioni da spuntare: rimozione dal PC di alimentazione, registrazione su Webfarm,
  registrazione su RIFT. Ogni spunta salva data/ora e operatore; si può annullare.

#### Spostamenti (`/allevamento/spostamenti`)
- **Entrata** (da esterno), **Uscita** (macello, con categoria: fine ciclo 165-180 kg / scarto-sottopeso /
  Macellati Ca Bianca Agriturismo), **Interno** (box → box). Il box è sempre obbligatorio.
- Peso medio e foto della bolla per entrate/uscite; contatori capi/kg per categoria di uscita, filtrabili.
- Pulsante **PC alim.** per segnare che lo spostamento è stato riportato sul PC di alimentazione: salva data/ora
  e operatore (badge verde, un clic per annullare), come per la mortalità.
- Modificabili ed eliminabili dall'admin.

#### Consegne mangime e siero (`/allevamento/consegne`)
- Registro consegne con data/ora, quantità (quintali), foto bolla, note; modifica ed eliminazione riservate
  all'admin. La foto della bolla si può aggiungere anche dopo, dall'icona 📷 nella tabella.
- **Invio robusto da campo**: il modulo invia prima i dati (con 3 tentativi) e poi, separatamente, la foto
  compressa nel browser (max 1600 px). Se la connessione cade durante la foto, la consegna resta salvata.
- **Siero**: quantità, % sostanza secca (Brix), lotto, **speditore**, trasportatore. Ogni nuovo carico chiude il
  precedente (la cisterna si svuota sempre prima di ricaricare): per questo l'ora è obbligatoria. Per ogni carico
  chiuso: consumo reale pesato in cucina e scarto rispetto al dichiarato, con evidenza se supera la soglia.
  Si può anche segnare a mano la cisterna vuota.
- **Speditori siero** (`SpeditoreSiero`): anagrafica con azienda, indirizzo, tipo di siero e note, gestita
  dall'elenco in fondo alla pagina Consegne (creazione per tutti, modifica/eliminazione per l'admin; uno
  speditore usato in qualche consegna non si può eliminare). Nel modal della consegna lo speditore si **sceglie
  da un menu**, con la voce *"＋ Nuovo speditore…"* per crearlo al volo senza uscire dal modulo. La stessa azienda
  con sedi diverse è uno speditore diverso (es. Galbani di Corte Olona e di Casale Cremasco): è vietato solo il
  doppione esatto azienda + indirizzo. Lo speditore appare come **Azienda** (indirizzo), con l'indirizzo in grigio.
  Il vecchio campo testuale `consegne_siero.speditore` resta nel DB solo per lo storico.
- **Mangime**: tipo, numero bolla, fornitore. Giacenza **cumulativa** (non si azzera tra i cicli), ricalibrabile
  a mano con un conteggio fisico dei silos (data/ora/operatore): da lì i calcoli ripartono dal valore reale.
- Stime: pasti/giorni residui (simulazione pasto per pasto ripetendo l'ultimo pasto completo, non una media
  storica) e data/ora in cui ci sarà spazio nei silos per un nuovo carico da riordinare.

#### Alimentazione (`/allevamento/alimentazione`)
- Consumi reali per **pasto (1/2/3) e linea**: mangime, siero, acqua (quintali). Un pasto conta come completo solo
  quando tutte le linee attive hanno un valore e l'orario configurato è passato.
- I pasti non inseriti vengono stimati copiando l'ultimo reale (`stimato=True`), mai in modo retroattivo.
- % di sostituzione della sostanza secca con il siero calcolata sul consumo reale e sulla % s.s. del carico in uso.

#### Razione box (`/allevamento/razione`)
- Percentuale di razione per box, in una griglia settimanale.
- Oggi resta modificabile; appena un giorno passa senza inserimento, per ogni box viene salvata una riga reale
  con l'ultimo valore noto (`stimato=True`, celle evidenziate in giallo). Correggere un giorno passato non
  ricalcola i giorni successivi.

#### Trattamenti (`/allevamento/trattamenti`)
- Registro dei trattamenti (`Medicinale`, `Trattamento`, `Somministrazione`) per box o intero capannone.
- Dose per capo e totale = ml/kg × peso medio × numero animali; dosi da ripetere in evidenza; periodo di
  sospensione prima del macello.
- Modifica, chiusura anticipata con motivazione (accodata alle note), eliminazione.

#### Impostazioni allevamento (`/allevamento/impostazioni`, solo admin)
- Apertura/chiusura ciclo.
- Curva di accrescimento (età in giorni → peso in kg).
- Medicinali (ml/kg, giorni di somministrazione e sospensione).
- Scorte: capacità silos, soglia di riordino (in pasti, così segue l'aumento dei consumi), quantità per ordine,
  soglia di scarto siero, orari dei 3 pasti.

#### Modelli dati (`app/models.py`)

| Modello | Tabella | Descrizione |
|---|---|---|
| `Ciclo` | `cicli_v2` | Periodo produttivo |
| `Censimento` / `CensimentoBox` | `censimenti` / `censimento_box` | Censimento per box, immutabile |
| `CurvaAccrescimento` | `curva_accrescimento` | Punti età → peso per interpolare |
| `EventoMortalita` | `eventi_mortalita` | Morti per box, con le 3 azioni successive |
| `Spostamento` | `spostamenti_animali` | Entrata/uscita/interno, categoria uscita, peso, bolla |
| `SpeditoreSiero` | `speditori_siero` | Anagrafica speditori (azienda, indirizzo, tipo siero, note) |
| `ConsegnaSiero` | `consegne_siero` | Carichi di siero, con `speditore_id` e chiusura del carico |
| `ConsegnaMangime` | `consegne_mangime` | Consegne di mangime |
| `CalibrazioneGiacenza` | `calibrazioni_giacenza` | Ricalibrazioni manuali della giacenza mangime |
| `UsoPasto` | `uso_pasti` | Consumo per pasto/linea, reale o stimato |
| `RazioneBox` | `razioni_box_v2` | % razione per box e giorno, reale o stimata |
| `Medicinale` | `medicinali` | Farmaci disponibili |
| `Trattamento` / `Somministrazione` | `trattamenti` / `somministrazioni` | Corso di cura e singole dosi |

#### Servizi (`app/services/`)

| File | Contenuto |
|---|---|
| `allevamento_scorte.py` | Giacenze mangime/siero, curva di accrescimento (`peso_da_giorni`, `giorni_da_peso`), `pasto_completo`, stime di esaurimento e spazio per il carico, ricalibrazioni, scarto dei carichi di siero |
| `allevamento_pasti.py` | Registrazione pasti, stime dei pasti mancanti, calcolo % siero |
| `allevamento_bot.py` | Bot Telegram dell'allevamento |

---

## Bot Telegram

Due usi dello stesso bot (`TELEGRAM_BOT_TOKEN`), su tre gruppi Telegram (allevamento, finanza, notifiche di sistema):

1. **Notifiche** (`app/services/telegram_bot.py`, `send_telegram_message(testo, canale=...)`), inviate a gruppi dedicati:
   - canale `finanza` → `TELEGRAM_CHAT_ID` (gruppo *Finanza*): scadenze arretrate e dei prossimi 7 giorni, avvisi banca
     (import CBI mancante, movimenti da riconciliare, esito import), scorte basse dell'inventario, sincronizzazione
     cassa, fatture SDI importate da email;
   - canale `sistema` → `TELEGRAM_SISTEMA_CHAT_ID` (gruppo *Notifiche sistema*): backup e notifiche tecniche future.
   Nei gruppi delle notifiche il bot non risponde ai comandi e ignora i messaggi.
2. **Bot allevamento** (`app/services/allevamento_bot.py`), avviato in un thread all'avvio dell'app. Menu a
   pulsanti con percorsi guidati:
   - 📋 Censimento, 🍽️ Registra consumo (linea → pasto → mangime → siero → acqua), 💀 Registra morte,
     🔄 Spostamento, 🚚 Consegna siero (quintali → % s.s. → speditore tra quelli in anagrafica → foto bolla),
     🌾 Consegna mangime, 💊 Trattamenti (da fare oggi / nuovo), 📊 Stato ciclo.
   - Comandi: `/start` e `/menu` (menu principale), `/cancel` (annulla), `/skip` per i campi facoltativi.
   - Gli speditori nuovi si creano dal web; il bot propone solo quelli esistenti.

**Accesso e uso nel gruppo aziendale.** Con `TELEGRAM_GROUP_ID` impostato, il bot risponde solo nel gruppo
aziendale e, in chat privata, solo a chi è membro di quel gruppo (verifica ricontrollata al massimo ogni 10 minuti):
per dare o togliere l'accesso a un collega basta aggiungerlo o toglierlo dal gruppo. Messaggi da altri gruppi o
da estranei vengono ignorati e registrati nel log. Nel gruppo ogni collega ha il proprio percorso separato; chi
preme i pulsanti del menu aperto da un altro riceve l'avviso "Questo menu è di …". Se Telegram trasforma il
gruppo in supergruppo (cambia ID) il bot segue il nuovo ID e chiede nel log di aggiornare `.env`.

Configurazione su BotFather per l'uso nel gruppo: `/setprivacy` → **Disable** (altrimenti nel gruppo il bot non
riceve i numeri scritti come risposta; dopo la modifica va tolto e riaggiunto al gruppo) e, una volta aggiunto,
`/setjoingroups` → **Disable** (nessuno può aggiungerlo ad altri gruppi). Per trovare l'ID del gruppo: lasciare
vuoto `TELEGRAM_GROUP_ID`, scrivere `/menu` nel gruppo e leggere l'ID nel log (`Bot Telegram: messaggio dal gruppo …`).

Il bot è un'unica `ConversationHandler`: ogni flusso deve tornare allo stato `MAIN_MENU`, altrimenti i pulsanti
del menu smettono di rispondere dopo la conferma.

---

## Funzionalità trasversali

- **Esportazione CSV** per il commercialista.
- **Allegati e foto** in `app/static/uploads/` (volume persistente), max 16 MB per upload.
- **PWA**: installabile su smartphone.
- **Multi-utente** con ruoli e accesso per sezione.
- **Log**: il logger `httpx` è a livello WARNING perché a INFO scriverebbe nei log l'URL delle chiamate a
  Telegram, che contiene il token del bot.

---

## Utenti, ruoli e accesso alle sezioni

| Ruolo | Permessi |
|---|---|
| `admin` | Tutto: impostazioni, utenti, backup, modifiche/eliminazioni di registrazioni già fatte |
| `operatore` | Lettura e inserimento (`write_required`) |
| `consulente` | Sola lettura |

Ogni utente ha un campo `sections` (JSON, es. `["finanza", "allevamento"]`) con le sezioni accessibili; l'admin
le vede tutte. Il controllo è il decorator `section_required`, registrato come `before_request` su ogni blueprint
di sezione. L'utente admin iniziale viene creato al primo avvio da `ADMIN_USERNAME` / `ADMIN_PASSWORD`; gli altri
si gestiscono da **Impostazioni → Utenti**.

---

## Attività pianificate

APScheduler gira nel processo dell'app (fuso `Europe/Rome`):

| Orario | Job | Note |
|---|---|---|
| configurabile (default 02:00) | Backup | Rispetta la frequenza in giorni impostata |
| 03:00 | Generazione spese ricorrenti | |
| 04:00 | Sincronizzazione registratore di cassa | Solo se configurato 4CloudOffice |
| 08:00 | Notifica scadenze su Telegram | |
| 08:30, 14:30, 20:30 | Recupero fatture SDI da email (IMAP) | Solo se configurato IMAP |

---

## Backup e ripristino

- Il job copia il database in `backups/gestionale_backup_AAAAMMGG_HHMMSS.db`, tiene **gli ultimi 7 file**, lo invia
  come allegato all'indirizzo configurato (SMTP) e manda un messaggio Telegram "Backup completato".
- Orario, **frequenza in giorni** e destinatario email si impostano da **Impostazioni → Backup**. Con una frequenza
  maggiore di 1, nelle notti intermedie il log riporta `Backup saltato: eseguito di recente secondo la frequenza
  configurata`: è il comportamento previsto, non un errore.
- Da **Impostazioni → Backup** l'admin può lanciare subito un backup o ripristinare uno dei file in `backups/`.
- Prima di un deploy che modifica lo schema conviene fare una copia a mano (vedi sotto).

---

## Sicurezza

**Server (VPS)**
- **fail2ban** sul servizio SSH (`/etc/fail2ban/jail.local`): 5 tentativi falliti in 10 minuti → ban di 1 ora,
  che cresce per chi ritorna fino a 1 settimana. `ignoreip` contiene localhost, l'IP della sede e la rete
  ZeroTier, per non bloccare gli accessi legittimi. Stato: `sudo fail2ban-client status sshd`;
  sbloccare un IP: `sudo fail2ban-client set sshd unbanip <ip>`.
- Login di root via SSH disattivato; accesso con chiave (il login con password è ancora attivo, protetto da fail2ban).
- Aggiornamenti di sicurezza automatici (`unattended-upgrades`).
- `.env` con permessi `600`.

**Caddy** (`/etc/caddy/Caddyfile`)
- HTTPS con certificati automatici e redirect da HTTP.
- Header: `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options: SAMEORIGIN`,
  `Referrer-Policy`, `Permissions-Policy`; header `Server` rimosso.
- **Log degli accessi** in `/var/log/caddy/access.log` (JSON, IP reale del client, rotazione 20 MB × 10 file,
  max 30 giorni). A differenza dei log del container, sopravvive ai deploy.
- Dopo ogni modifica: `sudo caddy validate --config /etc/caddy/Caddyfile` e `sudo systemctl reload caddy`.
  Attenzione: `validate` eseguito come root crea il file di log se manca, di proprietà di root, e il reload poi
  fallisce con `permission denied` (Caddy resta sulla configurazione precedente, il sito non si ferma):
  `sudo chown caddy:caddy /var/log/caddy/access.log`.

**Applicazione**
- Login: dopo 5 tentativi falliti in 15 minuti dallo stesso IP (o 20 sullo stesso utente da IP diversi) il login
  è bloccato per 15 minuti (HTTP 429). I tentativi falliti finiscono nel log con utente e IP. Il contatore è in
  memoria e si azzera al riavvio.
- L'IP reale arriva da Caddy tramite `X-Forwarded-For` (`ProxyFix`).
- Il parametro `next` del login accetta solo percorsi interni (niente redirect verso siti esterni).
- Cookie di sessione e "ricordami" `Secure`, `HttpOnly`, `SameSite=Lax`; "ricordami" valido 30 giorni.
- CSRF su tutti i form (Flask-WTF), password con bcrypt.
- Gli allegati in `app/static/uploads/` (foto bolle, fatture, ricevute) sono serviti solo agli utenti loggati;
  i nuovi file hanno nomi casuali.

---

## Configurazione (.env)

Il file `.env` (creato da `setup.sh`, mai committato) contiene:

| Variabile | Descrizione |
|---|---|
| `SECRET_KEY` | Chiave per le sessioni Flask |
| `DATABASE_URL` | Default `sqlite:///data/gestionale.db` |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_DISPLAY_NAME` | Utente admin creato al primo avvio |
| `TELEGRAM_BOT_TOKEN` | Token del bot. **Un solo server alla volta può usare il token** |
| `TELEGRAM_CHAT_ID` | Gruppo (o chat) delle notifiche finanza |
| `TELEGRAM_SISTEMA_CHAT_ID` | Gruppo delle notifiche di sistema (backup); vuoto = in `TELEGRAM_CHAT_ID` |
| `TELEGRAM_GROUP_ID` | Gruppo aziendale autorizzato a usare il bot (vuoto = nessun controllo) |
| `CLOUD_OFFICE_URL`, `CLOUD_OFFICE_USER`, `CLOUD_OFFICE_PASSWORD` | Registratore di cassa 4CloudOffice |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Invio backup via email |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD`, `IMAP_FOLDER`, `IMAP_SEARCH_FROM` | Recupero fatture SDI dalla casella email |
| `APP_PORT` | Porta del container (default 8080) |
| `APP_BIND` | Interfaccia su cui pubblicare la porta: `127.0.0.1` dietro reverse proxy (produzione), `0.0.0.0` (default) in LAN |
| `COOKIE_SECURE` | `1` (default): cookie solo su HTTPS. `0` solo se l'app è usata in http (LAN senza proxy), altrimenti il login non funziona |
| `APP_HOST`, `APP_DEBUG` | Opzioni di esecuzione |

Le impostazioni modificabili dal pannello (backup, scorte, orari pasti, soglie…) stanno invece nella tabella
`settings` del database.

---

## Installazione

Requisiti: un server Linux con Docker e Docker Compose (lo script li installa se mancano).

```bash
git clone https://github.com/corsandre/cabianca-gestionale.git
cd cabianca-gestionale
./setup.sh
```

Lo script chiede le credenziali, genera `.env` e avvia l'applicazione.

Per esporla su Internet dietro Caddy:

1. in `.env` impostare `APP_BIND=127.0.0.1`;
2. nel `Caddyfile`:
   ```
   gestionale.example.com {
       reverse_proxy localhost:8080
   }
   ```
3. sul firewall aprire solo SSH, 80 e 443.

---

## Deploy di un aggiornamento

Il codice arriva in produzione passando da GitHub.

```bash
# 1. in sviluppo
git push origin master

# 2. sul server di produzione (via SSH), nella cartella del progetto
cd ~/cabianca-gestionale

#    se il deploy cambia lo schema del DB: copia di sicurezza coerente
docker exec cabianca-gestionale-web-1 python -c "
import sqlite3; s=sqlite3.connect('/app/data/gestionale.db'); d=sqlite3.connect('/app/data/gestionale.db.pre-deploy'); s.backup(d)"

git pull --ff-only
docker compose build --no-cache   # prima il build: il servizio resta su durante la compilazione
docker compose down
docker compose up -d

# 3. verifica
docker compose logs web --tail=50
```

Dopo il riavvio è normale vedere per circa un minuto qualche `409 Conflict` del bot: è la connessione della
vecchia istanza che Telegram non ha ancora chiuso. Se il conflitto continua, c'è un'altra istanza attiva con
lo stesso token.

**Provare in locale senza toccare la produzione**: copiare il DB di produzione in `data/_test.db` e lanciare uno
script di prova in un container usa-e-getta, con il bot disattivato:

```bash
docker compose build
docker compose run --rm --no-deps -e PYTHONPATH=/app \
  -e DATABASE_URL=sqlite:////app/data/_test.db web python /app/data/_prova.py
```

dove lo script, prima di `create_app()`, sostituisce `app.services.allevamento_bot.start_bot` con una funzione
vuota. Mai usare `docker compose up` su una macchina che non sia la produzione.

Comandi utili:

```bash
docker compose logs -f web      # log in tempo reale
docker compose ps               # stato del container
docker compose down             # ferma (i dati restano nei volumi)
```

---

## Database e migrazioni

- **SQLite** in `data/gestionale.db` (volume).
- Le tabelle nuove vengono create da `db.create_all()` all'avvio.
- Le colonne aggiunte dopo il primo deploy sono nella lista `_migrate_columns` in `app/__init__.py` (`ALTER TABLE
  … ADD COLUMN`, ignorando l'errore se la colonna esiste già). Non si usa Alembic: la cartella `migrations/` è vuota.
- Le modifiche che SQLite non supporta con `ALTER TABLE` (es. togliere un vincolo `UNIQUE`) si fanno ricostruendo
  la tabella, sempre in `_init_db()` e in modo idempotente (es. `speditori_siero`).
- Ogni migrazione deve poter girare a ogni avvio senza effetti se già applicata.

---

## Struttura del progetto

```
app/
  __init__.py          # factory create_app, init DB e migrazioni, seed, scheduler, avvio bot
  config.py            # configurazione da .env
  models.py            # tutti i modelli SQLAlchemy
  routes/              # un blueprint per area
    auth.py dashboard.py prima_nota.py fatture.py cassa.py movimenti.py ricorrenti.py
    banca.py anagrafica.py inventario.py categorie.py analisi.py scadenzario.py
    finanza_impostazioni.py impostazioni.py
    allevamento.py     # tutta la sezione Allevamento
  services/
    sdi_parser.py sdi_importer.py email_fetcher.py pdf_parser.py   # fatture elettroniche
    cbi_parser.py reconciliation.py rules_engine.py                # banca
    cloud_office.py recurring_generator.py export.py               # cassa, ricorrenti, CSV
    backup.py telegram_bot.py                                      # backup e notifiche
    allevamento_scorte.py allevamento_pasti.py allevamento_bot.py  # allevamento
  templates/           # Jinja2, tutti estendono base.html; una cartella per sezione
    components/        # sidebar_nav.html, scorta_card.html, …
  static/
    css/style.css      # branding Ca Bianca
    uploads/           # allegati e foto bolle (volume)
  utils/decorators.py  # role_required, admin_required, write_required, section_required
scripts/               # script di manutenzione una tantum
Dockerfile  docker-compose.yml  gunicorn.conf.py  setup.sh  requirements.txt
```

---

## Convenzioni di sviluppo

- Route protette con `@login_required` (+ `@write_required` / controllo `current_user.role == "admin"` dove serve).
- Ogni form POST include `csrf_token()`.
- Dopo un POST: `flash("messaggio", "success|danger|warning")` e `redirect(url_for(...))`.
- Le modifiche di registrazioni già fatte avvengono in un modal con lo stesso layout dell'inserimento.
- Stima ≠ dato reale: i valori propagati automaticamente sono salvati con `stimato=True` e mostrati in modo
  diverso, mai ricalcolati all'indietro.
- Colori: verde `#009d5a` (Finanza), rosa `#c2185b` (Allevamento). Font: Varela Round (testo), Yeseva One (titoli).

---

## Risoluzione problemi

| Sintomo | Causa probabile |
|---|---|
| `409 Conflict: terminated by other getUpdates request` continuo nei log | Un'altra istanza usa lo stesso token del bot: fermarla |
| Le modifiche al codice non si vedono | Serve `docker compose build --no-cache` + `up -d`, non `restart` |
| Backup non creati ogni notte | Controllare la frequenza in Impostazioni → Backup (`Backup saltato…` nei log) |
| Email del backup non arriva | Credenziali `SMTP_*` o destinatario in Impostazioni → Backup |
| Login impossibile in LAN via http | Impostare `COOKIE_SECURE=0` in `.env` |
| "Troppi tentativi falliti" al login | Blocco anti-forzatura: attendere 15 minuti o riavviare il container |
| Reload di Caddy fallito con `permission denied` sul log | `sudo chown caddy:caddy /var/log/caddy/access.log` |
| Foto bolla non caricata | Connessione instabile: la consegna è salvata, ricaricare la foto dall'icona 📷 |

---

## Stack tecnologico

- **Backend**: Python 3.11, Flask, SQLAlchemy, Flask-Login, Gunicorn
- **Database**: SQLite
- **Frontend**: Jinja2, Bootstrap 5.3, Bootstrap Icons, Chart.js
- **Job pianificati**: APScheduler
- **Bot**: python-telegram-bot
- **Deploy**: Docker Compose, Caddy (HTTPS)
- **Integrazioni**: SDI/FatturaPA (XML, p7m) via IMAP, 4CloudOffice, estratti conto CBI, SMTP

## Licenza

Uso interno – Fattoria Ca Bianca
