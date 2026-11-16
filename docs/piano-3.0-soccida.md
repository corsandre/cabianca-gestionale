# Piano 3.0 — Compenso di soccida (scheda «Soccida»)

Scritto il 15/11/2026. Sostituisce l'Excel `Calcoli compenso Soccida v2` per il ciclo iniziato il 19/05/2026.

## Obiettivo

Una scheda dell'allevamento che dice, in ogni momento del ciclo:

1. quanto incasserò (resa oppure minimo garantito) e con quale saldo;
2. che probabilità ho di arrivare a premio, cioè di superare il minimo;
3. cosa sposta il risultato (giorni, peso di uscita, siero, mangime), per decidere.

All'inizio i numeri sono quasi tutti stimati. A ogni bolla, fattura e riscontro del macello una stima diventa un dato reale, fino al consuntivo.

## Regole del calcolo (confermate)

| # | Voce | Regola |
|---|---|---|
| 1 | Mangime consumato | kg delle bolle + giacenza iniziale − giacenza finale. Il siero non conta. Si usano bolle e fatture, mai i dati della cucina. |
| 2 | Carne valida | peso morto dei carichi «grassi» + peso morto degli «scarti» contato al 50%. Peso morto degli scarti = peso vivo × (1 − calo peso 16,38%). Quota e calo sono parametri modificabili. Vale sia per l'indice sia per il compenso. |
| 3 | Peso morto dei grassi senza riscontro | peso vivo della bolla × resa media dei carichi riscontrati del ciclo; 82% finché non ce n'è nessuno. |
| 4 | Indice di conversione | mangime consumato / carne valida. |
| 5 | Valore €/kg | percentuale della tabella, interpolata tra le due righe vicine, × prezzo di partenza × (1 + premio su tabella). Oggi 1,45 € e +20%. |
| 6 | Tabella oltre i limiti | sotto 2,9 si prolunga con lo stesso passo delle prime righe (+1,4 punti ogni 0,1). Sopra 4,0 resta il valore di 4,0: lì vince comunque il minimo. |
| 7 | Resa | €/kg × carne valida × (1 + premi da prontuario % + premio extra %). Premio extra (Esselunga) = 0 in questo ciclo. |
| 8 | Minimo del ciclo | 98.000 / 365 × giorni dall'ultimo giorno pagato del ciclo precedente (11/05/2026) alla fine di questo. Ogni giorno dell'anno è pagato una volta sola: se i cicli si accavallano, i giorni in comune non si pagano due volte e la data di inizio del ciclo non conta. |
| 9 | Esito | Veronesi paga il più alto tra *resa* e *minimo + fatture del siero*. Il siero lo pago io: al netto resta il più alto tra *resa − siero* e *minimo*. |
| 10 | Saldo | importo pagato − anticipi. |
| 11 | Suini Fattoria Ca' Bianca | esclusi da capi e carne. La fattura dei suinetti si paga a parte e non entra nel saldo. |

Controllo sul ciclo 6: mangime 699.280 kg, carne 203.059 kg, indice 3,444, valore 0,2596 €/kg, resa 56.924 €, minimo 59.605 €, siero 17.477 € → vince il minimo per 20.158 €.

## Cosa c'è già e cosa manca

Già nel gestionale: consegne di mangime e siero con foto della bolla, entrate e uscite dei suini con categoria (`fine_ciclo`, `scarto_sottopeso`, agriturismo) e peso vivo, mortalità, censimenti, consumi della cucina (`uso_pasti`), giacenza stimata dei silos, fatture SDI ricevute.

Manca: riscontro del macello sulle uscite, parametri del contratto, anticipi, giacenze contrattuali, collegamento tra fatture e bolle del siero, motore di calcolo, stime e scheda.

## Dati nuovi

- **Parametri di soccida per ciclo** (tabella `soccida_parametri`, una riga per ciclo, così i cicli chiusi non cambiano se cambia il contratto): posti, minimo annuo, prezzo di partenza, premio su tabella %, premi da prontuario %, premio extra %, quota scarti % (50), calo peso scarti % (16,38), resa di partenza dei grassi % (82), ultimo giorno pagato del ciclo precedente, giacenza iniziale e finale di mangime, data di fine prevista, peso vivo di uscita previsto.
- **Tabella di rapporto** (`soccida_tabella`: ciclo, indice, percentuale), copiata dal ciclo precedente alla creazione di un ciclo.
- **Anticipi** (`soccida_anticipi`: ciclo, data, importo, nota), inseriti a mano. Partenza: 6 × 9.000 €.
- **Riscontro del macello** sulle uscite (`spostamenti_animali`): capi riscontrati, peso morto medio, numero della bolla, foto del riscontro. Resa % calcolata.
- **Siero**: importo e fattura SDI collegata su ogni consegna (`consegne_siero`).
- **Chiusura**: fotografia del consuntivo, importo liquidato da Veronesi, bonifico a saldo.

