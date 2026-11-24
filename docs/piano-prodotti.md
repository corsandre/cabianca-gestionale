# Piano: gestionale a moduli (3.3.3 → 3.4.x) e modulo "Prodotti" 1.0.0 (ricettario, libro lotti, etichette)

## Contesto
Fattoria Ca' Bianca produce e trasforma prodotti per la vendita: marmellate, mostarde, passate, sottoli e sottaceti, pasta ripiena, salumi, farine e prodotti da forno. Oggi le etichette sono file Illustrator e PDF sparsi in `~/Desktop/etichette/Etichette prodotti` (circa 70 cartelle). I formati dei codici lotto sono diversi tra loro e non esiste un registro unico dei lotti con le materie prime usate.

In caso di controllo NAS o ATS serve:
- un **libro dei lotti** con la tracciabilità "un passo indietro": per ogni ingrediente, il fornitore e il suo lotto (Reg. CE 178/2002);
- un **ricettario**;
- **etichette** conformi al Reg. UE 1169/2011.

L'obiettivo è una nuova sezione del gestionale, **Prodotti**, protetta da un permesso dedicato. Deve essere comoda: si crea un lotto partendo da un prodotto già fatto, o da uno nuovo, e si ottiene subito l'etichetta in PDF, che resta archiviata.

Le decisioni sono state prese con Andrea il 24/11/2026:
- **Stile:** nuovo e accattivante, con sfondo **bianco** per risparmiare toner. Lo stile deve poter essere aggiornato nel tempo, come modelli con versione.
- **Stampa:** fogli A4 **pretagliati**. Propongo io i formati da acquistare (vedi sotto).
- **Tracciabilità:** per ogni lotto si registrano gli ingredienti con fornitore e lotto del fornitore. La ricetta si sceglie dal ricettario quando si crea il lotto.
- **Inventario:** si registra **solo la produzione**, cioè quanti pezzi fa ogni lotto. Non c'è giacenza né scarico delle vendite.
- **Codice lotto:** `L` + data GGMMAA + `-` + sigla, ad esempio `L241126-ZUC`. Il gestionale lo propone e si può modificare.
- **Ingredienti in etichetta:** il testo è generato in automatico dalla ricetta, in ordine di peso decrescente e con gli allergeni in grassetto. Si può **modificare per ogni lotto**.
- **Catalogo iniziale:** lo estraggo io dalle etichette esistenti e lo preparo come bozza da ricontrollare.
- **Extra:** ricerca per i **richiami**, **export del libro lotti** (molto importante) ed **export delle ricette**. Le finestre per creare ricette, lotti ed etichette vanno curate bene.
- **Esclusi per ora:** il bollino tondo per il tappo e la stampa da una posizione N del foglio.

## Architettura a moduli: aggiornare Prodotti senza disturbare allevamento e gestionale

**Il problema oggi.** Un deploy fa `docker compose down` e poi `up` di tutto (README righe 884–916). Il container `web` contiene insieme:
- il sito;
- lo scheduler (cassa, email, fatture, avvisi allevamento);
- il bot Telegram dell'allevamento (`app/__init__.py:497–613`).

Anche il container `impianto` viene fermato. Quindi ogni aggiornamento interrompe il bot e i lavori programmati, e ogni modifica dello schema tocca `gestionale.db`.

**Altri problemi trovati analizzando il codice:**
- Il backup (`app/services/backup.py:32`) fa `shutil.copy2` del solo `gestionale.db` mentre il DB è in uso, e non copia gli allegati.
- `_init_db()` (`app/__init__.py:195`) gira a ogni avvio **in ogni processo**: anche `impianto` esegue ALTER TABLE e ricostruzioni su `gestionale.db` mentre li esegue `web`. È una corsa già presente oggi, nascosta da `except OperationalError: pass`.
- `db.create_all()` di Flask-SQLAlchemy 3.1 crea le tabelle di **tutti** i database. Se si aggiungesse un secondo DB, verrebbe creato "a sorpresa" senza migrazioni.
- SQLite non ha né WAL né `busy_timeout`, anche se ci scrivono già due processi.

