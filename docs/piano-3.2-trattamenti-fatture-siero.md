# Piano — Dosaggi, marcatore, stato del server, controllo delle fatture del siero

Richiesta di Andrea del 20/11/2026, risposte alle domande nello stesso giorno. Quattro lavori:

| Versione | Lavoro | Tipo |
|---|---|---|
| 3.1.5 | 1. Dosaggio dei medicinali con 4 decimali | correzione |
| 3.1.5 | 2. Marcatore che non si salva al primo salvataggio (da telefono) | correzione |
| 3.2.0 | 3. Stato del server in Impostazioni (disco, memoria, da cosa è occupato) | funzione nuova |
| 3.3.0 | 4. Controllo delle fatture del siero: riquadro che si espande | funzione nuova |

Lo stato del server va prima delle fatture: è veloce da fare e toglie subito il dubbio sullo spazio.
Codice individuato con graphify (`graphify query/explain`) e poi letto solo nei punti trovati.

---

## 1. Dosaggio con 4 decimali — 3.1.5

**Dove sta il problema** (confermato da Andrea: Impostazioni › nuovo medicinale › dose per kg).
`allevamento/impostazioni.html` riga 378: il campo ha `step="0.001"`, quindi il browser **rifiuta** 4 decimali, e sta
in una colonna `col-md-2` insieme al menu ml/kg–g/kg largo 80px: il campo resta così stretto che si leggono solo 2
cifre dopo la virgola. Il server (`medicinali_new`, riga ~2203) e il database (Float) tengono già qualsiasi decimale:
provato su una copia del DB, 0,0125 si salva esatto.

**Cosa fare.**
- Campo del dosaggio con `step="any"` (accetta 4 decimali e oltre) e `inputmode="decimal"` per il telefono, in tutti e
  quattro i punti: `impostazioni.html` 331 (modifica medicinale) e 378 (nuovo), `trattamenti.html` 269 (modifica) e
  400 (nuovo trattamento).
- Colonna del nuovo medicinale più larga (`col-md-3`) e campo con larghezza minima, così si vedono tutte le cifre;
  stessa cosa per il campo da 90px nella tabella dei medicinali (riga 332).
- Dosi calcolate: `quantita()` (Python `allevamento_trattamenti.py:26`, copia JS in `trattamenti.html`, usata anche
  dal bot) oggi mostra 1 decimale, e con dosaggi piccoli la dose a capo esce «0,0 g». Decimali che si adattano: sotto
  1 → 3 decimali, sotto 10 → 2, altrimenti 1; sopra 1000 kg/l con 2 come ora.
- Prova in `tests/`: `quantita()` con valori piccoli, medi e grandi.

---

## 2. Marcatore che non si salva al primo salvataggio — 3.1.5

**Cosa sappiamo.** Succede nel **nuovo trattamento da telefono**, anche per un solo suino (quindi con un box scelto).
Dopo, con la modifica, si salva. Il server è a posto: su una copia del DB sia il nuovo trattamento che la modifica
salvano colore e segno al primo colpo. Quindi il problema è in quello che la pagina manda dal telefono.

**Indiziato.** La proposta automatica del segno (`aggiornaColori()`, `trattamenti.html` ~riga 553): quando si sceglie
il box parte la richiesta a `/trattamenti/colori/<box>` e anche quella del peso; se la risposta arriva dopo la scelta
fatta a mano, o se sul telefono la scelta non fa scattare `change` prima della risposta, i menu vengono riscritti.
Da verificare anche `updateBoxes()` (ricrea il menu dei box se si tocca di nuovo il capannone).

**Cosa fare.**
1. Riprodurre con Chromium sul Raspberry (`/usr/bin/chromium`) in modalità telefono, facendo i passi: capannone → box
   → marcatore → salva, e guardare il POST.
2. Se serve, registrare per qualche giorno nel log del server cosa arriva in `colore`/`segno` al nuovo trattamento
   (con il tipo di browser), da togliere dopo.
3. Correzione: la proposta riempie i menu solo se sono ancora al valore iniziale (non in base al flag
   `marcatoreScelto`), e non li tocca più dopo che l'utente li ha toccati (anche `input`/`click`, non solo `change`).
4. Il messaggio verde dopo il salvataggio dice anche il marcatore («Trattamento registrato: …, 1 capo, riga rossa»):
   si vede subito se è andato.

---

## 3. Stato del server in Impostazioni — 3.2.0

**Perché.** Sulla VPS girano gestionale, ordini e Postiz; ogni giorno arrivano foto delle bolle e fatture. Serve vedere
quanto disco e memoria sono occupati e da cosa, prima che diventi un problema.

**Cosa c'è oggi** (da graphify): niente che misuri lo spazio. I file stanno in `app/static/uploads/`
(volume `./app/static/uploads` in `docker-compose.yml`):
- `allevamento_consegne/` foto delle bolle (siero e mangime, da web e dal bot Telegram);
- radice di `uploads/` fatture SDI ricevute (XML/PDF, `sdi_importer.py:32`);
- cartella dei PDF delle fatture emesse (`fatture_emesse.py:185`), `movimenti/` allegati, pagine del Modello 4.