Le colonne nuove passano da `_migrate_columns`, le tabelle nuove da `db.create_all()`, come da convenzioni.

## La scheda «Soccida»

Nuova voce nel menu dell'allevamento, visibile solo agli amministratori.

1. **Esito in alto**: «Premio probabile al 35%», importo atteso, distanza dal minimo, saldo previsto. Accanto, quanta parte del risultato poggia su dati reali (es. «dati certi 62%»).
2. **Indice**: indice stimato oggi e indice di pareggio, cioè quello sotto cui scatta il premio.
3. **Il conto passo per passo**, come l'Excel (righe 1–10 sopra). Ogni numero è marcato *reale* o *stimato*.
4. **Leve**: quanto vale 1 giorno in più, 1 kg di peso morto medio, 10 t di mangime, un carico di siero. Più un simulatore con data di fine, peso di uscita e siero modificabili, che ricalcola esito e probabilità.
5. **Carichi al macello**: previsti, partiti, riscontrati, con resa per carico.
6. **Controlli**: bolle contro fatture del siero; bolle contro cucina per mangime e siero.
7. **Storico**: i cicli passati a confronto.

Le impostazioni stanno in una scheda dedicata «Soccida» dentro Impostazioni allevamento: parametri, tabella, anticipi.

## Come nascono le stime

| Grandezza | Reale quando | Prima si stima con |
|---|---|---|
| Carne dei carichi partiti | arriva il riscontro | peso vivo della bolla × resa media |
| Carne dei capi in stalla | partono | capi presenti − mortalità attesa, × peso vivo di uscita previsto × resa |
| Mangime | ultima bolla e giacenza finale | bolle fino a oggi − giacenza dei silos + consumo recente per capo × capi × giorni residui |
| Siero € | arriva la fattura del mese | consegne non fatturate × prezzo medio, più il ritmo recente fino a fine ciclo |
| Giorni | ultimo camion | data di fine prevista |
| Premi da prontuario | li comunica Veronesi | quelli del ciclo scorso (8%) |

**Probabilità di premio.** Simulazione di qualche migliaio di scenari che fa variare resa, peso di uscita, mortalità residua, consumo residuo e siero residuo. L'ampiezza delle variazioni parte da quanto queste grandezze sono cambiate nei 6 cicli dell'Excel e si restringe da sola man mano che le stime diventano dati. La probabilità è la quota di scenari in cui *resa − siero* supera il *minimo*. È una stima di modello: va letta insieme all'intervallo (caso sfavorevole, atteso, favorevole) mostrato accanto.

## Fasi

Il ciclo sta finendo: prima viene ciò che serve per tirare i conti, poi le stime.

**Fase 0 — Dati (prima di scrivere codice)**
- Andrea: bolle mancanti di mangime e siero, bolle di entrata dei suinetti.
- Guardare in produzione una fattura del siero per vedere come sono fatte le righe dei carichi.
- Recuperare la giacenza iniziale al 19/05/2026.

**Fase 1 — Motore di calcolo** (`app/services/soccida.py`)
- Funzioni pure: dati in ingresso → conto completo, senza toccare il database.
- Test: deve riprodurre al centesimo i cicli 3, 4, 5 e 6 dell'Excel.

**Fase 2 — Dati e impostazioni**
- Tabelle e colonne nuove, scheda Impostazioni «Soccida», riscontro del macello nel form delle uscite (web e bot Telegram).

**Fase 3 — Scheda a consuntivo → rilascio 3.0.0**
- Sezioni 1, 2, 3 e 5 con le stime semplici della tabella sopra, senza probabilità.
- Da qui si può già chiudere il ciclo in corso.

**Fase 4 — Siero: fatture e bolle → 3.0.x**
- Lettura delle righe delle fatture SDI dei fornitori di siero, abbinamento alle consegne per data, quantità e numero di bolla.
- Segnalazioni: bolla senza fattura, fattura senza bolla, quantità diverse.
- Confronto bolle contro cucina.

