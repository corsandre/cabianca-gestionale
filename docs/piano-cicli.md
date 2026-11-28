# Piano: più cicli nell'allevamento (selettore del ciclo)

Proposta del 28/11/2026, da confermare con Andrea. Il ciclo 05/2026 si chiude la settimana prossima.

## Com'è oggi

- **I dati sono già divisi per ciclo**: censimenti, mortalità, spostamenti, consegne di siero e mangime, pasti, trattamenti, Modello 4 e soccida hanno tutti `ciclo_id`. Non serve cambiare il database per separare i cicli.
- **Le pagine invece vedono solo il ciclo attivo**: tutte le pagine dell'allevamento e della soccida chiamano `ciclo_attivo()`. Se nessun ciclo è attivo mostrano «Nessun ciclo attivo» e i dati di quello chiuso non si vedono più.
- **«Chiudi ciclo»** (Impostazioni) mette `attivo = False` e `data_fine = oggi`. La data non si può scegliere.
- **«Nuovo ciclo»** disattiva quello attivo e ne crea un altro. Così un solo ciclo resta attivo, ma non c'è nessun controllo.
- **Le pagine usano sempre la data di oggi**: Analisi calcola le serie fino a oggi, non fino alla fine del ciclo, e legge l'impianto «dal giorno di inizio in poi», senza un limite di fine. Su un ciclo chiuso darebbero giorni vuoti e dati del ciclo successivo.
- **Le giacenze di mangime e siero sono di stalla, non di ciclo**: consegne meno consumi, da sempre o dall'ultima ricalibrazione. È giusto così, perché il mangime rimasto nel silo passa al ciclo nuovo. Va solo indicato chiaramente.
- **La soccida sa già del ciclo precedente**: copia il contratto e la tabella e prende la giacenza finale come giacenza iniziale.

## Regole proposte

1. **Un solo ciclo attivo.** Bot Telegram, impianto EM2000, avvisi delle 8:45 e pasti stimati lavorano solo su quello. Durante un accavallamento il ciclo nuovo è «in avvio» e i suoi dati si inseriscono a mano (vedi «Cicli che si accavallano»).
2. **Il selettore del ciclo serve solo a guardare.** Su un ciclo chiuso le pagine mostrano tutto, ma in sola lettura: niente pulsanti per aggiungere, modificare o eliminare. In testa compare una fascia «Ciclo 05/2026 — chiuso il …, sola lettura».
3. **Le eccezioni sul ciclo chiuso**, cioè le cose che arrivano dopo la chiusura:
   - riscontro del macello sugli ultimi carichi;
   - fatture del siero;
   - liquidazione di Veronesi, giacenza finale e premi in Soccida;
   - documenti: bolle e Modello 4 da allegare.

   Le può fare solo l'admin, anche a ciclo chiuso. Niente «riapri ciclo».
4. **Il ciclo scelto è ricordato per utente** (in sessione) e vale per tutte le pagine dell'allevamento. Si può anche indicare nell'indirizzo con `?ciclo=<id>`, così un link salvato apre sempre lo stesso ciclo. Se non si sceglie niente si vede il ciclo attivo.
5. **Su un ciclo chiuso «oggi» diventa la data di fine**: conteggi, età, pesi, grafici e soccida si fermano lì.

## Pagine: cosa cambia

