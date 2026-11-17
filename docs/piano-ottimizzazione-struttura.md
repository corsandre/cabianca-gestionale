# Piano — Ottimizzazione della struttura (conteggio capi e foto delle bolle)

Scritto il 17/11/2026 dopo la lettura del grafo di graphify. Regola: **nessun cambiamento visibile nelle pagine**,
solo codice spostato in un posto migliore. Due interventi indipendenti, rilasciabili insieme o separati.

**Stato (17/11/2026, sera): fatti tutti e due, provati, da rilasciare come 3.1.4 (fuori dai pasti).**
- Conteggio: copia di produzione del 17/11, prima e dopo identici in tutte le 204 voci (conteggi di ogni giorno di ogni
  ciclo, 1.776 capi oggi, stima Soccida, scorte, 15 pagine). L'unica riga diversa è l'ora del controllo con il PC
  scritta nella pagina Confronto. `tests/test_conteggio.py`: 9 prove, 51 in tutto, OK. Prova: `data/_prova_conteggio.py`
  (`PYTHONHASHSEED=0`; `--confronta prima.json dopo.json`).
- Bolle: sintassi delle tre pagine generate controllata; in Chromium una foto di 7,5 MB diventa 516 KB (1600×1200), il
  PDF resta uguale, il token scaduto si rinnova senza contare un tentativo, la rete caduta fa riprovare, senza rete
  l'errore arriva dopo i tentativi previsti. Anche l'aggancio dei campi `.cb-bolla-input` (identico nelle due pagine)
  è passato in `bolla.js`. Resta da provare a mano dal telefono dopo il rilascio.

## Perché

Il grafo mostra un punto debole solo: `app/routes/allevamento.py` (2.736 righe) contiene, oltre alle pagine, calcoli
usati da tutto il resto. Dieci moduli di servizio lo importano «di nascosto» (dentro le funzioni, per evitare import
circolari):

| Chi importa da `routes/allevamento.py` | Cosa |
|---|---|
| `services/soccida_dati.py` | `_live_count` |
| `services/allevamento_scorte.py` | `_get_ciclo_attivo`, `_live_count`, `LINEA_PER_BOX` |
| `services/allevamento_analisi.py` | `_live_count`, `LINEA_PER_BOX` |
| `services/allevamento_confronto_box.py` | `_live_count`, `CAP_PER_BOX`, `eventi_dopo_censimento` |
| `services/allevamento_trattamenti.py` | `_live_count`, `CAPANNONI`, `_stato_trattamento` |
| `services/allevamento_bot.py` | `_stato_trattamento`, `avvisi_nuovo_carico_siero` |
| `services/impianto/registrazione.py`, `servizio.py` | `_get_ciclo_attivo` |
| `services/impianto/recupero.py` | `LINEA_PER_BOX` |
| `routes/soccida.py`, `routes/impianto.py` | `_check_allevamento` (e `bp`) |

Il conteggio dei capi (`_live_count`) è la base di Censimento, Soccida, mortalità, scorte, analisi e confronto con il
PC, ma oggi non ha nessun test: si può provare solo avviando tutta l'app.

## Intervento 1 — Conteggio dei capi in un servizio

### Cosa si sposta

Nuovo modulo **`app/services/allevamento_conteggio.py`** con, copiati senza modifiche:

- struttura fissa della stalla: `CAP_PER_BOX`, `LINEA_PER_BOX`, `POSTI_PER_BOX_STANDARD`, `CAPANNONI`, `BOX_PER_CAP`,
  `POSTI_PER_CAP`, `CATEGORIE_USCITA`;
- `REGOLA_ORA_CENSIMENTO_DAL` ed `eventi_dopo_censimento`;
- `ciclo_attivo()` (oggi `_get_ciclo_attivo`);
- `live_count(ciclo, al_giorno=None)` (oggi `_live_count`).

`_stato_trattamento` va in **`services/allevamento_trattamenti.py`**, che esiste già e lo usa.

### Una sola modifica di forma, per poterlo provare

`_live_count` oggi fa due cose insieme: legge dal database e fa i conti. Lo divido in due:

- `applica_eventi(conteggi, morti, spostamenti)` — **funzione pura**: riceve i capi del censimento e gli eventi,
  restituisce i capi per box. Dentro c'è esattamente la logica di oggi (somme senza fermarsi a zero, zero solo alla
  fine; morti per capannone divisi tra i box; entrate e uscite su più box da `box_svuotati`).
- `live_count(ciclo, al_giorno)` — fa le stesse query di oggi e chiama `applica_eventi`.

Così il cuore del conteggio si prova da solo, come la curva (`python3 -m unittest`).

### Compatibilità: niente si rompe

In `routes/allevamento.py` restano i vecchi nomi, importati dal nuovo modulo:

```python
from app.services.allevamento_conteggio import (
    CAP_PER_BOX, LINEA_PER_BOX, ..., eventi_dopo_censimento,
    live_count as _live_count, ciclo_attivo as _get_ciclo_attivo,
)
```