**Fase 5 — Probabilità e simulatore → 3.1.0**
- Simulazione, leve, simulatore, grafico dell'andamento della probabilità nel ciclo.

**Fase 6 — Chiusura e storico → 3.2.0**
- Chiusura del ciclo con fotografia del consuntivo e confronto con la liquidazione di Veronesi.
- Import dei 6 cicli dell'Excel nello storico.

## Punti aperti

Confermati il 15/11/2026: prezzo di partenza 1,45 € e +20%; ultimo giorno pagato del ciclo scorso 11/05/2026; scarti al 50% con calo peso 16,38%.

Siero (deciso il 15/11/2026):
- nel conto entra il totale delle fatture con IVA, come nell'Excel;
- l'indicizzazione gasolio del mese si ripartisce sui carichi in proporzione alle tonnellate;
- ogni carico deve risultare in un solo ciclo: la scheda deve segnalare i carichi fatturati che non sono in nessun ciclo o sono in due;
- le fatture Nosari sono PDF (`*.xml.pdf` in uploads): una riga «DDT n del gg-mm-aaaa» seguita da tonnellate, 9,25 €/t e importo. Il numero del DDT è il campo `lotto` delle consegne. Righe già estratte in `docs/soccida-dati/siero-fatture-nosari-2026.json`;
- i 47 carichi dal 30/06 al 10/09/2026 sono stati inseriti in produzione dalle fatture (senza ora, caseificio e sostanza secca);
- carichi dell'1 e 4 maggio 2026 (fattura di maggio, 318,04 €): non erano nel conto del ciclo 6, si contano in questo ciclo (se vince il minimo vengono rimborsati);
- **assegnazione al ciclo modificabile**: per i carichi di siero e di mangime a ridosso della fine di un ciclo e dell'inizio del successivo si deve poter scegliere a mano il ciclo in cui contarli, indipendentemente dalla data. Lo stesso per le righe di fattura senza consegna (come quelle di maggio);
- mangime: i 15 carichi dal 19/05 all'1/09/2026 sono stati inseriti in produzione dall'elenco ordini Veronesi; non ce ne sono altri mancanti.

Prima stima a mano del 15/11/2026 (script e ipotesi in `docs/soccida-dati/prima-stima-2026-11-15.py`): indice 3,19 contro pareggio 3,22, margine sul minimo circa +2.200 €, premio al 59% circa. Da validare con Andrea prima di programmare.


1. Giacenza iniziale di mangime di questo ciclo: da recuperare.
2. Il mangime mangiato dai suini di Fattoria Ca' Bianca resta nel totale, come nell'Excel.

## Prototipo della scheda (15/11/2026)

Prototipo interattivo con i dati veri del ciclo: https://claude.ai/artifact/5MKo3yQa9Jf1izSEz372na (copia dei sorgenti in `docs/soccida-dati/prototipo/`: `Main` è la scheda, `Impostazioni` la scheda Soccida delle impostazioni con il testo «Come funziona», `Riscontro` il modulo degli spostamenti, con dentro il motore di stima in JavaScript da portare in Python).

Scelte da riportare nella scheda vera:
- lo **scenario standard** (data di fine, peso di uscita, resa, capi, premi, giacenza iniziale) si corregge a mano e si salva; le prove non lo toccano finché non si salva;
- la data di fine si può segnare «confermata da Veronesi», e l'incertezza sulla data si restringe;
- grafici: distribuzione del margine, probabilità per data di fine, griglia data × peso di uscita, leve;
- sezione «Dati da aggiornare»: per ogni dato lo stato (ipotesi, stimato, reale, da fare), quanto sposta il margine e l'azione per renderlo certo, in ordine di peso;
- «quanto è già reale» mostrato separato per mangime, siero e carne, non come percentuale unica.

