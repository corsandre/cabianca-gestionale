# Ca Bianca Gestionale

Applicazione gestionale per **Fattoria Ca Bianca**: contabilità, fatturazione elettronica, banca, magazzino e
gestione dell'allevamento suini. Web app Flask in Docker, usabile da PC e da smartphone (PWA), con un bot Telegram
per le operazioni quotidiane di stalla. Dalla versione 2.0 può collegarsi al PC dell'impianto di alimentazione
(EM2000) per leggere i consumi dei pasti e sorvegliarlo.

---

## Indice

- [Architettura e ambienti](#architettura-e-ambienti)
- [Sezioni](#sezioni)
  - [Finanza](#finanza-tema-verde)
  - [Allevamento Suini](#allevamento-suini-tema-rosa)
  - [Impianto di alimentazione](#impianto-di-alimentazione-collegamento-al-pc-dalla-20)
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
                                                                          container Docker "impianto" (stessa immagine)
                                                                              └─ servizio di sorveglianza ──SSH via ZeroTier──▶ PC impianto (EM2000)
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
- **Due container, un database.** `web` è il gestionale; `impianto` è il servizio che sorveglia l'impianto di
  alimentazione (processo separato, così un aggiornamento del gestionale non interrompe un pasto seguito). Usano la
  stessa immagine e lo stesso `data/`; il servizio parte con `RUOLO=impianto` e non avvia né scheduler né bot.
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
| Fatture emesse | `/fatture-emesse` | Copie PDF delle fatture emesse inviate per email dalla Coldiretti, lette con OCR e abbinate ai bonifici (vedi sotto) |
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

**Import CBI e quadratura** (`app/services/cbi_parser.py`, `app/services/saldo_banca.py`):
- ogni movimento ha un'impronta anti-doppione fatta con il **codice univoco della banca** (primo elemento della
  descrizione del record 62, es. `MB0B73745958`) + data + verso + importo + causale: ricaricare un estratto conto
  già importato non crea doppioni, e due operazioni vere identiche nello stesso giorno (es. due incassi POS
  uguali) entrano entrambe. Fino alla 2.3.0 l'impronta usava data/importo/causale/controparte e la seconda
  veniva scartata: alla 2.3.1 le impronte esistenti sono state ricalcolate una volta dal record originale;
- ogni file caricato viene conservato in `data/cbi/`;
- all'import il file viene verificato giorno per giorno (saldo apertura + movimenti = saldo chiusura);
- la pagina Banca divide la differenza tra saldo della banca e saldo contabile in **movimenti da riconciliare**
  (sospesi: lavoro da fare) e **differenza non spiegata** (saldo banca − apertura − tutti i movimenti
  importati: movimenti mancanti o in più, da sistemare ricaricando il CBI del periodo). L'import avvisa se
  dopo il caricamento la differenza non spiegata non è zero.

**Regole automatiche banca** (`AutoRule`, `app/services/rules_engine.py`): condizioni su descrizione/importo/fonte
che assegnano categoria, contatto, metodo di pagamento, aliquota IVA, note, spostamento data, oppure ignorano il
movimento con un motivo. Possono essere riapplicate in blocco ai movimenti esistenti.

#### Fatture emesse (`/fatture-emesse`)

Le fatture emesse non arrivano come XML: chi tiene la contabilità (Coldiretti, programma GAMMA) manda per email
una **copia PDF** di ogni fattura, e quel PDF non contiene testo vero (i caratteri sono disegni). Il gestionale:

1. **legge le email** del mittente `FATTURE_EMESSE_MITTENTE` in tutte le cartelle della casella IMAP (escluse
   cestino, spam, bozze e inviate), **in sola lettura**: le email non vengono spostate né segnate come lette,
   perché le archivia una persona. Ogni email viene elaborata una volta sola (tabella `email_elaborate`).
   Controllo automatico alle 8:35, 14:35 e 20:35, oppure con il pulsante "Controlla email";
2. **legge il PDF con OCR** (`app/services/fatture_emesse_ocr.py`: `pdftoppm` a 200 dpi + `tesseract` in
   italiano, installati nell'immagine Docker). Si leggono solo i PDF fino a 3 pagine e solo le pagine con
   l'intestazione di Fattoria Ca' Bianca (nelle stesse email arrivano anche fatture di altre aziende seguite
   dalla Coldiretti). Dal modulo si ricavano numero, data, cliente, P.IVA/codice fiscale, prima riga degli
   articoli, imponibile, IVA e totale. Se un controllo non torna (es. imponibile + IVA ≠ totale, cliente non
   letto) la fattura resta **da controllare** (riga gialla) e si corregge dalla pagina di dettaglio;
3. **conserva il PDF** in `static/uploads/fatture_emesse/` (`<anno>_<sezionale>_<numero>.pdf`), scaricabile
   dall'elenco e visibile nel dettaglio, come per le fatture ricevute;
4. **note di credito**: dalla causale ("nota di credito relativa alla fattura 42/01 del 19.05.2026") si
   collega la fattura stornata, che non va più incassata;
5. **abbina gli incassi**: per ogni fattura cerca i bonifici in entrata dello **stesso importo** da 60 giorni
   prima a 60 giorni dopo la data della fattura (di solito la fattura si emette dopo il pagamento). Si abbina
   in automatico solo se nel bonifico c'è anche il **cognome** del cliente (la prima parola in fattura) o almeno
   due parole del suo nome; un solo nome di battesimo in comune non basta. Altrimenti i bonifici
   compatibili vengono proposti nel dettaglio e si collegano a mano. Con l'abbinamento:
   - bonifico già riconciliato a mano → la fattura si collega a quella transazione (niente doppioni);
   - bonifico sospeso **o ignorato** → si crea l'entrata (categoria dalla descrizione: fattoria didattica,
     ristorazione, vendita animali/prodotti) e il bonifico diventa riconciliato. Gli ignorati sono solo
     incassi già registrati in altro modo (es. con scontrino, sincronizzati dalla cassa): se c'è una fattura,
     non lo sono;
   - "Scollega" elimina l'entrata creata dall'abbinamento e rimette il bonifico tra i sospesi;
   - "Incassata in contanti / POS / altro" per le fatture già incassate in cassa o pagate con un unico
     bonifico insieme ad altre.
   L'abbinamento gira anche dopo ogni import dell'estratto conto;
6. **numeri mancanti**: per ogni anno e sezionale (`/01` fattoria didattica e ristorazione, senza suffisso
   attività agricola, `/09` con bolla, `/50` e `/60` note di credito) segnala i numeri che non sono arrivati
   per email, in pagina e su Telegram (una volta per numero).

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
- **Brix ricalcolato sui pasti**: ogni volta che un carico di siero viene registrato, modificato, chiuso o eliminato
  (dal web o dal bot), Brix di riferimento e % di sostituzione di ogni pasto vengono ricalcolati dal carico a cui il
  suo siero è attribuito (`ricalcola_brix_pasti` in `allevamento_pasti.py`). Così non conta l'ordine in cui si
  inseriscono le cose: un pasto letto o inserito prima di registrare il carico prendeva il Brix del carico precedente.
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

#### Orari dei pasti e attribuzione del siero ai carichi
Il gestionale non registra quando la cucina distribuisce davvero un pasto: ogni pasto ha un **istante**, che è
il giorno più l'orario standard di Impostazioni (es. pasto 2 alle 12:50). Da quell'istante dipendono: se il pasto
è già avvenuto (righe sbiadite e scorte), giacenze e stime di mangime e siero, e **da quale carico di siero viene
scalato**. Il calcolo sta tutto in `app/services/allevamento_scorte.py` (docstring del modulo).

- **Orario effettivo.** Se un pasto viene dato a un'altra ora (es. rimandato per aspettare lo scarico del siero),
  in Alimentazione si clicca l'orario sotto "Pasto N" (in giallo quello standard presunto, in bianco quello
  effettivo inserito, come per le celle stimate/inserite) e si indica l'ora reale di quel giorno
  (`OrarioPastoEffettivo`, tabella `orari_pasto_effettivi`; vale per tutte le linee). L'orario effettivo sostituisce
  quello standard ovunque, perché `_datetime_pasto()` è l'unico punto che calcola l'istante di un pasto. Si toglie
  con "Torna all'orario standard".
- **Carico di siero = intervallo [arrivo, chiusura).** Un carico si chiude all'arrivo del successivo (la cisterna si
  svuota sempre prima) o con "cisterna vuota" segnata a mano. Un pasto nello stesso minuto dell'arrivo appartiene
  al carico nuovo.
- **Regole di attribuzione** (`attribuzione_siero()`, una sola funzione usata sia per la giacenza del carico aperto
  sia per consumo e scarto dei carichi chiusi):
  1. il siero di un pasto va al carico aperto nell'istante del pasto;
  2. **rete di sicurezza**: se in quell'istante nessun carico era aperto (cisterna segnata vuota, carico nuovo non
     ancora arrivato) ma il pasto ha usato siero, quel siero non può che venire dal carico successivo e viene
     attribuito lì. In Consegne, nella colonna Periodo del carico compare "incl. pasto N del gg/mm, dato a cisterna
     vuota";
  3. se il carico successivo non è ancora stato registrato, il pasto resta non attribuito finché non arriva
     (idem per i pasti precedenti al primo carico in assoluto).
  Contano solo i pasti avvenuti e completi su tutte le linee con animali.
- **Avvisi alla registrazione di un carico** (web e bot, `avvisi_nuovo_carico_siero()`): segnala i pasti attribuiti
  al carico perché dati a cisterna vuota, e l'ultimo pasto con siero nelle 3 ore prima dell'arrivo rimasto nel carico
  precedente, che potrebbe essere stato rimandato. In entrambi i casi suggerisce di indicare l'orario effettivo.
- **Bot**: un carico registrato da Telegram prende come ora di arrivo l'ora della registrazione e chiude il carico
  precedente, come dal web.

Esempio (30/09): carico precedente segnato vuoto il 29/09 alle 18:37, carico nuovo arrivato alle 14:43, pasto 2
rimandato a dopo lo scarico ma con orario standard 12:50. Senza orario effettivo il pasto cade a cisterna vuota e la
regola 2 lo attribuisce al carico nuovo; con orario effettivo 14:50 cade direttamente nel carico nuovo.

#### Alimentazione (`/allevamento/alimentazione`)
- Consumi reali per **pasto (1/2/3) e linea**: mangime, siero, acqua (quintali). Un pasto conta come completo solo
  quando tutte le linee attive hanno un valore e l'orario configurato è passato.
- I pasti non inseriti vengono stimati copiando l'ultimo reale (`stimato=True`), mai in modo retroattivo.
- % di sostituzione della sostanza secca con il siero calcolata sul consumo reale e sulla % s.s. del carico in uso.
- Sotto ogni pasto, in grigio, la **sostanza secca** per linea e totale: kg di s.s. (mangime alla % s.s. impostata
  in Impostazioni, default 100%, + siero alla % Brix del suo carico) e kg di s.s. per capo, sui suini presenti
  nei capannoni della linea in quel giorno (ricostruiti da censimento, mortalità e spostamenti fino a quella data).
  Sotto il totale gli stessi valori per l'intera giornata.
- Nella stessa riga grigia il **rapporto di diluizione** «10:32»: kg di liquido (acqua + parte acqua del siero,
  cioè siero × (100 − Brix)%) ogni 10 kg di sostanza secca, come il «rapporto 10:» delle ricette di EM2000. Con il
  collegamento all'impianto accanto c'è il valore impostato sul PC per la ricetta in uso, ed è in rosso quando viene
  superato: succede quando il siero da solo porta più liquido del necessario e l'acqua aggiunta va a zero (es. siero
  a Brix basso). Validato sui pasti letti dal PC: con acqua aggiunta i pasti stanno a 32,1–32,6 con 32 impostato.
