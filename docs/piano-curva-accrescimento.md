# Piano — Curva di accrescimento (PC e gestionale)

Scritto il 17/11/2026, aggiornato con le indicazioni di Andrea lo stesso giorno. Regola: **poco, ma ben ragionato**.
Una sola curva, quella del PC, uguale nel gestionale; la posizione dei suini sulla curva la decidono i censimenti.

## Come funziona (deciso da Andrea, 17/11/2026)

- **La curva è quella del PC**: curva n. 2 «RICETTA VERONESI LC – SUINI PESANTE LC», l'unica usata dai box veri (1–54).
  Il gestionale la copia con «Aggiorna dal PC» e non la modifica per conto suo.
- **Le età dei suini non si leggono dal PC.** Al censimento Andrea scrive il peso, stimato o pesato a campione; il
  gestionale ricava l'età dalla curva, cioè **il punto della curva in cui si trovano davvero**. Se serve, Andrea
  corregge l'età dei box sul PC con quella del gestionale, così mangiano la razione giusta per il loro peso.
- Per questo l'età nel gestionale non è l'età anagrafica: è la posizione sulla curva. Lo scarto dalla curva è già
  dentro l'età del censimento e non va aggiunto altrove (vedi «Soccida»).
- Il PC dosa **per età** (`BOX.DB`: `ETA`, `NRCURVA`, `PERRAZIONE`). Il peso della curva sul PC non decide la razione.

## Fatto

**Curva corretta sul PC (Andrea, 17/11/2026), verificata rileggendola dal PC.** Solo i pesi; razioni invariate.

| Età | Prima | Ora | |
|---|---|---|---|
| 0 | 20,0 | **26,0** | peso d'arrivo vero; il primo scaglione passa da 1.429 a 571 g/giorno |
| 7 – 210 | | invariati | |
| 217 | 174,0 | **177,0** | |
| 224 | 175,0 | **181,0** | |
| 231 | 176,0 | **184,8** | |
| 238 | 178,0 | **188,5** | |
| 245 | 179,0 | **192,0** | |
| 252 | 180,0 | **195,4** | |
| 259 | 181,0 | **198,6** | |
| 266 | 182,0 | **201,7** | |
| 273 | 183,0 | **204,7** | |

La coda vecchia cresceva 160 g/giorno con 3,1 kg di razione (19 kg di mangime per kg di crescita). Quella nuova scende
da 585 a 430 g/giorno (da 5,4 a 7,2 kg di mangime per kg): è un punto di partenza, da tarare con i camion di dicembre.

**Da dove vengono i numeri**
- Pesi delle bolle dei cicli 4–6 (Excel `Calcoli compenso Soccida v2`): all'uscita i suini pesano in media 2–10 kg più
  della curva (ciclo 4 183,6 kg a 218 giorni, ciclo 5 176,8 a 199, ciclo 6 176,3 a 211).
- Consumo della cucina di questo ciclo (torna con le bolle: 668,8 t contro 674,0 t): 83–86% della razione della curva,
  il resto lo spiegano la % dei box (94–97%) e il siero (circa 0,5 kg di mangime equivalente al giorno).
- Le colonne «1», «2», «3» della foto del PC sono le razioni delle curve 1, 2 e 3: nel gestionale c'è la 2.
- Tabelle del PC lette in sola lettura via SFTP: `pc/db/new/CurveNEW.DB` (nomi), `curvepuntoNEW.db` (40 punti ogni
  7 giorni; per la curva n colonne `HGEn` età, `HGPn` peso, `HGn` razione), `BOX.DB`.

## Nella 3.1.0

1. **Pagina «Curva di accrescimento»** (Impostazioni allevamento): punti con peso e razione modificabili, scaglioni
   (accrescimento e razione al giorno, mangime e indice), due grafici.
2. **«Aggiorna dal PC»**: legge in sola lettura la curva usata dalla maggior parte dei box con capi, mostra i punti
   diversi e sostituisce la curva del gestionale solo con «Sostituisci con la curva del PC».
3. Correzione: un punto nuovo della curva senza razione dava errore in produzione (colonna obbligatoria dal modulo v1).
4. Censimenti contro la curva teorica (sezione sotto).

**Al rilascio**: «Aggiorna dal PC» sulla curva di produzione (oggi diversa in 10 punti: lo 0 e la coda) e
controllo che i pesi stimati nelle pagine Censimento e Soccida siano sensati.

## Soccida: lo scarto dalla curva si conta una volta sola

Nel censimento del 16/11 i pesi scritti (160, 158, 150 kg) hanno dato età di 188, 185 e 173 giorni: in media circa
4 kg sopra la curva rispetto alle età del PC. È proprio il modo di lavorare deciso sopra, ma lo scenario della Soccida
aggiunge anche «+4 kg rispetto alla curva»: contato due volte.

| Caso | Margine | Premio |
|---|---|---|
| Età del censimento + 4 kg (oggi, doppio) | +17.800 € | 96% |
| Età del censimento, 0 kg (corretto) | +10.900 € | 86% |

**Da fare**: in Impostazioni Soccida «kg di peso vivo in più rispetto alla curva» a 0. Da qui in poi quel campo serve
solo per le prove di scenario, non per correggere la curva.

Nota: con la curva nuova la stima di oggi della Soccida non cambia (uscita media a circa 209 giorni, prima della
coda). Cambiano le leve sui ritardi: 7 giorni in più costano circa 5.500 € invece di 8.800 €.