Decisioni del secondo giro sul prototipo (15/11/2026):
- **due date nello scenario**: primo carico e ultimo carico previsti (partenza 03/12 e 23/12). Tra le due i capi escono in modo regolare, quindi mangime e siero residui = consumo giornaliero pieno × (giorni al primo carico + metà della finestra). Il minimo si paga fino all'ultimo carico. Un carico è di 120–135 capi, al massimo 2 al giorno: la scheda avvisa se la finestra è troppo stretta;
- **niente registrazioni doppie**: entrate dei suinetti e uscite al macello restano negli Spostamenti (tipo entrata/uscita, già esistenti). La scheda le legge soltanto e rimanda lì per inserirle;
- **riscontro del macello nel modulo degli spostamenti in uscita** (categorie fine ciclo e scarti): numero bolla del camion, data del riscontro, capi riscontrati, peso morto medio, foto; resa e peso morto totale calcolati. Vale per tutti gli spostamenti con stessa data e stessa bolla. Da verificare con Andrea se oggi un camion si registra con una riga sola o una per box;
- **siero in tre parti** nella barra «quanto è reale»: fatturato, consegnato non ancora fatturato (quantità vere, prezzo dell'ultima fattura), stimato;
- **Impostazioni › Soccida**: contratto, dati del ciclo, scenario standard, anticipi, tabella di rapporto, carichi a cavallo tra due cicli, e il testo «Come funziona il modulo» in 7 punti.

## Ultime conferme prima di programmare (15/11/2026)

- **Camion in uscita = una riga sola** negli Spostamenti. Alla riga si collegano i box svuotati, ognuno «del tutto» o «in parte» con i capi tolti (tabella figlia `spostamenti_box`: spostamento, box, capi, svuotato). Il conteggio dei capi per box legge da lì. Il riscontro del macello sta sulla riga del camion.
- **Suini di Fattoria Ca' Bianca in questo ciclo: 19** (confermato).
- **Anticipi**: le date si leggono dalla banca. Il pagante è «Società Agricola La Pellegrina S.p.A.», bonifico di lunedì tra il 15 e il 22 del mese. In questo ciclo finora: 13/07 18.000 € (fattura 1), 19/08 9.000 € (2), 21/09 9.000 € (3), 19/10 9.000 € (4) = 45.000 €. La scheda propone i bonifici trovati in banca e Andrea li conferma come anticipi del ciclo; restano modificabili a mano. Da chiarire se il totale del ciclo è 54.000 € o 63.000 € (con novembre e dicembre).

## Come va scritto il codice

- Il calcolo sta in un solo modulo di funzioni pure (`app/services/soccida.py`): riceve numeri, restituisce il conto. Non legge il database e non conosce Flask, così si prova da solo contro l'Excel.
- Un secondo modulo raccoglie i dati dal gestionale (consegne, spostamenti, fatture, censimenti, impostazioni) e li passa al calcolo. Chi cambia una regola del contratto tocca solo il primo; chi cambia da dove arrivano i dati tocca solo il secondo.
- Nessun numero del contratto nel codice: tutto in Impostazioni › Soccida, per ciclo.
- Nessuna registrazione doppia: la scheda legge Consegne, Spostamenti e fatture, non ha tabelle proprie per gli stessi dati.
- Ogni regola del conto ha un test con i numeri dell'Excel (cicli 3–6).
- La documentazione sta in tre posti: il testo «Come funziona» in Impostazioni (per chi usa), la sezione Soccida del README (per chi modifica), i commenti nel modulo di calcolo con il riferimento alla regola del contratto.
- Un rilascio per fase, con numero di versione e messaggio di commit come nel resto del progetto.

## Stato dei lavori (15/11/2026, sera)

Ramo `soccida-3.0`, niente ancora in git né in produzione. Versione portata a 3.0.0.

Fatto e provato in locale su una copia del database di produzione (`data/_test.db`):
- **Fase 1** — `app/services/soccida.py` (calcolo puro) e `tests/test_soccida.py`: 18 prove, cicli 1–6 dell'Excel (il 6 al centesimo; 1–5 entro lo 0,05% perché l'Excel usava i centesimi della vecchia tabella arrotondati).
- **Fase 2** — tabelle `soccida_parametri`, `soccida_tabella`, `soccida_anticipi`, `soccida_fatture`, `spostamenti_box`; colonne del riscontro su `spostamenti_animali`; pagina Impostazioni Soccida; camion in una riga con i box svuotati e riscontro del macello nei moduli degli Spostamenti (`_uscita_campi.html`, `_campi_uscita()`); `_live_count` e Analisi aggiornati per i camion da più box.
- **Fase 3** — scheda `/allevamento/soccida` (`soccida_dati.py`, `soccida_scheda.py`, `routes/soccida.py`, template): esito, scenario con prove ricalcolate sul server, tre grafici, leve, dati da aggiornare, conto, entrate/uscite, siero mese per mese. Con la probabilità e le leve dentro: la fase 5 è di fatto anticipata.
- README aggiornato (sezione Soccida, Spostamenti, struttura).