- In cima, due schede **«Brix del siero»** e **«Sostituzione con siero»** che seguono il giorno scelto: grafico della
  sua settimana (da lunedì a domenica, giorno scelto evidenziato) con i valori applicati davvero, dai consumi
  registrati, e il valore del giorno; per oggi quello letto dal PC, con l'ora dell'ultima lettura e dell'ultimo cambio
  (`app/services/allevamento_siero_schede.py`).
- Con il collegamento attivo, pulsante **«Aggiorna dal PC»** e pannello delle letture dell'impianto (vedi sotto).

#### Razione box (`/allevamento/razione`)
- Percentuale di razione per box, in una griglia settimanale.
- Oggi resta modificabile; appena un giorno passa senza inserimento, per ogni box viene salvata una riga reale
  con l'ultimo valore noto (`stimato=True`, celle evidenziate in giallo). Correggere un giorno passato non
  ricalcola i giorni successivi.

#### Trattamenti (`/allevamento/trattamenti`)
- Registro dei trattamenti (`Medicinale`, `Trattamento`, `Somministrazione`) per box o intero capannone.
- Dose per capo e totale = ml/kg × peso medio × numero animali; dosi da ripetere in evidenza; periodo di
  sospensione prima del macello.
- Modifica, chiusura anticipata con motivazione (accodata alle note) e casella «Deceduto» (animale morto: nessun
  periodo di sospensione), eliminazione.
