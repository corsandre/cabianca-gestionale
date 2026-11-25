# Piano: versioni per area (finanza, allevamento, bot) e permesso «soccida» dentro «allevamento»

Richiesta di Andrea (25/11/2026, sera):
- nella pagina iniziale si vedono la versione del gestionale e quella di Prodotti, ma non quelle di finanza e
  allevamento;
- «soccida» deve essere un sottopermesso di «allevamento»;
- il messaggio di avvio su Telegram parla solo di Prodotti;
- il bot dovrebbe essere a parte, e l'impianto fa parte dell'allevamento.

Stato: **PIANO, da approvare**. Non è ancora stato toccato niente.

## Com'è oggi (dal codice)

- **Moduli veri.** Con il pacchetto proprio, il database proprio (`data/<nome>.db`), la versione propria e la
  registrazione in `app/moduli`, oggi c'è **solo Prodotti**.
- **Finanza e allevamento** sono ancora nel *nucleo*:
  - stesso database (`gestionale.db`), stesso pacchetto `app/routes` e `app/services`;
  - una sola versione per tutti (`app/version.py`, oggi 3.4.1);
  - sono separati come **sezioni** (permessi e menu), ma non come moduli.
- **Sono collegati dentro lo stesso database.**
  - L'allevamento legge le fatture della finanza: fatture del siero (`siero_fatture.py` legge `sdi_invoices`) e
    acquisti di mangime.
  - Il bot serve **tutte e due**: per l'allevamento mortalità, spostamenti, consegne, pasti, censimento e
    trattamenti; per la finanza le spese Amazon da descrivere (`spese_bot.py`), le scadenze e gli avvisi.
  - Il bot gira nel container `servizi` insieme ai lavori programmati di finanza (cassa, email, fatture,
    backup) e di allevamento (avvisi, fatture del siero).
- **L'impianto** (`app/services/impianto/`, pagine `app/routes/impianto.py`, container `impianto`) usa già il
  permesso «allevamento» (`_check_allevamento`): nei fatti fa già parte dell'allevamento.
- **Il permesso «soccida»** è una casella a sé in Impostazioni › Utenti. Nel codice la scheda soccida
  controlla prima «allevamento» e poi «soccida» (`routes/soccida.py:_puo_vedere`). Chi ha soccida senza
  allevamento riceve un errore 403: un permesso che si può assegnare ma che da solo non funziona.
  - Oggi in produzione nessuno è in quella situazione: maria e agnese94 hanno entrambi i permessi.

## Proposta

### 1. «Aree» con la loro versione, senza spostare il codice

Separare davvero finanza e allevamento in moduli come Prodotti (pacchetto e database propri) **non conviene**.
- Sono legati da collegamenti diretti nel database (fatture ↔ siero, mangime, spese) e da bot e scheduler comuni.
  Dividerli vorrebbe dire riscrivere quei collegamenti, con molto rischio e nessun vantaggio per chi li usa.
- Gli aggiornamenti senza fermare il bot li abbiamo già ottenuti con i container `web` / `servizi` / `impianto`.

Propongo un registro delle **aree**, solo per versioni, messaggi e documentazione. Nessun file si sposta e
nessuna tabella cambia. File nuovo `app/aree.py`:

| Area | Cosa comprende (cartelle e file) | Dove gira | Versione iniziale |
|---|---|---|---|
| **gestionale** (nucleo) | utenti e permessi, menu, impostazioni, backup, avvio, `app/moduli`, `deploy.sh` | tutti | 3.4.1 → 3.5.0 con questo lavoro |
| **finanza** | prima nota, fatture, banca, cassa, scadenzario, analisi, … (`routes/` e `services/` di finanza) | web + lavori in `servizi` | 3.4.1 |
| **allevamento** | allevamento, **soccida**, **impianto** (`routes/allevamento.py`, `soccida.py`, `impianto.py`, `services/allevamento_*`, `soccida*`, `siero_*`, `impianto/`) | web + `servizi` + container `impianto` | 3.4.1 |
| **bot** (Telegram) | `allevamento_bot.py`, `spese_bot.py`, `telegram_bot.py` | `servizi` | 3.4.1 |
| **prodotti** (modulo) | `app/moduli/prodotti/` | web | 1.1.0 (già così) |

- Il bot diventa un'area a sé perché serve sia la finanza sia l'allevamento, come hai intuito.
- L'impianto sta dentro allevamento. È un container separato solo per motivi tecnici (collegamento al PC
  dell'impianto).
- Ogni area ha la sua `VERSIONE` e l'elenco delle sue cartelle e file.
  - **Controllo automatico in `deploy.sh`**: se cambiano i file di un'area e la sua versione no, lo script lo
    dice prima del deploy («allevamento: file cambiati ma versione ferma a 3.4.1»). Così le versioni restano
    vere senza doverci pensare.
  - Un test verifica che ogni file Python di `app/routes` e `app/services` appartenga a una sola area. Un file
    nuovo non dichiarato fa fallire il test, quindi niente resta fuori.