E poi `data/gestionale.db` e `backups/` (gli ultimi 7, `backup.py`). Le foto dal web sono già ridotte prima dell'invio
(`bolla.js`: lato 1600 px, JPEG 75%; Modello 4: 2000 px, 80%); quelle dal bot sono quelle che manda Telegram.

**Cosa vede il gestionale da solo e cosa no.** Dal container si leggono: spazio del disco della VPS
(`shutil.disk_usage` sul volume, è il disco vero), memoria e carico della VPS (`/proc/meminfo`, `/proc/loadavg`),
dimensione di ogni cartella di upload, del DB e dei backup. **Non** si vedono: le immagini e la cache di Docker (di
solito la parte che cresce di più, perché ogni rilascio con `build --no-cache` lascia immagini vecchie), gli altri
servizi (ordini, Postiz) e la memoria usata da ogni container.

**Soluzione in due pezzi.**
1. **Script sulla VPS** `scripts/stato_server.sh`, lanciato da cron ogni 15 minuti, che scrive
   `data/stato_server.json` con: `df` del disco, `free`, `docker system df` (immagini, container, volumi, cache di
   build), `docker stats --no-stream` (memoria e CPU di ogni container), `du` delle cartelle di ordini e Postiz,
   dimensione dei log di sistema. Solo letture, niente pulizie.
2. **Il gestionale** (`app/services/stato_server.py`): legge quel file e ci aggiunge il dettaglio delle sue cartelle
   (dimensione, numero di file, quanto è cresciuta negli ultimi 30 giorni in base alla data dei file). Se il file manca
   o è vecchio di più di un'ora, mostra quello che vede da solo con l'avviso «dati di Docker non aggiornati».

**Come appare** (Impostazioni, riquadro «Server», solo admin):
- **Barra del disco** a segmenti colorati: foto delle bolle · fatture ricevute · fatture emesse · altri allegati ·
  database e backup · Docker (immagini/cache) · ordini · Postiz · sistema e altro · libero. Sotto, la tabella con GB e
  % di ogni voce. Barra verde fino a 75%, gialla fino a 90%, rossa oltre.
- **Barra della memoria**: un segmento per container (gestionale, impianto, ordini, Postiz…) + sistema + libera;
  swap usata.
- **Riga di stato**: carico CPU, acceso da (giorni), ultimo backup, ultimo aggiornamento dei dati.
- **Crescita**: foto e fatture al mese (MB) e stima «al ritmo attuale il disco è pieno tra circa N mesi».
- **Avviso su Telegram** (canale sistema, una volta al giorno al massimo) se il disco supera l'85% o la memoria è
  quasi piena con swap in uso.

**File toccati.** `scripts/stato_server.sh` (nuovo), `app/services/stato_server.py` (nuovo), route e template di
Impostazioni (`app/routes/impostazioni.py`, `templates/impostazioni/index.html`), controllo giornaliero nello scheduler
esistente, README (cron da installare sulla VPS e comandi di pulizia di Docker da usare a mano), prove in `tests/` sul
calcolo delle percentuali e sul file mancante/vecchio. Nella procedura di rilascio del README si aggiunge
`docker image prune -f` dopo il build, così le immagini vecchie non si accumulano.

---

## 4. Controllo delle fatture del siero — 3.3.0

**Cosa c'è oggi** (`consegne.html` righe 77–96, `siero_fatture.controllo()`): un riquadro con «N da controllare»,
«fatturato fino al», i due pulsanti *Cerca fatture nuove* / *Rileggi tutte* e una fila di badge «in fattura ma non in
Consegne»; l'esito di ogni consegna è nella colonna «Fattura». Non si vede l'elenco delle fatture, non si apre il PDF e
non si può correggere un abbinamento.

**Cosa diventa.** Il riquadro resta compatto (riga di oggi + numeri principali) e si apre cliccandolo; si apre da solo se
ci sono differenze. Dentro, tre parti.

### 4a. Numeri del ciclo
| | Consegne | Fatture | Differenza |
|---|---|---|---|
| Tonnellate | consegne fino a «fatturato fino al» | righe dei carichi | t e % |
| Importo | valore delle consegne | totale fatture con IVA (e imponibile) | € |
| €/t | prezzo dell'ultima consegna fatturata | totale ÷ t fatturate | |
| Gasolio / extra | | righe «extra» | |

Più: fatture lette, carichi abbinati per bolla / per data / a mano, consegne in attesa di fattura.

**Prezzo per le consegne non fatturate** (deciso da Andrea): €/t dell'**ultima consegna fatturata**, cioè
importo ÷ tonnellate della riga di fattura più recente abbinata a una consegna.

### 4b. Elenco delle fatture
Una riga per fattura del ciclo (`soccida_dati.fatture_siero`): numero, data, fornitore, carichi, t, imponibile, totale,
esito (✓ coincide / N differenze), pulsante **Vedi fattura** (PDF in una nuova scheda). Cliccando la riga si aprono i
suoi carichi: data, bolla, t in fattura, € del carico, consegna abbinata (data, qli, lotto, come: bolla/data/a mano),
esito; sotto le righe extra (gasolio).
- Route nuova `GET /allevamento/consegne/fattura/<id>/pdf` (login, solo fatture dei fornitori di siero): il PDF di
  `xml_path` aperto nel browser; se il file non c'è, «file non disponibile».