Differenze rispetto al prototipo: i valori dello scenario sono campi (date e numeri) e non cursori, e la pagina si ricalcola sul server, così il motore è uno solo. Il siero usa i totali fattura e, per il non fatturato, il prezzo medio dell'ultima fattura: l'abbinamento carico per carico con le righe delle fatture resta nella fase 4.

Dato emerso: con l'età media del censimento dell'11/09 la curva dà **169,2 kg** di peso vivo alla data media di uscita, non i 172 kg della stima a mano. Con 169,2 kg la scheda dice margine −1.200 € e premio al 44%; con +3 kg torna intorno a +3.900 € e 67%.

Da fare dopo il rilascio in produzione: compilare Impostazioni Soccida (partita IVA Nosari 00883710196, pagante «LA PELLEGRINA», ultimo giorno pagato 11/05/2026, giacenza iniziale, 19 suini) e confermare gli anticipi dai bonifici.

Restano: fase 4 (righe delle fatture abbinate alle bolle, segnalazioni per carico), fase 6 (chiusura con fotografia del conto, storico dei cicli dall'Excel), riscontro del macello dal bot Telegram.

Aggiornamenti del 15/11/2026, notte:
- **Anticipi del ciclo: 54.000 € in tutto** (confermato da Andrea).
- **Cursori tornati nello scenario**: date (± 21 giorni attorno a quella mostrata, più il campo data per scriverla) e valori (peso, resa, morti, premi, giacenza iniziale). Al rilascio del cursore la scheda si ricalcola sul server: restano i cursori e resta un motore solo.
- **Fase 4 spostata**: l'abbinamento tra righe delle fatture di siero e consegne non va nella scheda Soccida ma nella sezione **Fatture ricevute** (Finanza). La scheda Soccida tiene solo il riepilogo mensile bolle/fattura e legge i totali.
- Correzione: l'abbinamento tra righe delle fatture di siero e consegne va nella pagina **Consegne** (Allevamento), non in Fatture ricevute.

Aggiunto alla 3.0.0 su richiesta di Andrea (15/11/2026):
- **Fatture del siero abbinate alle consegne**, nella pagina Consegne (scheda Siero, solo admin): colonna «Fattura» con importo del carico ed esito, riepilogo in alto, righe di fattura senza consegna. Moduli `siero_fatture_pdf.py` (lettura del testo, con test) e `siero_fatture.py` (righe in `siero_fatture_righe`, abbinamento per numero di bolla e poi per data).
- **Controllo di ogni mattina alle 8:45**: legge le fatture di siero nuove e manda il riepilogo su Telegram (canale finanza), solo per le fatture degli ultimi 60 giorni. La prima lettura delle fatture già presenti va fatta dal pulsante «Cerca fatture nuove», che non manda messaggi.
- Sulla copia del database: 12 fatture lette, 196 carichi; nel ciclo in corso 87 carichi abbinati e le stesse differenze trovate a mano (11/09 e 26/10 quantità, 27/10 e 31/10 numero di bolla, 1 e 4 maggio senza consegna).

## Rilascio (15/11/2026, 22:25)

La 3.0.0 è in produzione (commit 60c3f57). Copia del database prima del rilascio: `data/gestionale.db.pre-deploy-3.0.0` sul server.
Impostazioni Soccida compilate: partita IVA Nosari, pagante «LA PELLEGRINA», ultimo giorno pagato 11/05/2026, giacenza iniziale 3.000 kg (ipotesi), 19 suini di Fattoria Ca' Bianca. Anticipi confermati dai bonifici: 45.000 € (13/07 18.000, 19/08, 21/09, 19/10 da 9.000); il bonifico del 22/06 da 29.494,51 € è il saldo del ciclo scorso e resta proposto senza essere un anticipo. Fatture di siero lette: 12, senza messaggi.
Restano: chiusura del ciclo con fotografia del conto, storico dei cicli dall'Excel, riscontro del macello dal bot Telegram.

## 3.0.1 — tabella di rapporto senza limiti (16/11/2026)

Chiarito con Andrea: le righe della tabella sono quelle date da Veronesi, ma da contratto il miglioramento non ha limite e il conto si fa comunque anche oltre il 4,0.
- **Indici migliori della prima riga** (2,8, 2,7, 2,62…): la tabella prosegue con il passo delle prime due righe (+1,4 punti ogni 0,1). Era già così.
- **Indici peggiori dell'ultima riga** (oltre 4,0): prosegue con il passo delle ultime due (−0,83 punti ogni 0,1), mai sotto zero. Prima restava ferma a 9,46: corretto. Lì vince quasi sempre il minimo, ma resa e indice mostrati ora sono quelli veri.
- In Impostazioni Soccida le righe di Veronesi restano modificabili; sopra e sotto compaiono in grigio le righe calcolate (2,6–2,8 e 4,1–4,2) per far vedere come prosegue.
La regola 6 in cima a questo piano («sopra 4,0 resta il valore di 4,0») è superata da questa.

## 3.0.2 — scheda Soccida in sola lettura per altri utenti (16/11/2026)

Chiesto da Andrea per l'utente agnese94.
- Nuova sezione utente «soccida» (Impostazioni → Utenti → «Soccida (sola lettura)»): chi ce l'ha, insieme ad «Allevamento Suini», vede la voce Soccida nel menu e la scheda intera con i calcoli.
- Può provare gli scenari (non salvano niente), ma non vede «Salva come standard» né «Impostazioni Soccida»; impostazioni, tabella, anticipi e fatture restano agli amministratori (403 per gli altri).
- Prova dei permessi: `data/_prova_permessi.py` su `data/_test.db` (amministratore, agnese94 con la sezione, maria senza).
- Dopo il rilascio va spuntata la casella per agnese94 in produzione.

## 3.0.3 — nuovo censimento da web con ultimo censimento, stima e modifiche di gruppo (16/11/2026)

Chiesto da Andrea: compilare il censimento dal sito senza ricopiare 54 box guardando la pagina sotto.
- **Modal «Nuovo censimento»** rifatto: una tabella per capannone, una riga per box con l'**ultimo censimento** (capi, età e peso di allora) e la **nostra stima** alla data scelta (capi dal conteggio live, età proiettata, peso dalla curva di accrescimento — gli stessi numeri della pagina Censimento).
- **Campi già compilati con la stima** (capi, età, peso). Quello che si cambia si colora; per i capi compare lo scarto dall'atteso sul box, sul capannone e sul totale in alto. Resta l'avviso «sopra capienza».
- **Età ↔ peso collegati**: cambiando l'uno, l'altro si ricalcola dalla curva finché non lo si scrive a mano (stessa interpolazione di `peso_da_giorni` / `giorni_da_peso`, rifatta in JavaScript sui punti della curva passati alla pagina).
- **Modifica di gruppo**: spunta per box, per capannone, «Tutti / Nessuno»; nella barra in alto si scrive l'età oppure il peso e «Applica» li mette nei box selezionati che hanno capi. «Rimetti la stima» riporta i selezionati ai valori proposti. I capi non si cambiano in gruppo.
- **Cambio data**: attesi e stima si ricalcolano a quel giorno con la nuova rotta `GET /allevamento/censimento/stima?data=AAAA-MM-GG`; i campi toccati a mano non vengono sovrascritti. La data non può essere futura.
- Su telefono ultimo censimento e stima stanno in una riga piccola sotto ogni box.

Nel codice: `_stima_censimento(ciclo, al_giorno)` e `_proiezione_giorni_peso(ciclo, al_giorno)` in `app/routes/allevamento.py`; `punti_curva_accrescimento()` (prima privata) in `app/services/allevamento_scorte.py`. I nomi dei campi del modulo (`box_N`, `giorni_N`, `peso_N`) sono gli stessi di prima; nessuna modifica al database, bot Telegram non toccato.

Due comportamenti cambiati:
- un box salvato con 0 capi non conserva più età e peso (sporcherebbero la stima dei censimenti successivi);
- salvando senza toccare nulla, età e peso stimati vengono registrati nel censimento (prima restavano vuoti).

Prove: `data/_prova_censimento.py` su `data/_test.db` (stima uguale alla pagina, rotta per data, salvataggio, box vuoto) e il JavaScript del modal in Chromium senza interfaccia (differenze, collegamento età/peso, gruppo, rimetti la stima, cambio data con risposta finta), da PC e a 390 px.