**Architettura scelta (approvata il 24/11/2026): "modulo isolato + container servizi".**
Prodotti è isolato **nel codice e nel database** ma gira dentro il sito. Bot, scheduler e impianto vivono in container separati dal sito. Il risultato:
- aggiornare Prodotti, o il gestionale, riavvia **solo il sito** (3–5 secondi);
- bot Telegram, avvisi, backup, cassa, email e impianto non si fermano.

Abbiamo scartato un container dedicato a Prodotti: costerebbe immagini da tenere allineate, link del menu che non funzionano tra container, CSRF tra due origini e una pagina d'errore per il 502, e non porterebbe vantaggi reali a chi aggiorna da solo. Il pacchetto e il DB separati lasciano comunque la porta aperta: passare a un container dedicato in futuro richiederebbe solo modifiche al compose e a Caddy.

### Componenti
1. **Pacchetto modulo** `app/moduli/prodotti/`, che contiene:
   - `__init__.py` con `registra(app)` e `migra(app)`;
   - `routes.py`, `models.py`, `schema.py` (migrazioni), `services/`, `templates/prodotti/`, `static/`, `version.py`.

   Regole:
   - il modulo importa solo il **nucleo** (`app.models.User/Contact`, `app.utils.decorators`, `base.html`, `style.css`) e il nucleo non importa mai il modulo;
   - fra moduli diversi non ci sono import;
   - il registro dei moduli in `app/moduli/__init__.py` (`MODULI_DISPONIBILI = {"prodotti": ...}`) è l'unico punto di contatto;
   - **le versioni sono separate:** `prodotti 1.0.0` in `app/moduli/prodotti/version.py`, con `NUCLEO_MIN = "3.4.0"`;
   - i commit iniziano con `prodotti 1.0.1: …`.
2. **Database separato** `data/prodotti.db`, configurato con `SQLALCHEMY_BINDS` in `app/config.py`. I modelli hanno `__bind_key__ = "prodotti"`.
   - Dal DB principale si leggono solo `User` e `Contact` (fornitori).
   - Il nome del fornitore viene **copiato come testo** nelle righe del lotto, così il registro resta completo anche se l'anagrafica cambia o un contatto viene cancellato.
   - SQLite non supporta chiavi esterne tra due file, quindi i collegamenti sono id più copia testuale.
3. **Ruoli dei processi** (variabile `RUOLO`, che per default vale `web`):

   | RUOLO | Container | Cosa fa |
   |---|---|---|
   | `web` | `web` | solo il sito; **unico proprietario dello schema di `gestionale.db`** (esegue `_init_db_nucleo`) e delle migrazioni dei moduli attivi |
   | `servizi` | `servizi` (nuovo) | scheduler APScheduler, bot Telegram, avvisi, backup; niente gunicorn; non migra niente |
   | `impianto` | `impianto` | come oggi, ma **non esegue più `_init_db`** |
   | `sviluppo` | locale | sito con tutti i moduli, senza scheduler né bot (per non entrare in conflitto con il bot di produzione) |

   `MODULI=prodotti` (env) dice quali moduli registra il sito, quindi un modulo si può spegnere senza toccare il codice.