- Link anche alla scheda della fattura in Fatture (`fatture.detail`).

### 4c. Discrepanze e azioni
Elenco unico per data, raggruppato per tipo, ognuna con il suo valore in euro:

| Tipo | Esempio | Valore | Azioni |
|---|---|---|---|
| Quantità diversa | 28,4 t in bolla, 29,1 t in fattura | diff t × €/t del carico | *Vai alla consegna* · *Correggi consegna* |
| Bolla diversa / mancante | manca la bolla in Consegne, 1234 in fattura | — | *Scrivi 1234 nel lotto* (un clic) |
| In fattura, non in Consegne | 12/11 bolla 1234, 29 t | importo del carico | *Abbina a una consegna* · *Crea la consegna* |
| In Consegne, non in fattura | 14/11, 28 t | t × €/t dell'ultima consegna fatturata | *Abbina a una riga* · *Vai alla consegna* |

- *Vai alla consegna*: scorre ed evidenzia la riga della tabella (ogni riga riceve `id="consegna-<id>"`).
- *Correggi consegna*: apre il modulo di modifica che c'è già.
- *Abbina a mano* / *Scollega*: menu con righe o consegne libere vicine di data; salva `come = "manuale"`.
  `abbina()` lavora solo sulle righe libere e non tocca i manuali; *Rileggi tutte* invece cancella e rilegge le righe
  di una fattura → va cambiato per **rimettere gli abbinamenti manuali** (per bolla + data) dopo la rilettura.
- Niente «accetta la differenza» (deciso da Andrea): una discrepanza sparisce solo correggendo i dati.

**File toccati.** `app/services/siero_fatture.py` (`controllo()` con fatture, totali, discrepanze con tipo e valore;
`abbina_manuale()`, `scollega()`; rilettura che conserva i manuali), `app/routes/allevamento.py` (PDF, abbina/scollega,
scrivi bolla: POST, admin), `templates/allevamento/consegne.html` (riquadro espandibile, id sulle righe),
`tests/test_siero_fatture.py` (totali, valore delle discrepanze, prezzo dell'ultima consegna, manuale che resta dopo
«Rileggi tutte»), README, `version.py`. Nessuna colonna nuova nel database.

---

## Ordine di lavoro
1. **3.1.5**: punti 1 e 2, prove, rilascio.
2. **3.2.0**: punto 3 — prima la parte del gestionale (cartelle, disco, memoria), poi lo script con cron sulla VPS.
3. **3.3.0**: punto 4 — prima 4a+4b (sola lettura), poi 4c con le azioni.

Dopo ogni modifica al codice: `graphify update .`.

## Da fare con Andrea
- Punto 2: per vedere i dati reali dei trattamenti salvati senza marcatore serve leggere il DB di produzione (copia in
  sola lettura dalla VPS); la copia automatica è stata bloccata dai permessi, va autorizzata o fatta a mano.
- Punto 3: installare il cron dello script sulla VPS (una riga in `crontab -e`, scritta nel README).

---

## Stato dei lavori (20/11/2026)

**Fatto e in produzione.**
- **3.2.0** (con le correzioni previste per la 3.1.5):
  - punto 1: dosaggio a 4 decimali e oltre; il limite era nel campo del nuovo medicinale (`step="0.001"` in un
    campo largo 2 cifre);
  - punto 2: nel DB di produzione i trattamenti del 15/11 erano stati registrati alle 8:43, prima della correzione
    2.5.9 delle 9:52 dello stesso giorno, che toglieva la sovrascrittura con il pallino blu. Provato con Chromium in
    modalità telefono: il marcatore ora si salva in ogni ordine di compilazione. Aggiunti la proposta più robusta e
    il marcatore nel messaggio verde. Trovato e corretto anche un altro difetto: scegliendo in fretta il box, i capi
    restavano quelli del capannone (39 invece di 1);
  - punto 3: stato del server, con il cron installato sulla VPS. La cache di build di Docker occupava 55 GB su 67:
    pulita, il disco è passato dal 71% al 17%. La pulizia ora fa parte della procedura di rilascio nel README.
- **3.3.0**: punto 4 completo (numeri, discrepanze con azioni, elenco delle fatture con PDF), provato sui dati veri
  (6 fatture, 89 carichi, 3 discrepanze).

**Da tenere d'occhio.**
- La stima di quando il disco sarebbe pieno usa il disco intero solo dopo 7 giorni di storia dello script.
- In `data/` ci sono 59 copie del DB fatte prima dei rilasci (165 MB): si vedono nel riquadro e si possono sfoltire a mano.
- Le due righe di maggio (bolle 8509 e 8510, fattura 330) sono carichi di prima dell'inizio del ciclo: se non sono
  da registrare, la fattura va assegnata al ciclo precedente in Impostazioni Soccida.