Il resto del file (pagine e template) non cambia. Poi i servizi della tabella sopra importano dal nuovo modulo invece
che dalle route. Restano dove sono, perché sono cose di pagina: `_check_allevamento` (permesso di accesso), `bp`
(Soccida è una parte della sezione Allevamento) e `avvisi_nuovo_carico_siero` (da valutare in futuro, fuori da questo
piano). Il bot ha già un suo `_get_ciclo_attivo(app)`: non si tocca.

### Test nuovi — `tests/test_conteggio.py`

Casi presi da quelli già successi in produzione:
1. censimento senza eventi → capi uguali;
2. morto in un box e morti «per capannone» divisi tra i box (con il resto ai primi box);
3. spostamento interno, entrata su un box, entrata su più box (3.1.1), uscita su più box (3.0);
4. ordine degli eventi indifferente e zero solo alla fine (caso del 12/10, box 16: 2 capi, non 3);
5. box mai negativi nel risultato.

Per `eventi_dopo_censimento` (che costruisce una condizione SQL) la prova resta quella sul database.

### Prova sulla copia del database di produzione

Script `data/_prova_conteggio.py`, in un container sulla copia fresca del database:
- **prima e dopo**: per ogni ciclo e per ogni giorno, `live_count` di ogni box deve essere **identico** (oggi 1.776
  capi);
- stima della Soccida identica (residuo di mangime, carne, indice, margine);
- le pagine Panoramica, Censimento, Soccida, Analisi, Trattamenti, Alimentazione, Scorte e Curva rispondono 200 con
  gli stessi numeri;
- il servizio dell'impianto si avvia (`registrazione` e `servizio` importano dal nuovo modulo).

### Rilascio

Cambia anche il codice del servizio dell'impianto, quindi **vanno riavviati `web` e `impianto`**: solo fuori dai
pasti (07:55, ~13:05, 17:30, un'ora ciascuno), come sempre con il backup del database prima. Versione **3.1.4**.

## Intervento 2 — Foto delle bolle in un solo file JavaScript

### Oggi

Le stesse funzioni sono copiate in tre pagine, con solo differenze di commenti e di a capo:

| Funzione | Consegne | Spostamenti | Modello 4 |
|---|---|---|---|
| `cbComprimiImmagine` (riduce la foto prima di inviarla) | ✓ | ✓ | ✓ |
| `cbNuovoTokenCsrf` (rinnova il token se la sessione è scaduta) | ✓ | ✓ | |
| `cbFetchConRetry` (riprova l'invio se la rete cade) | ✓ | ✓ | |

`cbInviaConRetry` (solo Consegne) e `cbComprimiTutte` (solo Spostamenti) restano nelle loro pagine.

### Cosa si fa

- Nuovo file **`app/static/js/bolla.js`** con le tre funzioni (la versione di Spostamenti, che è la stessa delle
  altre).
- Nelle tre pagine si tolgono le copie e si aggiunge, prima degli script della pagina:
  `<script src="{{ url_for('static', filename='js/bolla.js') }}?v={{ versione }}"></script>`
  Il `?v=` con la versione obbliga i telefoni a scaricare il file nuovo a ogni rilascio (non c'è service worker che
  lo trattenga).
- Modello 4 è una pagina a sé (senza `extra_js`): lo script va messo nel suo `<head>`.

### Prova

Non ci sono test automatici per il JavaScript: prova a mano, **dal telefono**, sulla copia locale:
1. Consegne: nuova consegna di mangime con foto della bolla; foto aggiunta dopo dall'icona nella tabella.
2. Spostamenti: uscita con foto della bolla; Modello 4 con più pagine.
3. Una foto grande (5–10 MB) deve arrivare ridotta (~300–600 KB); un PDF deve arrivare uguale.
4. Con la rete staccata a metà invio: deve riprovare e avvisare, e la consegna deve restare salvata.

### Rilascio

Solo template e file statico: basta `web` (`up -d --no-deps web`), anche durante un pasto. Può andare nella stessa
3.1.4.

## Cosa non si fa (per restare minimal)

- Non si divide il resto di `routes/allevamento.py` per pagina (mortalità, spostamenti, consegne…): funziona, ed è
  un lavoro grande con poco guadagno.
- Non si toccano Banca e Bot, che il grafo segnala come «poco coesi» ma sono stabili.
- `avvisi_nuovo_carico_siero` resta nelle route.

## Ordine di lavoro

1. Intervento 1: nuovo modulo, test puri, compatibilità, servizi aggiornati, prova sulla copia (prima/dopo identici).
2. Intervento 2: `bolla.js`, tre pagine, prova dal telefono.
3. README e questo piano aggiornati, `graphify update .` (gratis), commit e rilascio 3.1.4 fuori dai pasti, quando lo
   dice Andrea.