| Pagina | Ciclo chiuso: cosa mostra | Lavoro |
|---|---|---|
| Riepilogo (index) | capi a fine ciclo, morti, totali di alimentazione, statistiche di fine ciclo | ciclo dal selettore, «oggi» = fine; nascondere scorte e avvisi di oggi |
| Mortalità | elenco completo | sola lettura |
| Censimento | censimenti e dettaglio | sola lettura |
| Spostamenti / Modello 4 | carichi, bolle, PDF del Modello 4 | sola lettura, ma l'admin può ancora inserire il riscontro del macello e allegare le bolle |
| Confronto con il PC | — | solo per il ciclo attivo (il PC è lo stato di adesso) |
| Consegne | siero e mangime del ciclo, fatture del siero | sola lettura, abbinamento delle fatture ancora aperto all'admin |
| Alimentazione / Razione | pasti del ciclo | sola lettura; la razione serve solo al ciclo attivo |
| Trattamenti | trattamenti e somministrazioni | sola lettura; nessuna somministrazione in attesa |
| Analisi | serie dall'inizio alla fine del ciclo | fermare a `data_fine`, impianto entro le date del ciclo, **più il confronto tra cicli (sotto)** |
| Soccida | conto definitivo | ciclo dal selettore; liquidazione, giacenza finale e premi ancora modificabili dall'admin |
| Curva di accrescimento | — | è unica per tutti i cicli, non cambia |
| Impostazioni | elenco dei cicli | chiusura con la data scelta, apertura del ciclo nuovo (sotto) |

## Confronti tra cicli (statistiche)

Nella pagina **Analisi** dell'allevamento:

- **«Confronta con»**: un menu che sceglie un altro ciclo, di norma il precedente. Le curve si allineano sul **giorno di ciclo** (giorno 1 = primo censimento), non sulla data, così due cicli con inizi diversi si sovrappongono. Il ciclo di confronto è disegnato tratteggiato e in grigio.
- **Tabella riassuntiva dei cicli**, una riga per ciclo:
  - durata;
  - capi entrati e capi usciti;
  - mortalità in %;
  - peso medio in uscita;
  - mangime e siero per capo;
  - indice di conversione stimato;
  - compenso di soccida;
  - premio raggiunto sì o no.
- I numeri si calcolano dagli stessi dati delle pagine, non si salvano. L'unica eccezione è la «fotografia» del conto di soccida (fase 6 del piano soccida): il conto chiuso non deve cambiare se domani cambia una regola di calcolo.
- **Cicli vecchi dall'Excel** (6 cicli in «Calcoli compenso Soccida»): si possono aggiungere più tardi, solo come righe della tabella riassuntiva (senza pasti né censimenti). Non è necessario per la settimana prossima.

## Chiusura e apertura (procedura)