4. **Le migrazioni del modulo hanno una versione** (`app/moduli/prodotti/schema.py`) e non seguono la lista di ALTER del nucleo:
   - la tabella `schema_versione` sta in `prodotti.db`, insieme alla lista ordinata `MIGRAZIONI = [(1, m001), (2, m002), ...]`, scritta in SQL esplicito e non con `create_all`;
   - `migra()` apre `BEGIN IMMEDIATE`. Se ci sono migrazioni da applicare, **prima fa una copia** `backups/prodotti_pre_v{n}_{data}.db` (con l'API di backup di sqlite3), poi applica ogni passo in una transazione e lo registra;
   - **guardia:** se il DB ha una versione più nuova del codice (dopo un rollback dell'immagine), il modulo **non si avvia** e manda un avviso sul canale Telegram "sistema". Il resto del sito continua a funzionare;
   - regola: **le migrazioni aggiungono soltanto** (niente DROP o RENAME), così tornare all'immagine precedente è sicuro senza ripristinare i dati.
5. **Il registro legale non si cancella.**
   - Trigger SQLite in m001: `BEFORE DELETE ON lotti` → `RAISE(ABORT)`, e lo stesso per le righe ingredienti dei lotti e per le stampe.
   - Un lotto sbagliato si **annulla** (`stato=annullato` con motivo e utente) oppure si corregge con una riga "rettifica" che rimanda all'originale. La storia rimane visibile.
6. **SQLite più robusto**, con un evento `connect` su `Engine` in `app/__init__.py`:
   - `PRAGMA busy_timeout=10000` e `journal_mode=WAL` per entrambi i DB;
   - `synchronous=FULL` su `prodotti.db`.

   Per tornare indietro basta `PRAGMA journal_mode=DELETE`.
7. **Backup corretto** (`app/services/backup.py`):
   - usa `sqlite3.connect(src).backup(dst)` invece di `copy2`, che con WAL perderebbe dati, e controlla la copia con `PRAGMA integrity_check`;
   - copre **tutti** i `data/*.db`, cioè gestionale e prodotti, e manda entrambi per email;
   - **in più**, ogni settimana fa un archivio `tar.gz` dei PDF delle etichette;
   - tiene 7 copie giornaliere e 12 mensili;
   - lo esegue il container `servizi`.
8. **Deploy, con due script:**
   - `scripts/deploy.sh sito`: è il caso normale, sia per Prodotti sia per il gestionale. Esegue:
     1. una copia di sicurezza dei DB;
     2. `docker compose build web`;
     3. `docker tag … :precedente`;
     4. `docker compose up -d --no-deps web`;
     5. un controllo di `/salute` per 30 secondi.

     Servizi e impianto restano accesi.
   - `scripts/deploy.sh tutto`: si usa quando cambiano bot, scheduler, impianto o le dipendenze di sistema. Fa la procedura completa di oggi.
   - Lo script **sceglie da solo** con `git diff --name-only <tag deploy-servizi>..HEAD`: se sono cambiati file usati da `servizi` o `impianto` (`app/services/allevamento_bot.py`, `app/services/impianto/`, scheduler, `requirements.txt`, `Dockerfile`, `app/models.py`), lo dice e propone "tutto".
   - Le immagini hanno un **tag di versione** (`cabianca-gestionale:3.4.0` più `:precedente`), non solo `latest`. Così `servizi` e `impianto` non prendono per sbaglio il codice nuovo al loro prossimo riavvio.
9. **Un modulo guasto non blocca il sito.** La registrazione e la migrazione di ogni modulo sono protette da `try/except`. Se Prodotti non parte, il gestionale parte lo stesso senza la sezione Prodotti e arriva un avviso sul canale Telegram "sistema".
10. **Versioni e salute.**
   - `/salute` (senza login, JSON minimo) restituisce nucleo, moduli, versione dello schema e stato dei DB.
   - Il piè di pagina mostra "gestionale 3.4.0 · prodotti 1.0.0".
   - Il messaggio di avvio su Telegram (`app/services/avvio.py`) dice anche "Prodotti aggiornato da X a Y (schema vN)".
11. **Rollback:**
    1. solo codice: `docker tag …:precedente` e poi `up -d --no-deps web`. È sicuro grazie alle migrazioni "solo aggiunte";
    2. migrazione sbagliata: si ripristina `backups/prodotti_pre_vN_*.db` (dopo aver cancellato `-wal` e `-shm`) e si avvia l'immagine precedente. Si perdono i lotti inseriti dopo il deploy, quindi **si aggiorna quando non si sta producendo**.

### Lati negativi (accettati, con le contromisure)
- **Lavoro e rischio iniziali:** le fasi 0a–0c toccano avvio, backup e bot, e le etichette arrivano dopo. *Contromisura:* rilasci separati e osservazione prima di proseguire.
- **Più memoria:** un container in più occupa circa 100–150 MB di RAM sul VPS.
- **Due database:** non si possono fare collegamenti diretti tra lotti e fornitori o fatture. *Contromisura:* id più copia del testo.
- **Due modi di aggiornare:** se si sceglie quello sbagliato, il bot resta sul codice vecchio. *Contromisura:* lo script se ne accorge e propone "tutto".
- **Isolamento parziale:** un errore grave nel sito ferma il sito per tutte le sezioni (non bot e impianto). *Contromisura:* punto 9.
- **WAL:** i database non si copiano più con un semplice `cp`, perché esistono i file `-wal` e `-shm`. *Contromisura:* lo script di backup e il README.

### Integrazione nel nucleo (dal grafo graphify, commit 90d4e6c, che è aggiornato)
- **`app/__init__.py`:**
  - `_init_db` diventa `_init_db_nucleo`, con `create_all(bind_key=None)`, e gira solo con `RUOLO=web`;
  - le righe 197–201 diventano: scheduler e bot solo con `RUOLO=servizi` (fase 0b), oppure `web` finché `servizi` non esiste;
  - si registrano i moduli da `MODULI` tramite `app/moduli`;
  - si aggiunge `'prodotti': 'prodotti'` a `BLUEPRINT_SECTION_MAP` (riga 179);
  - `inject_globals` aggiunge `moduli_attivi` e le versioni.
- **`docker-compose.yml`:**
  - nuovo servizio `servizi` (stessa immagine, `command: python -m app.servizi`, `RUOLO=servizi`, volumi `data` e `backups`);
  - `impianto` non dipende più dalla ricostruzione di `web`;
  - immagine con tag di versione;
  - la porta del sito è fissata a `127.0.0.1:8080`.
- **Nuovo `app/servizi.py`:** crea l'app senza gunicorn, avvia `_init_scheduler` e il bot e resta in attesa. La logica dei job non cambia.
- **Dockerfile:** aggiunge `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b fonts-dejavu-core` per WeasyPrint. È un cambio del nucleo, quindi va con il deploy "tutto" della fase 0b.
- **Permesso:** si aggiunge la sezione `"prodotti"` a `User.sections`. Non serve toccare il DB, perché `has_section()` è in `app/models.py:21`. In `app/templates/impostazioni/index.html` va aggiunta la casella "Prodotti" in tre punti: la lista dei badge (riga 24), la finestra di modifica (righe 76–89) e la creazione (righe 123–136). Le scritture usano `write_required` (`app/utils/decorators.py`), così il consulente ha sola lettura.
- **Menu:** un nuovo gruppo PRODOTTI in `app/templates/components/sidebar_nav.html`, copiato dal blocco ALLEVAMENTO (righe 95–172), con un colore suo (oro `#c6a96f`). Il gruppo compare solo se `'prodotti' in moduli_attivi` e l'utente ha la sezione.
- **Modelli** in `app/moduli/prodotti/models.py`, nel DB `prodotti.db`.
- **Fornitori:** si riusano i `Contact` con `type="fornitore"` (`models.py:34`), con la possibilità di crearne uno al volo dentro la finestra.
- **Logica pura** (codice lotto, scadenza, testo ingredienti, scalatura della ricetta, adattamento del testo all'etichetta) in `app/moduli/prodotti/services/`, senza Flask, così la si può testare con `unittest` come in `tests/test_trattamenti.py`.
- **Interfaccia:** Bootstrap 5 più `cb-card`/`btn-cb`. Lo schema CRUD si copia da `anagrafica` e le modifiche si fanno in finestre modali, come da convenzione del README.
- **Documenti:** `docs/piano-prodotti.md`, una copia di questo piano, insieme a `~/Desktop/etichette/piano-prodotti-etichette.md`. Nel README va aggiunta una sezione "Moduli" con le regole del punto 1 e le procedure di deploy e rollback.

## Modello dati (`app/moduli/prodotti/models.py`, DB `prodotti.db`)
- **MateriaPrima:** `nome`, `nome_etichetta` (ad esempio "farina di GRANO tenero tipo 00"), `allergeni` (JSON con i 14 allergeni UE), `composta` (testo tra parentesi, per esempio la mostarda: "frutta, zucchero, essenza di SENAPE"), `fornitore_default_id` (collegato a Contact), `produzione_propria` (sì/no), `attiva`.
- **Prodotto:** `nome`, `sottotitolo` (es. "Pasta artigianale ripiena all'uovo – prodotto congelato"), `sigla` (es. ZUC), `categoria`, `peso_netto` e `unita` (g/ml), `formato_etichetta_id`, `tipo_scadenza` ("da consumarsi preferibilmente entro" oppure "da consumarsi entro"), `durata_giorni`, `conservazione`, `modalita_uso`, `tracce` ("Può contenere tracce di…"), `prodotto_da` (di default "Fattoria Ca' Bianca Società Agricola S.S. – Via Costa S. Caterina 1, Ossalengo, 26022 Castelverde (CR)"), `lavorato_da` (facoltativo, ad esempio il laboratorio con bollo CE per i salumi), `dichiarazioni_extra` (ad esempio "Frutta utilizzata: X g per 100 g", obbligatoria per le confetture), `nutrizionale` (JSON facoltativo), `ricetta_default_id`, `attivo`, `da_verificare` (per l'import).
- **Ricetta** con righe **RicettaRiga**: `prodotto_id`, `versione` (v1, v2…), `resa` (pezzi e kg per una produzione), `procedimento`, `note_haccp` (cottura, pastorizzazione, temperature). Le righe hanno `materia_prima_id`, `quantita`, `unita` e `ordine`. **Una ricetta già usata in un lotto non si modifica più**: "Modifica" crea una nuova versione. Così ogni lotto resta legato alla ricetta esatta con cui è stato fatto.
- **Lotto** con righe **LottoIngrediente:**
  - Il lotto ha `codice` (unico), `prodotto_id`, `ricetta_id`, `data_produzione`, `data_scadenza`, `pezzi_prodotti`, `ingredienti_testo` (copia del testo, modificabile), `allergeni`, `note`, `stato` (attivo, esaurito o ritirato), `creato_da` e `creato_il`.
  - Ogni riga ingrediente ha `materia_prima_id`, `quantita_usata`, `fornitore_id` (oppure testo libero), `lotto_fornitore`, `rif_documento` (DDT o fattura), `produzione_propria`.
- **FormatoEtichetta:** `nome`, `codice_foglio`, misure in mm (larghezza, altezza, colonne, righe, margini, passo), `offset_x` e `offset_y` per calibrare la stampante, `layout` (orizzontale, compatto o striscia).
- **StampaEtichetta**, l'archivio delle stampe: `lotto_id`, `formato_id`, `stile` (con la versione), `n_etichette`, `pdf_path`, `sha256`, `utente`, `data`.
  - I PDF stanno in `data/prodotti/etichette/AAAA/<lotto>_<sha8>.pdf`, fuori da `static/`: sono scritti una volta sola e mai sovrascritti.
  - Si scaricano solo da `/prodotti/etichette/<id>`, con login e permesso.
  - Accanto c'è una copia JSON dei dati stampati, così il PDF si può rigenerare identico.

## Etichette
- **Motore:** WeasyPrint con modelli Jinja HTML e CSS, cioè lo stesso modo in cui è stato fatto il PDF dei marubini. Va aggiunto `weasyprint` (e `openpyxl` per l'Excel) a `requirements.txt`, e `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b` al `Dockerfile`.
- **Font** inclusi in `app/static/fonts/` (Yeseva One e Varela Round, licenza OFL), così il PDF non dipende da internet. Il logo è `app/static/img/logo.svg`.
- **Stili con versione:** `app/templates/prodotti/etichette/stili/<nome-stile>/` contiene `etichetta.html` e `stile.css`. Lo stile attivo si sceglie in Impostazioni prodotti. Per aggiornare la grafica si aggiunge una cartella `stile-2027`, ma i lotti vecchi restano archiviati con lo stile con cui sono stati stampati.
- **Proposta di stile nuovo** (primo passo dell'implementazione, da approvare su una prova di stampa):
  - sfondo bianco, logo verde, nome del prodotto in Yeseva One bordeaux;
  - una fascia sottile verde `#009d5a` con un filo oro `#c6a96f`;
  - un riquadro con bordo per lotto e scadenza (molto leggibile);
  - il peso netto grande;
  - nessuna campitura piena, per non consumare toner.
- **Adattamento automatico del testo:** ogni etichetta si prova a misure di carattere sempre più piccole finché il contenuto sta in una pagina della dimensione dell'etichetta. Se servirebbe un carattere sotto il minimo di legge (altezza della x ≥ 1,2 mm, cioè circa 7 pt), compare un avviso. Questa logica è in `services/prodotti_etichette.py`.
- **Anteprima dal vivo** nella finestra: lo stesso modello HTML in un iframe in scala. Il PDF viene generato solo alla conferma.

### Formati pretagliati da acquistare (proposta, da verificare misurando i vasetti)
| Formato | Uso | Misura etichetta | Per foglio A4 | Codice di riferimento |
|---|---|---|---|---|
| Grande | vasetti 250–314 ml, passata 750 ml, buste pasta 500 g, farine | 105 × 74 mm | 8 | Avery 3427 (la stessa griglia delle etichette attuali dei tortelli) |
| Medio | vasetti 150–156 ml | 105 × 42,3 mm | 14 | Avery 3653 |
| Piccolo | vasetti 100–106 ml, sacchettini | 70 × 37 mm | 24 | Avery 3474 |
| Salumi | salami, pancetta, cotechini | 70 × 42,3 mm | 21 | Avery 3652 |

Ogni formato è un record nel DB e si modifica dalla pagina Formati, così se ne aggiungono altri senza toccare il codice. Sempre dalla pagina Formati si stampa un **foglio di calibrazione** per regolare `offset_x` e `offset_y`.

## Pagine e finestre (`app/templates/prodotti/`)
1. **Home Prodotti:** un pulsante grande "＋ Nuovo lotto", gli ultimi lotti, i prodotti usati di recente e gli avvisi (prodotti da verificare, ricette senza fornitore).
2. **Finestra "Nuovo lotto"**, una procedura in tre passi pensata anche per il telefono:
   1. **Prodotto:** ricerca con i prodotti recenti in cima, oppure "＋ Nuovo prodotto" che apre il modulo prodotto dentro la stessa finestra.
   2. **Produzione:**
      - la ricetta è già scelta (quella predefinita) e si può cambiare;
      - la data di produzione è oggi;
      - il codice lotto e la scadenza sono calcolati e modificabili;
      - c'è il numero di pezzi;
      - le quantità vengono scalate dalla ricetta in base ai pezzi;
      - per ogni ingrediente il fornitore e il lotto del fornitore sono **precompilati con quelli usati l'ultima volta** per quella materia prima, e c'è la casella "produzione propria".
   3. **Etichetta:** testo ingredienti modificabile (con "ripristina dalla ricetta"), anteprima dal vivo, formato e numero di etichette o fogli. "Crea lotto e stampa" salva il lotto, archivia il PDF e lo apre.
3. **Catalogo prodotti:** elenco per categoria e scheda prodotto (dati di etichetta, ricette e versioni, lotti). "Nuovo lotto" dalla scheda apre la finestra con il prodotto già scelto.
4. **Ricettario e finestra "Nuova ricetta":**
   - righe ingredienti con completamento automatico sulle materie prime e "＋ nuova materia prima" con le caselle degli allergeni direttamente nella riga;
   - totale e percentuali calcolati;
   - **anteprima dell'elenco ingredienti di legge** generato mentre si scrive;
   - procedimento e note HACCP;
   - "duplica come nuova versione".
5. **Materie prime:** elenco con allergeni, fornitore predefinito e storico dei lotti dei fornitori usati.
6. **Libro lotti:**
   - tabella con filtri per periodo, prodotto e stato, e ricerca per codice;
   - dettaglio del lotto: ricetta, ingredienti con fornitore e lotto, etichette stampate (da riscaricare);
   - **Export PDF** (registro per periodo, pronto da mostrare al controllo) ed **Export Excel**.
7. **Richiamo:** si cerca per materia prima e lotto del fornitore, oppure per fornitore e periodo, e si vedono tutti i lotti di prodotto coinvolti, con la possibilità di segnarli "ritirato" in blocco. Anche questo si esporta in PDF.
8. **Export ricettario:** PDF con una ricetta per pagina (ingredienti, procedimento, HACCP, versione) ed Excel, sia per tutto il ricettario sia per una singola ricetta.
9. **Impostazioni prodotti** (solo admin): stile attivo, dati del produttore predefiniti, formati.

## Catalogo iniziale
Lo script `scripts/importa_etichette.py` va lanciato una sola volta, in locale:
- per ogni cartella prende l'etichetta più recente, PDF o `.ai` (compatibile PDF), e ne estrae il testo con `pdftotext`;
- ricava nome, peso, ingredienti con gli allergeni, conservazione e produttore;
- scrive un JSON di bozza che ricontrollo a mano;
- carica i prodotti con `da_verificare=1` e le materie prime individuate;
- non crea ricette con le quantità, perché le etichette non le riportano: le ricette le inserite voi.

## Modo di lavoro (deciso il 24/11/2026)
- **Su GitHub, non in produzione.**
  - Tutto lo sviluppo va sul ramo `sviluppo/moduli-prodotti`, con push su GitHub dopo ogni passo.
  - Niente merge su `master` e niente deploy sul VPS finché Andrea non lo chiede.
  - I rilasci in produzione seguiranno poi le fasi 0a, 0b, 0c e 1+.
- **Salvato sempre, per riprendere se finiscono i crediti:**
  - un commit e un push a ogni passo piccolo e funzionante;
  - `docs/piano-prodotti.md` contiene il piano più una sezione **"Stato dei lavori"** con una lista di caselle (fatto / in corso / da fare, con data, ultimo commit e il prossimo passo esatto), aggiornata in ogni commit;
  - una memoria `gestionale-prodotti` punta a quel file.
- **Ordinato e documentato:**
  - ogni file nuovo inizia con un docstring che dice a cosa serve e come si collega al resto;
  - le funzioni non banali hanno un commento sul *perché*;
  - il README ha le sezioni "Moduli" (regole, ruoli, deploy, rollback) e "Prodotti" (flussi d'uso);
  - `app/moduli/prodotti/LEGGIMI.md` è la mappa del modulo;
  - i commit seguono lo stile del repo: `3.3.3: …` per il nucleo e `prodotti 1.0.0-dev: …` per il modulo;
  - alla fine di ogni fase si esegue `graphify update .`.
- Copia del piano in `~/Desktop/etichette/piano-prodotti-etichette.md`.

## Fasi
Ogni fase del nucleo si rilascia **da sola** e va tenuta in osservazione prima di passare alla successiva.

| Fase | Cosa | Via libera se | Come si torna indietro |
|---|---|---|---|
| **0a – 3.3.3** | WAL e `busy_timeout`; backup con l'API sqlite3, `integrity_check` e tutti i `data/*.db`; conservazione 7 copie giornaliere e 12 mensili | un backup ripristinato in una cartella di prova passa l'`integrity_check`; 3 notti di backup OK | `journal_mode=DELETE` e immagine precedente |
| **0b – 3.4.0** | `RUOLO` (web, servizi, impianto, sviluppo); `_init_db_nucleo` solo con `web`; nuovo container `servizi` con scheduler e bot; `app/moduli/` vuoto con il registro; `MODULI`; `/salute`; tag delle immagini; `scripts/deploy.sh`; Dockerfile con le librerie per WeasyPrint; README "Moduli". **Il comportamento non cambia.** | test verdi; per una settimana bot, avvisi, backup, cassa, email e impianto funzionano; un `deploy.sh sito` di prova non interrompe il bot (log di `servizi`) | `deploy.sh tutto` con il tag precedente |
| **0c – 3.4.1** | permesso "Prodotti", gruppo nel menu, modulo vuoto (pagina iniziale e `schema_versione` v1) | il deploy "sito" crea `prodotti.db` con la copia pre-migrazione; `gestionale.db` resta senza tabelle nuove | `MODULI=` vuoto |

Poi il modulo, rilasciato sempre con `deploy.sh sito`, cioè con un riavvio di 3–5 secondi del solo sito:

1. Modelli (migrazione m001 con trigger anti-cancellazione) e CRUD per materie prime, prodotti e ricette (versioni comprese).
2. Libro lotti con la finestra "Nuovo lotto" e i servizi puri (codice, scadenza, testo ingredienti, scalatura).
3. Motore etichette: WeasyPrint, font, stile nuovo, formati, adattamento del testo, anteprima e archivio. **Prima si stampa una prova dello stile da approvare.**
4. Export (libro lotti e ricettario in PDF e Excel) e pagina Richiamo.
5. Import del catalogo dalle etichette esistenti.
6. Test, aggiornamento del README e del grafo (`graphify update .`), rilascio di `prodotti 1.0.0`.

## Verifica
- `python3 -m unittest discover -s tests` con i nuovi test:
  - `test_prodotti_lotti.py`: codice lotto e codici duplicati nello stesso giorno, scadenza, scalatura della ricetta;
  - `test_prodotti_ingredienti.py`: ordine per peso, grassetto degli allergeni, ingredienti composti, "tracce";
  - `test_prodotti_etichette.py`: l'adattamento del testo riduce il carattere e segnala sotto il minimo; la griglia dei formati dà le posizioni giuste in mm.
- Prova in locale con `data/_test.db`:
  - creare un utente operatore con il solo permesso "Prodotti" e controllare che veda solo quella sezione e che il consulente sia in sola lettura;
  - creare una materia prima, poi un prodotto e una ricetta, poi un lotto, e generare l'etichetta;
  - aprire il PDF e confrontarlo a video con il PDF dei marubini.
- Stampa vera di un foglio di calibrazione e di un foglio di etichette su ciascun formato pretagliato.
- Export del libro lotti in PDF e Excel, e un richiamo su un lotto di materia prima usato in due lotti di prodotto.
- Build Docker sul VPS (WeasyPrint e Pango) prima del rilascio.
- **Nuovo test `tests/test_avvio_ruoli.py`** (usa Flask e DB temporanei, con scheduler e bot sostituiti da finti):
  - per ogni combinazione di `RUOLO` e `MODULI`, `create_app()` parte e ogni pagina GET senza parametri risponde senza 500 né BuildError;
  - con `servizi` partono scheduler e bot, con `web`, `impianto` e `sviluppo` no;
  - con `impianto` lo schema di `gestionale.db` resta identico (hash di `sqlite_master`).
- **Nuovo test `tests/test_prodotti_schema.py`:**
  - le migrazioni funzionano su un DB vuoto, su uno alla v1 e anche lanciate due volte;
  - un DB "più nuovo del codice" viene rifiutato;
  - i trigger bloccano la DELETE dei lotti;
  - la copia pre-migrazione viene creata.
- **Isolamento in locale con `docker compose`:**
  - `scripts/deploy.sh sito` cambia l'uptime solo di `web`, mentre `servizi` e `impianto` restano accesi (`docker compose ps`);
  - nei log di `servizi` non c'è un riavvio del bot né un 409 di Telegram;
  - `gestionale.db` non ha tabelle di prodotti (`sqlite3 .tables`).
- **Backup:** si ripristinano `gestionale.db` e `prodotti.db` dall'ultimo backup in una cartella di prova, si avvia l'app con `RUOLO=sviluppo` e si controlla che il libro lotti ci sia.

---

## Stato dei lavori

> Aggiornato a ogni commit. Chi riprende il lavoro (anche un'altra sessione di Claude) parte da qui:
> leggere "Prossimo passo", poi `git log --oneline sviluppo/moduli-prodotti`.

**Ramo:** `sviluppo/moduli-prodotti` (su GitHub, NON in produzione). Produzione ferma a 3.3.2 (`master`).

### Fase 0a – 3.3.3 (SQLite robusto + backup)
- [ ] WAL + busy_timeout (evento connect su Engine)
- [ ] backup con API sqlite3 + integrity_check, tutti i data/*.db, 7 giornalieri + 12 mensili
- [ ] test backup

### Fase 0b – 3.4.0 (ruoli e container servizi)
- [ ] RUOLO (web/servizi/impianto/sviluppo), _init_db_nucleo solo con web
- [ ] app/servizi.py + servizio compose `servizi`
- [ ] app/moduli/ registro + MODULI + /salute
- [ ] scripts/deploy.sh (sito/tutto), tag immagini
- [ ] Dockerfile librerie WeasyPrint
- [ ] tests/test_avvio_ruoli.py
- [ ] README sezione "Moduli"

### Fase 0c – 3.4.1 (modulo vuoto)
- [ ] permesso "prodotti", menu, pagina iniziale, schema_versione v1

### Modulo prodotti 1.0.0
- [ ] 1. modelli + m001 + CRUD materie prime / prodotti / ricette
- [ ] 2. libro lotti + finestra Nuovo lotto
- [ ] 3. motore etichette (prova stile da approvare)
- [ ] 4. export + richiamo
- [ ] 5. import catalogo dalle etichette
- [ ] 6. test, README, graphify

### Diario
- 24/11/2026 – piano approvato, creato il ramo.

### Prossimo passo
Fase 0a: evento connect SQLite in `app/__init__.py` e riscrittura di `app/services/backup.py`.