- **Più medicinali per lo stesso animale**: nel nuovo trattamento si aggiungono più righe medicinale, ognuna con la
  sua dose (ml/kg), i suoi giorni di somministrazione e di sospensione. Ogni medicinale resta un `Trattamento` a sé,
  quelli dati insieme hanno lo stesso `gruppo` (icona 🔗 nell'elenco); la sospensione prima del macello che conta è la
  più lunga. Il bot permette di scegliere più medicinali nello stesso percorso.
- **Colore del marcatore** (🔵 blu, ⚫ nero, 🔴 rosso): se nello stesso box si trattano più animali, ognuno ha il suo
  colore; sulla schiena si fa una riga per ogni giorno di trattamento (1ª riga il primo giorno, 2ª il secondo…, di
  solito al massimo 3). Per un nuovo trattamento viene proposto un colore non ancora usato nel box; il colore vale per
  tutti i medicinali dello stesso animale. La procedura è spiegata in cima alla pagina.
- **Promemoria del mattino** (all'orario di Impostazioni → Avvisi giornalieri, default 07:00) nel gruppo
  dell'allevamento, una riga per animale: «box 30, maiale ⚫ nero: Cloxacillina dose 2 di 3; Micospectone dose 2 di 5
  → fai la 2ª riga». Nel bot, «Da fare oggi» elenca gli animali e registra in un colpo la dose di tutti i loro
  medicinali (`app/services/allevamento_trattamenti.py`).

#### Analisi (`/allevamento/analisi`)
- Pagina di grafici interattivi sul ciclo attivo, con una riga di filtri che vale per tutta la pagina: periodo
  (7 / 14 / 30 giorni / tutto il ciclo), linea (tutte o una) e valori per capo o totali. La scelta resta salvata
  nel browser.
- Indicatori con sparkline e confronto col periodo precedente: capi presenti (con "tutto il ciclo" si parte da 0
  e si vedono gli entrati), mortalità in % dei capi a inizio periodo più gli entrati, uscite per tipo con i kg,
  farina al giorno e per capo nel periodo, siero e sostanza secca al giorno, % di sostituzione con siero. Il filtro
  "per capo / totali" decide quale dei due valori mostrano.
- Rapporto di diluizione per linea giorno per giorno, con il valore impostato sul PC tratteggiato.
- Andamento dei capi (a gradini, punti nei giorni con consegne, morti o uscite) con il bilancio del periodo:
  inizio + entrati − morti − usciti = fine (le "rettifiche" sono le differenze trovate ai censimenti o, per una
  linea, gli spostamenti tra linee). Gli entrati sono i censimenti che aumentano i capi (consegne di suinetti)
  più gli spostamenti di tipo entrata.
- Consumi al giorno di farina, siero e acqua e tabella del consumo nel periodo: totale, per capo (ogni giorno il
  consumo diviso i capi di quel giorno, poi sommato) e per capo al giorno.
- Grafici: sostanza secca al giorno per linea, s.s. in % del peso vivo stimato, s.s. da farina e da siero,
  % di sostituzione per linea, crescita dei componenti della razione (indice base 100 con media mobile a 3 giorni),
  medie per pasto, mortalità nel tempo (giornaliera o settimanale), mortalità per capannone con elenco degli eventi,
  riepilogo settimanale (con usciti e farina kg/capo/g). Ogni grafico ha una vista tabella.
- Le linee hanno i loro colori (1 blu, 2 rossa, 3 verde) più un simbolo diverso (● ▲ ■), perché rosso e verde non
  bastano per chi ha difficoltà a distinguere i colori. Palette verificata con lo strumento della skill dataviz.
- I dati grezzi giornalieri li prepara `app/services/allevamento_analisi.py`; aggregazioni e filtri sono calcolati nel
  browser, quindi cambiare filtro non ricarica la pagina. La giornata in corso è esclusa dalle medie.

#### Impostazioni allevamento (`/allevamento/impostazioni`, solo admin)
- Apertura/chiusura ciclo.
- Curva di accrescimento (età in giorni → peso in kg).
- Medicinali (ml/kg, giorni di somministrazione e sospensione).
- Scorte: capacità silos, soglia di riordino (in pasti, così segue l'aumento dei consumi), quantità per ordine,
  soglia di scarto siero, orari dei 3 pasti.
- Avvisi giornalieri: orario (default 07:00) del messaggio con i trattamenti da ripetere nel giorno
  (`app/services/allevamento_avvisi.py`, nessun messaggio se non ce ne sono).
- Impianto di alimentazione: modalità del collegamento, indirizzo del PC, chiave, prova (vedi sotto).

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
| `UsoPasto` | `uso_pasti` | Consumo per pasto/linea, reale o stimato; `fonte` = `impianto` se letto dal PC di alimentazione |
| `RazioneBox` | `razioni_box_v2` | % razione per box e giorno, reale o stimata |
| `Medicinale` | `medicinali` | Farmaci disponibili |
| `Trattamento` / `Somministrazione` | `trattamenti` / `somministrazioni` | Corso di cura (un medicinale; `gruppo` = medicinali dati insieme allo stesso animale, `colore` = marcatore, `deceduto`) e singole dosi |
| `ImpiantoControllo` | `impianto_controlli` | Controlli periodici dell'impianto (raggiungibile, stato, orologio, orari) |
| `ImpiantoLinea` | `impianto_letture_linee` | Quantitativi letti per pasto e linea: proposta → approvata/scartata, o registrata |
| `ImpiantoEvento` | `impianto_eventi` | Eventi dei pasti e anomalie, con la fotografia dello schermo |

#### Servizi (`app/services/`)

| File | Contenuto |
|---|---|
| `allevamento_scorte.py` | Giacenze mangime/siero, curva di accrescimento (`peso_da_giorni`, `giorni_da_peso`), `pasto_completo`, stime di esaurimento e spazio per il carico, ricalibrazioni, scarto dei carichi di siero |
| `allevamento_pasti.py` | Registrazione pasti, stime dei pasti mancanti, calcolo % siero |
| `allevamento_bot.py` | Bot Telegram dell'allevamento |
| `allevamento_analisi.py` | Dati giornalieri per la pagina Analisi (capi, età, pasti, entrate, uscite, morti) |
| `allevamento_siero_schede.py` | Schede Brix e sostituzione di Alimentazione (valore attuale e 15 giorni) |
| `allevamento_trattamenti.py` | Più medicinali per animale, colore del marcatore, dosi da ripetere per animale |
| `allevamento_avvisi.py` | Avviso del mattino con i trattamenti da ripetere |
| `impianto/` | Collegamento all'impianto di alimentazione (vedi sotto) |

---

### Impianto di alimentazione (collegamento al PC, dalla 2.0)

L'impianto di alimentazione (software **EM2000**, su un PC Linux) prepara e distribuisce i pasti. Il gestionale può
collegarsi al PC **in sola lettura**: fotografa lo schermo, ne legge i valori e segue i pasti. Sul PC non viene
scritto niente e non resta nessun file (la fotografia viaggia compressa sulla connessione SSH).

**Tre modalità** (Impostazioni allevamento → *Impianto di alimentazione*):

| Modalità | Cosa fa |
|---|---|
| **Manuale** (default) | Nessuna connessione al PC: il gestionale funziona come senza impianto collegato. Per le aziende che non hanno il collegamento |
| **Automatico con verifica** | Sorveglianza completa e messaggi, ma i consumi letti sono *proposte* da approvare o scartare in Alimentazione |
| **Automatico** | I consumi letti entrano direttamente come dati reali (`fonte = impianto`). Un pasto già inserito a mano non viene toccato |

**Cosa fa il servizio** (`app/services/impianto/servizio.py`, container `impianto`):
- *Controllo periodico* (default ogni 60 minuti, 5 se il PC non risponde): fotografia dello schermo e orari dei pasti
  impostati sull'impianto, salvati in `impianto_controlli`. Tra un controllo e l'altro rilegge ogni 10 minuti solo
  gli orari, il Brix del siero e la % del siero nelle ricette: un pasto anticipato viene seguito dall'inizio e un
  cambio di Brix o sostituzione viene segnalato. Riepilogo giornaliero, impianto non raggiungibile (dopo 3
  tentativi) e di nuovo raggiungibile, orologio del PC spostato.
- *Aggiorna dal PC*: pulsante in Alimentazione e nelle impostazioni dell'impianto, e nel bot Telegram: il servizio
  rilegge subito schermata, orari, Brix e ricette e risponde nel gruppo entro un minuto. Se il servizio riparte a
  pasto in corso lo segue senza mandare di nuovo «iniziato» né gli avvisi già inviati.
- *Schermata*: EM2000 va lasciato su «Situazione impianto» (controllata anche dal controllo leggero ogni 10 minuti).
  Se è altrove arriva un avviso con la fotografia che dice dove: Menu principale (dal titolo grande), una pagina di
  gestione riconosciuta dal **titolo della finestra** («Modifica orari distribuzione», «Visualizza dati box»,
  «Modifica dati ricette»…; per un titolo nuovo «un'altra pagina»), oppure la schermata «Situazione impianto» con il
  contenuto **scorso fuori posizione** (titolo giusto ma niente leggibile). I controlli diventano ogni 5 minuti e,
  appena torna giusta, arriva una conferma con la foto; se ricapita lo stesso giorno si riavvisa.
- *Orari dei pasti*: con il collegamento attivo quelli del gestionale sono gli orari impostati sul PC (il servizio li
  copia a ogni controllo; in Impostazioni allevamento sono in sola lettura; con un numero di pasti diverso da 3 non si
  cambia niente e lo si dice). Un pasto spostato a ridosso e trovato dal controllo dei 10 minuti ancora sulla linea 1
  in preparazione vale come inizio vero («Pasto iniziato» e orario effettivo); un pasto avanzato trovato dopo un
  riavvio viene seguito senza «iniziato».
- *Pasto*: da qualche minuto prima dell'orario (convertito in ora reale con lo scarto dell'orologio del PC) una
  fotografia ogni 60 secondi finché l'impianto torna in attesa. Fine di ogni linea: i quantitativi letti più volte
  uguali (dalla miscelazione in poi, solo se acqua + siero + farina = totale) diventano la lettura della linea.
  Messaggi: inizio pasto, per ogni linea fine del carico dei componenti (inizio miscelazione) e «tra 1 minuto
  riempimento dei tubi» (durata della miscelazione dalla ricetta, Ricette.DB; foto ogni 20 s durante il carico per
  cogliere l'inizio; disattivabili con «Messaggi dei pasti: essenziali»), fine di ogni linea con i quantitativi,
  riepilogo. Siero sotto 0,15 q su una linea = non erogato (residuo a cisterna vuota), registrato nell'acqua e mai
  attribuito a un carico. **Tutti i messaggi dell'impianto**
  vanno nel gruppo scelto nelle impostazioni (default *allevamento*).
- *Avvisi*: pasto non partito, orari dei pasti cambiati o pasto saltato, cisterna del siero o silos **finiti ora**
  (con orario e quantità: solo se hanno dato una parte vera della dose, non i pochi kg che pompa e coclea tirano
  quando sono già vuote), **di nuovo in uso** quando tornano a dare la dose piena; finché restano vuoti **ancora
  vuoto** una volta al giorno; silos **saltato da EM2000** (coclea a 0) (EM2000 ricorda la sostituzione e non riprova
  la coclea finché non finiscono gli altri silos, quindi una coclea a 0 non vuol dire silos vuoto); **dosaggio di siero o
  farina inferiore al previsto** solo se mancano almeno 0,5 q e non c'è una riga SOS (con la riga SOS il componente è
  finito davvero; senza SOS e con poca differenza è solo l'errore di stima del «volo», cioè di quanto cade dopo la
  chiusura); fase bloccata, stato mai visto, **lettura incompleta** (una schermata riconosciuta in cui qualcosa non si
  legge: va insegnata al lettore); cambi di Brix, di % del siero e del **rapporto di diluizione** delle ricette. Le
  anomalie arrivano con la fotografia.
- *Orario effettivo*: per ogni pasto letto viene registrato l'orario effettivo (inizio della linea 1). Serve ad
  attribuire il siero al carico giusto anche quando gli orari standard cambiano dopo (seguono quelli del PC).
- *Ricetta in uso*: riconosciuta dai componenti della tabella (es. SIERO + COCLEA 1 = «ricetta 2 siero»); da Ricette.DB
  si leggono durata della miscelazione e rapporto di diluizione impostato (setting `impianto_ricetta`).

**Come si legge lo schermo** (`app/services/impianto/em2000/schermo.py`): il carattere di EM2000 è una bitmap
fissa, quindi ogni carattere si riconosce per confronto esatto con un campionario (`em2000/campionario.json`); le
frasi di stato in grassetto, dove le lettere si toccano, si riconoscono intere. La tabella della ricetta si legge
riga per riga dal nome (ACQUA, SIERO, COCLEA n, TOTALI RICETTA). Quando un componente finisce durante il dosaggio,
EM2000 aggiunge righe **SOS** che lo sostituiscono: siero finito → acqua (la parte acqua del siero) + farina (la sua
sostanza secca); silos finito → un'altra coclea (coclea 1 = silos A, 2 = B, 3 = C). Ogni riga SOS sostituisce la
riga più vicina sopra di lei che non ha dato tutta la dose, anche se è a sua volta una SOS (catena coclea 1 →
coclea 3 → coclea 2 quando finisce anche il silos della coclea 3). Il teorico viene solo dalle righe della ricetta, il reale da tutte le righe
di quel materiale.

**Insegnare una schermata nuova**: salvare la schermata (PNG), aggiungere in `scripts/em2000_addestra.py` i testi
che contiene e rilanciare lo script. Se un testo non si allinea ai caratteri trovati il campionario non viene
salvato.

**Configurazione del collegamento**
1. Il PC dell'impianto e il server devono essere sulla stessa rete privata (es. ZeroTier). Sul server, con `ufw`,
   va aperta la porta UDP di ZeroTier (`sudo ufw allow 9993/udp`), altrimenti il server non comunica con gli altri
   nodi della rete.
2. Chiave SSH: da Impostazioni (*Crea la chiave*) oppure con `ssh-keygen -t ed25519 -f data/impianto/chiave`.
   La chiave privata resta in `data/impianto/` (mai nel repository).
3. Sul PC, nel file `~/.ssh/authorized_keys` dell'utente con cui ci si collega, una riga con la chiave pubblica,
   limitata all'indirizzo del server e senza tunnel:
   ```
   from="<IP del server nella rete privata>",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAA… gestionale
   ```
   Per togliere l'accesso basta cancellare la riga.
4. In Impostazioni: indirizzo e utente del PC, modalità, poi **Prova ora** (si collega anche in Manuale, solo su
   richiesta). La chiave dell'host del PC viene memorizzata in `data/impianto/known_hosts` al primo collegamento.
5. Docker: la rete dei container ha MTU 1280 (`docker-compose.yml`), perché sulla rete ZeroTier pacchetti più grandi
   si perdono e la fotografia dello schermo non arriva.

Stato che il servizio ricorda nelle impostazioni (`settings`): `impianto_vuoto_siero` e `impianto_vuoto_silos_<n>`
(da quando la cisterna o un silos sono vuoti). Fotografie delle anomalie in `data/impianto/anomalie/`.

| File | Contenuto |
|---|---|
| `services/impianto/__init__.py` | Impostazioni, modalità, creazione del lettore, chiave |
| `services/impianto/base.py` | Modalità, fasi del pasto, `LetturaSchermo` (righe, sostituzioni, problemi di lettura) |
| `services/impianto/em2000/` | Lettore EM2000: SSH (paramiko), fotografia, lettura dello schermo, tabelle Paradox (orari) |
| `services/impianto/pasto.py` | `TracciaPasto`: segue il pasto lettura per lettura ed emette gli eventi |
| `services/impianto/registrazione.py` | Dalle letture ai consumi del gestionale (proposte, registrazione, orario effettivo) |
| `services/impianto/servizio.py` | Il servizio: controlli, pasti, messaggi, anomalie |
| `routes/impianto.py` | Impostazioni, chiave, prova, fotografie, approvazione/scarto delle letture |

---

## Bot Telegram

Due usi dello stesso bot (`TELEGRAM_BOT_TOKEN`), su tre gruppi Telegram (allevamento, finanza, notifiche di sistema):

1. **Notifiche** (`app/services/telegram_bot.py`, `send_telegram_message(testo, canale=...)`), inviate a gruppi dedicati:
   - canale `finanza` → `TELEGRAM_CHAT_ID` (gruppo *Finanza*): scadenze arretrate e dei prossimi 7 giorni, avvisi banca
     (import CBI mancante, movimenti da riconciliare, esito import), scorte basse dell'inventario, sincronizzazione
     cassa, fatture SDI importate da email;
   - canale `sistema` → `TELEGRAM_SISTEMA_CHAT_ID` (gruppo *Notifiche sistema*): backup e notifiche tecniche del server;
   - canale `allevamento` → `TELEGRAM_GROUP_ID` (gruppo dell'allevamento): tutti i messaggi dell'impianto di
     alimentazione (pasti, silos, siero, stato, anomalie con la fotografia dello schermo, `send_telegram_foto`) e
     ogni mattina i trattamenti da ripetere.
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
| configurabile (default 07:00) | Trattamenti da ripetere nel giorno (gruppo allevamento) | Controllato ogni minuto, inviato una volta al giorno |
| 08:30, 14:30, 20:30 | Recupero fatture SDI da email (IMAP) | Solo se configurato IMAP |
| 08:35, 14:35, 20:35 | Fatture emesse da email (OCR) e abbinamento ai bonifici | Solo se configurati IMAP e `FATTURE_EMESSE_MITTENTE` |

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
- `ufw`: aperte solo SSH, 80, 443 e la porta UDP di ZeroTier (9993) per il collegamento all'impianto.
- **PC dell'impianto**: accesso con chiave limitata all'indirizzo del server e senza tunnel; il servizio esegue solo
  la fotografia dello schermo e la lettura di file.
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
| `FATTURE_EMESSE_MITTENTE` | Indirizzo da cui arrivano le copie PDF delle fatture emesse (vuoto = funzione spenta) |
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
docker compose ps
docker compose logs web impianto --tail=50
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
docker compose logs -f web      # log in tempo reale del gestionale
docker compose logs -f impianto # log del servizio dell'impianto di alimentazione
docker compose ps               # stato dei container
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
    impianto.py        # impostazioni e letture dell'impianto di alimentazione
  services/
    sdi_parser.py sdi_importer.py email_fetcher.py pdf_parser.py   # fatture elettroniche
    cbi_parser.py reconciliation.py rules_engine.py                # banca
    cloud_office.py recurring_generator.py export.py               # cassa, ricorrenti, CSV
    backup.py telegram_bot.py                                      # backup e notifiche
    allevamento_scorte.py allevamento_pasti.py allevamento_bot.py  # allevamento
    allevamento_analisi.py
    impianto/          # collegamento all'impianto di alimentazione (servizio, lettore EM2000)
  templates/           # Jinja2, tutti estendono base.html; una cartella per sezione
    components/        # sidebar_nav.html, scorta_card.html, …
  static/
    css/style.css      # branding Ca Bianca
    uploads/           # allegati e foto bolle (volume)
  utils/decorators.py  # role_required, admin_required, write_required, section_required
scripts/               # script di manutenzione; em2000_addestra.py costruisce il campionario dello schermo
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
| Impianto "non raggiungibile" | PC spento o rete privata giù; dal server `ping` del PC. Se il ping non passa, controllare la porta UDP di ZeroTier su `ufw` |
| Fotografia dello schermo che non arriva (timeout) | MTU della rete Docker: deve restare 1280 (`docker-compose.yml`) |
| "Lettura incompleta" su Telegram | Schermata nuova o cambiata: insegnarla con `scripts/em2000_addestra.py` |

---

## Stack tecnologico

- **Backend**: Python 3.11, Flask, SQLAlchemy, Flask-Login, Gunicorn
- **Database**: SQLite
- **Frontend**: Jinja2, Bootstrap 5.3, Bootstrap Icons, Chart.js
- **Job pianificati**: APScheduler
- **Bot**: python-telegram-bot
- **Deploy**: Docker Compose, Caddy (HTTPS)
- **Integrazioni**: SDI/FatturaPA (XML, p7m) via IMAP, 4CloudOffice, estratti conto CBI, SMTP, impianto di
  alimentazione EM2000 (SSH con paramiko, lettura dello schermo con Pillow)

## Licenza

Uso interno – Fattoria Ca Bianca