**Chiudi ciclo**: una finestra con la data di fine (di norma il giorno dell'ultimo carico) e un controllo prima di confermare:

- capi ancora presenti secondo il gestionale: devono essere 0, altrimenti avviso;
- carichi senza riscontro del macello;
- trattamenti ancora aperti;
- consegna di siero ancora aperta.

Sono avvisi e non blocchi: si può chiudere lo stesso.

**Apri ciclo nuovo**: nome, data di inizio e note. Se nessun ciclo è attivo diventa subito attivo, altrimenti parte «in avvio» e diventa attivo alla chiusura del vecchio. Al massimo un ciclo in avvio.

## Cicli che si accavallano: versione semplice (scelta il 28/11/2026)

Di solito i cicli non si accavallano. Questa volta sì, per al massimo una decina di giorni: i suinetti arrivano **giovedì 3/12/2026**. In quali capannoni e su quale linea ancora non si sa, dipende da quanti ne portano. Hanno il loro mangime in un silo a parte e non mangiano siero nelle prime settimane.

Per non complicare il sistema per così pochi giorni **non si dividono capannoni o linee tra i cicli**:

1. **Il ciclo vecchio resta l'unico attivo.** Bot, impianto e avvisi lavorano su quello come oggi.
2. **Il ciclo nuovo si apre giovedì «in avvio».** Si vede nel selettore e ci si può scrivere, ma bot, impianto e avvisi non lo usano. Censimento d'arrivo, morti, trattamenti, consegne di mangime ed eventuali pasti a mano si inseriscono dalle pagine del gestionale, con il ciclo nuovo scelto nel selettore.
3. **Pasti letti dal PC: pulsante «Sposta sul ciclo nuovo».** Andrea fa mangiare sempre prima i piccoli e poi i grandi. Le letture si registrano da sole sul ciclo attivo come oggi. Su quelle dei piccoli Andrea preme «Sposta sul ciclo nuovo», su quelle dei grandi non fa niente.
   - Il pulsante sta su ogni lettura del PC del giorno (pagina Alimentazione e Impianto), solo se c'è un ciclo in avvio. C'è anche «Riporta sul ciclo attivo» per annullare.
   - Spostare agisce sulla **lettura del PC**, non sulla riga del pasto. La lettura dice a quale ciclo appartiene: il pasto del ciclo nuovo si scrive con i suoi valori, e quello del ciclo vecchio si ricalcola con le letture rimaste, oppure si toglie se non ne restano. Così l'ordine non conta: si può spostare prima o dopo che arrivi la lettura dei grandi.
   - Come aiuto la lettura mostra la ricetta letta dallo schermo: con una ricetta diversa per i piccoli si capisce subito quale spostare.
4. **Controllo nel bot.** Un morto o un trattamento registrato in un box che per il ciclo attivo è vuoto dà un avviso: «questo box non ha capi nel ciclo attivo: se è del ciclo nuovo registralo dal gestionale».
5. **Mangime: ogni ciclo scala dalle sue consegne.** Durante l'accavallamento:
   - **Ciclo vecchio**: il conto di oggi senza le consegne e i pasti del ciclo nuovo.
   - **Ciclo nuovo**: le sue consegne meno i suoi pasti, cioè le letture spostate e quelli inseriti a mano.
   - Ognuno ha la sua giacenza, la sua previsione di esaurimento e la sua ricalibrazione (la ricalibrazione prende il ciclo).
   - L'avviso Telegram di esaurimento vale per tutti e due. «Spazio per un carico» resta solo per il ciclo vecchio, perché la capacità del silo dei piccoli non si imposta.
6. **Chiusura del ciclo vecchio**: il ciclo nuovo diventa attivo e tutto passa a lui come oggi, cioè silo, conti, bot e impianto. La giacenza la inserisce Andrea con la ricalibrazione.
7. **Siero**: non si accavalla mai, quindi non cambia niente.

### Condizione sul PC (da verificare prima di giovedì)

Il gestionale riconosce le letture per data, **orario del pasto sul PC** e linea.

- **Il pasto dei piccoli deve avere un orario suo sul PC**, anche di pochi minuti prima di quello dei grandi. Se i piccoli e i grandi della stessa linea girano con lo stesso orario, la seconda lettura sovrascrive la prima e i dati dei piccoli si perdono.
- **I due orari devono stare entro 120 minuti**, così il gestionale li conta come lo stesso pasto (1, 2 o 3). Il PC impiega circa un'ora per tutto l'allevamento. Si porta `MINUTI_STESSO_PASTO` da 90 a 120; tra un pasto e l'altro ci sono più di 4 ore, quindi non si confondono.
- **Confermato da Andrea (28/11)**: i piccoli avranno una ricetta e un orario loro sul PC.
- **Siero e orario effettivo del pasto**: il siero si gestisce solo sul ciclo attivo (vecchio). L'orario effettivo si prende solo dalle letture del ciclo attivo: quelle spostate sul ciclo nuovo non contano.

*(Scartata: la gestione completa con capannoni assegnati ai cicli, orari e ricette per ciclo e giacenze per ciclo. Si può riprendere se gli accavallamenti diventano frequenti.)*

## Fasi e rilasci

**Fase 0 — Entro mercoledì 2/12/2026 (arrivo dei suinetti giovedì 3/12), 3.5.0**
- Stato del ciclo: attivo, in avvio o chiuso. Apertura di un ciclo «in avvio» con il vecchio ancora attivo.
- Selettore del ciclo (ciclo attivo e in avvio) nelle pagine di tutti i giorni: Riepilogo, Alimentazione, Mortalità, Censimento, Spostamenti, Trattamenti, Consegne. Con un ciclo in avvio si può scrivere.
- Ciclo della lettura del PC e pulsanti «Sposta sul ciclo nuovo» e «Riporta sul ciclo attivo», con il ricalcolo del pasto del ciclo vecchio.
- Avviso nel bot sui box vuoti nel ciclo attivo.
- Giacenza del mangime per ciclo durante l'accavallamento (ciascuno scala dalle sue consegne), ricalibrazione con il ciclo, avviso di esaurimento per tutti e due.
- `MINUTI_STESSO_PASTO` a 120; orario effettivo del pasto e siero solo dalle letture del ciclo attivo.
- Soccida del ciclo in avvio: non si apre finché il vecchio non è chiuso, perché le servono la data di fine e la giacenza finale del ciclo vecchio. I parametri si copiano alla chiusura.
- Chiusura del ciclo vecchio: il ciclo in avvio diventa attivo.
- Prova su una copia del DB di produzione: ciclo in avvio, due letture della stessa linea a orari vicini, una spostata.

**Fase 1 — Prima della chiusura del ciclo vecchio, 3.5.x**
- Selettore completo (anche i cicli chiusi), ciclo in sessione e `?ciclo=`; una funzione sola `ciclo_scelto()` nelle pagine che si guardano.
- Sola lettura sui cicli chiusi (fascia in testa, pulsanti nascosti, controllo anche nelle rotte POST), con le eccezioni dell'admin.
- «Oggi» = data di fine per un ciclo chiuso: Riepilogo, Analisi (con l'impianto filtrato sulle date del ciclo), Soccida, Trattamenti.
- Chiusura con la data scelta e i controlli; apertura solo senza un ciclo attivo.
- Prova su una copia del DB di produzione: chiudere il 05/2026, aprirne uno di prova, girare tutte le pagine su entrambi.

**Fase 2 — Confronti, 3.6.0**
- «Confronta con» in Analisi (allineamento sul giorno di ciclo).
- Tabella riassuntiva dei cicli.
- Fotografia del conto di soccida alla chiusura.

**Fase 3 — Più avanti**
- Storico dall'Excel nella tabella riassuntiva.
- Riscontro del macello dal bot.

## Da decidere con Andrea

Risposte del 28/11/2026:
- Questa volta i cicli si accavallano: i suinetti stanno in capannoni a parte, su linee separate, e mangiano diverso. Consegne e spostamenti li registra Andrea sul ciclo giusto, e la giacenza che passa al ciclo nuovo la inserisce a mano.
- Sul ciclo chiuso basta l'admin.
- Dalla finanza servono solo le fatture del siero e gli acconti e i saldi di Veronesi, da confrontare con i calcoli. Già tutto in Soccida: niente costi in più nella tabella riassuntiva.

- 28/11: il mangime dei suinetti va in un silo a parte. I cicli si dividono per capannone, non per linea: se una linea serve due cicli, mangiano a orari diversi e Andrea disattiva i box dal PC. Il gestionale legge soltanto i consumi.

- 28/11: conto del mangime semplice: durante l'accavallamento una giacenza per ciclo; alla chiusura del ciclo vecchio silo e conti passano al ciclo nuovo come oggi. Il siero non si accavalla mai (i piccoli non lo mangiano nelle prime settimane).

- 28/11: niente divisione per capannoni o linee. Il ciclo nuovo è «in avvio» e i suoi dati si inseriscono a mano. Le letture del PC dei piccoli (che mangiano sempre prima dei grandi) si spostano con il pulsante «Sposta sul ciclo nuovo».

Ancora aperte:
1. In quali capannoni vanno i piccoli (dipende da quanti arrivano) e quando esce l'ultimo carico del ciclo 05/2026.
- 28/11: ricetta e orario propri per i piccoli sul PC, entro 120 minuti da quello dei grandi. Mangime: ogni ciclo scala dalle sue consegne.

## Stato dei lavori

**28/11/2026 — fase 0 fatta (3.5.0), da rilasciare entro mercoledì 2/12.**
- Fatto: ciclo «in avvio» e apertura con il vecchio attivo; selettore nelle pagine di tutti i giorni (anche Analisi);
  «Sposta sul ciclo nuovo» / «Riporta sul ciclo attivo» in Alimentazione (letture dello stesso pasto e linea
  sommate, pasto di ogni ciclo ricalcolato, orario effettivo solo dal ciclo attivo); giacenza del mangime per ciclo
  con ricalibrazione; `MINUTI_STESSO_PASTO` a 120; chiusura con data, controlli e giacenza di tutti i silos (il
  ciclo in avvio diventa attivo); avviso del bot su morti e trattamenti in box vuoti del ciclo attivo; censimento dal bot
  sospeso durante l'accavallamento (si fa dal sito); recupero delle linee non lette solo sui box del ciclo attivo;
  promemoria dei trattamenti delle 7 anche per il ciclo in avvio; messaggio dell'impianto che ricorda lo spostamento.
- Prova: `data/_prova_cicli.py` su una copia di `data/_prod.db` (17/11), tutto OK. Comando:
  `docker run --rm -v "$PWD":/app -w /app -e RUOLO=sviluppo -e SECRET_KEY=prova -e DATABASE_URL=sqlite:////app/data/_test_cicli.db cabianca-gestionale:latest python data/_prova_cicli.py`
- Non c'è un avviso Telegram del mangime (né prima né ora): la scorta del ciclo in avvio si vede nel Riepilogo.
- La Soccida resta sul ciclo attivo: quella del ciclo nuovo si apre dopo la chiusura del vecchio.
- Rilasciata in produzione il 28/11/2026 alle 9:30 (commit 46a0030, `deploy.sh tutto`).

**28/11/2026 — fase 1 fatta (3.5.1).**
- Selettore con i cicli chiusi (menu «Cicli chiusi…»), anche in Soccida e Impostazioni Soccida; in Impostazioni
  allevamento i cicli precedenti hanno «Apri» e «Soccida».
- Ciclo chiuso: fascia «Ciclo chiuso il …»; per gli utenti sola lettura (pulsanti dei moduli disattivati, i pulsanti
  che aprono i modal nascosti, e il server rifiuta i POST con il ciclo_id di un ciclo chiuso); l'admin può correggere
  tutto (deciso con Andrea il 28/11), con la fascia in rosso.
- «Oggi» = data di fine: Panoramica (conteggio alla data di fine, niente scorte), Mortalità (settimana della fine),
  Alimentazione (giorno di fine), Analisi (serie e letture dell'impianto fino alla fine), Soccida (scheda alla data di
  fine; senza giacenza finale comunicata la stima è la giacenza della stalla del giorno dopo la fine).
- La Soccida di un ciclo in avvio non si apre (resta quella del ciclo attivo, con un messaggio).
- Prova: `data/_prova_cicli.py`, parte «FASE 1», tutto OK.
- Da ricordare: la Soccida del ciclo nuovo copia la giacenza finale del vecchio quando la si apre la prima volta;
  conviene inserire la giacenza finale del 05/2026 prima di aprire la Soccida del ciclo nuovo (o correggerla a mano).

**28/11/2026 — fase 2 in parte (3.6.0): fotografia del conto e tabella dei cicli, con lo storico dall'Excel.**
- Soccida › «Conto salvato»: salva i numeri del conto (SoccidaFotografia, si può rifare, vale l'ultima) con
  l'importo liquidato da Veronesi; mostra salvato contro ricalcolato adesso e la differenza con la liquidazione.
- `/allevamento/cicli` «Cicli a confronto» (link da Soccida e Impostazioni): cicli storici 1-6 dall'Excel (da
  controllare da Andrea: pulsante Modifica, casella «Controllato») e cicli del gestionale; giacenze iniziale e finale
  in colonna con gli avvisi; per un ciclo non finito i valori sono la stima della Soccida (kg a capo e peso morto sui
  capi usciti più quelli ancora da caricare).
- Dall'Excel: cicli 1-3 senza giacenze; ciclo 4 con 500 kg sommati alle bolle (presi come giacenza iniziale), finale
  non scritta; ciclo 5 iniziale 4.000 kg (il 4 non ha la finale: avviso); 5 → 6: 10.000 kg; 6 → 05/2026: 3.000 kg.
- Resta della fase 2: «Confronta con» in Analisi (curve allineate per giorno di ciclo), da fare quando il ciclo nuovo
  avrà qualche settimana di dati.