- I commit seguono lo stile già in uso per Prodotti: `allevamento 3.4.2: …`, `finanza 3.4.2: …`, `bot 3.4.2: …`.

### 2. Dove si vedono le versioni

- **Menu laterale (in fondo)**: «gestionale 3.5.0 · finanza 3.4.1 · allevamento 3.4.1 · bot 3.4.1 · prodotti
  1.1.0», su due righe. Ogni utente vede solo le aree che ha nei permessi, mentre l'admin le vede tutte.
- **Impostazioni › Server**: una tabella con le aree, la versione, dove gira (sito / servizi / impianto) e la
  versione che gira davvero in ogni container. Il container `servizi` scrive le sue versioni nei Setting
  all'avvio, così si vede se il bot è rimasto a una versione vecchia dopo un deploy `sito`.
- **`/salute`**: aggiunge le versioni delle aree.

### 3. Messaggi di avvio su Telegram

Oggi ci sono due messaggi, «🌐 Sito del gestionale» dal container web e «🔄 Gestionale avviato» dal container
servizi/bot, e solo il primo elenca i moduli. Proposta: tutti e due elencano tutte le aree e mettono in evidenza
quelle aggiornate.

```
🌐 Sito del gestionale – aggiornato
· gestionale 3.5.0 (era 3.4.1)
· finanza 3.4.1
· allevamento 3.4.2 (era 3.4.1) – impianto: Automatico
· prodotti 1.1.0
```
```
🔄 Servizi avviati (bot e lavori programmati) – riavviati senza aggiornamenti
· bot 3.4.1 · finanza 3.4.1 · allevamento 3.4.1 · bot connesso
```

Il confronto con le versioni precedenti si fa sui Setting `versioni_avviate_sito` e `versioni_avviate_servizi`,
come oggi con `versione_avviata`.

### 4. Permesso «soccida» dentro «allevamento»

- **Un solo elenco dei permessi**, in `app/models.py` (oggi è scritto a mano in tre punti di
  `impostazioni/index.html`):
  ```python
  SEZIONI = {"finanza": {}, "allevamento": {"sotto": {"soccida": "Soccida (scheda economica)"}}}
  ```
  I moduli aggiungono le loro sezioni. Prodotti dichiara `SEZIONE = "prodotti"` nel suo `__init__.py`, così il
  nucleo non deve più conoscerla per nome.
- **Regola nel modello**: `has_section("soccida")` è vera solo se c'è anche «allevamento». Vale per tutti i
  sottopermessi, quindi è una difesa anche se un dato vecchio fosse incoerente.
- **Salvataggio**: creando o modificando un utente, un sottopermesso senza la sua sezione viene tolto, con un
  avviso.
- **Finestra utenti**: «Soccida» compare **rientrata sotto Allevamento**. È spenta e non selezionabile finché
  Allevamento non è spuntato, e togliendo Allevamento si toglie anche lei. Nei badge dell'elenco utenti si legge
  «allevamento (+ soccida)».
- **Dati in produzione**: una piccola migrazione toglie «soccida» a chi non ha «allevamento». Oggi non c'è
  nessuno da correggere, ma resta come garanzia.
- **Test**: permessi e sottopermessi, salvataggio, menu e accesso 403.

### 5. Rilascio

- Cambiano `app/models.py`, `app/__init__.py` e `avvio.py`, quindi serve `scripts/deploy.sh tutto`: anche il bot
  riparte, con circa un minuto di interruzione. Va fatto quando non si sta lavorando con il bot (come oggi,
  dopo il pasto dei maiali).
- Prima la prova generale sulla copia dei dati veri, come per la 3.4.1.
- Si torna indietro con `scripts/deploy.sh indietro tutto`. Nessuna tabella nuova: le versioni sono costanti nel
  codice più alcuni Setting.

### Lavoro stimato

Circa mezza giornata di sviluppo e prove, più il rilascio.

## Domande per Andrea

1. **Numeri di partenza**: le aree partono tutte da 3.4.1, in continuità con la versione attuale, o da 1.0.0?
   Consiglio 3.4.1, così nessuna versione sembra «tornare indietro».
2. **Menu laterale**: tutte le versioni sempre visibili (due righe piccole), oppure solo «gestionale 3.5.0» con il
   dettaglio passando il dito o il mouse sopra?
3. **Separazione vera**: va bene restare con le «aree» (versioni e messaggi separati, stesso database)? Oppure in
   futuro vuoi davvero finanza e allevamento in moduli come Prodotti? In quel caso va fatto un piano a parte,
   molto più grande.