## Curva teorica dall'arrivo e scarti dei censimenti (fatto, 3.1.0)

**Curva teorica dall'arrivo e scarti dei censimenti.** Per ogni gruppo di box entrato insieme:
- età all'arrivo = età della curva al peso d'arrivo (26 kg → 0 giorni), registrata negli Spostamenti in entrata;
- età teorica oggi = età all'arrivo + giorni passati;
- a ogni censimento: età del censimento − età teorica = **giorni avanti o indietro sulla curva**, e lo stesso in kg.

Una tabella per censimento nella pagina della curva, con i gruppi di box sotto. Serve a vedere se i suini vanno più o
meno veloci della curva e a tarare la curva ciclo dopo ciclo. In questo ciclo le entrate dei suinetti non sono negli
Spostamenti: l'arrivo di ogni box è il primo censimento in cui compare (segnato con *).

Primo risultato, censimento del 16/11 (età ricavate dai pesi scritti): **+6,8 giorni, +4,5 kg** sulla curva teorica.
Arrivati il 19 e 22/05 +2 giorni; il 3/06 +12; il 9/06 +6; il 26/06 (box 22, 23, 47, 48) +13. Le età teoriche
coincidono con quelle del PC (186, 173, 167 giorni). I censimenti fino all'11/09 hanno le età proiettate, quindi scarto 0.
Il gruppo del 3/06 (+12 giorni) è quello da guardare: o crescono davvero di più, o il peso scritto è alto.

**Entrate registrate (3.1.1, 17/11/2026).** Le 4 entrate dei suinetti del ciclo sono negli Spostamenti, un camion per
censimento d'arrivo: 19/05 600 capi, 22/05 152, 03/06 575, 09/06 550 (capi = aumento del censimento + morti nel
frattempo; box come nel censimento). Peso d'ingresso provvisorio dal PC (26,4 / 28,2 / 29,3 / 29,3 kg): Andrea aggiunge
bolle e pesi veri. Con l'arrivo dalle entrate, al 16/11: **+8,8 giorni, +5,8 kg** (19/05 +6,3; 22/05 +6,2; 03/06
+13,3; 09/06 +7,2). I box riempiti il 26/06 e l'11/09 sono spostamenti interni: per loro resta il primo censimento (*).

## 3.1.2 — peso teorico, riga «Oggi» e grafico (17/11/2026, chiesto da Andrea)

- Tabella dei censimenti: anche **peso teorico** (curva all'età teorica) e **peso del censimento** (quello scritto).
- **Riga «Oggi»** in cima: ultimo censimento + aggiornamenti, come la stima della pagina Censimento. Per ogni gruppo
  l'età da scrivere sul PC se si sceglie di aggiornare, la razione con l'età teorica e con quella aggiornata e il mangime
  in più fino all'ultimo carico previsto. La scelta resta di Andrea: aggiornare il PC (mangiano per il loro peso) o
  lasciare l'età (seguono la curva).
- **Grafico** del peso medio: curva teorica (tratteggiata dopo oggi), censimenti, oggi, camion al macello; per tutti o
  per gruppo d'arrivo.
- Gruppi senza entrata: non più «arrivo» ma «Dal censimento del…», con la nota giusta. Prossimi cicli: un box riempito
  con uno spostamento interno registrato eredita l'arrivo dei box da cui vengono i capi.
- Sulla copia di oggi: stimati 157,2 kg contro 151,4 teorici (+5,8 kg); aggiornando le età sul PC +2,1 t di mangime
  fino al 19/12, di cui 1 t il gruppo del 3/06.

## Rimandato (solo se servirà)

- **Rapportino peso** (idea di Andrea, 17/11/2026): un controllo del peso senza rifare la conta dei capi (data, box
  pesati, capi pesati, peso medio, «pesato» o «stimato»), da fare più spesso dei censimenti. Entrerebbe come punto in
  più nella tabella e nel grafico, distinto dai censimenti, e direbbe quali pesi sono misurati. Il censimento resta
  com'è (la conta dei capi è la base di conteggio live, confronto con il PC, mortalità e Soccida). Nella pagina
  della curva i titoli potrebbero parlare di «pesi ai censimenti»: per ora lasciati così.

- Camion contro curva: peso vivo delle bolle contro il peso della curva dei box svuotati.
- Grafico consumo reale per capo contro razione della curva × % dei box.
- Peso «pesato» distinto dal peso stimato nel censimento.

## Decisioni aperte (Andrea)

1. **Prossimo ciclo**: con 26 kg = età 0, la razione del primo giorno è 1,0 kg (in questo ciclo, entrati a età 5, circa
   1,2; nella prima settimana hanno mangiato 1,02 kg al giorno). Da sentire con il tecnico di Veronesi o il veterinario.
2. **Taratura della coda** con i camion di dicembre.

## Prove

- `data/_prova_curva.py`, `data/_prova_curva_pc.py` (con le tabelle del PC copiate in `data/_pc`): pagina, salvataggi,
  «Aggiorna dal PC», permessi.
- `data/_prova_coda_curva.py`, `data/_prova_razione_reale.py`, `data/_prova_doppio_peso.py`: i numeri di questo piano.
- `tests/test_curva.py`: scaglioni, lettura della curva dal PC, differenze.
