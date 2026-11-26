# Stile etichette «base-2026»

Il primo stile del generatore di etichette, del 2026: sfondo bianco per consumare poco toner,
una sottile fascia verde (#009d5a) con un filo oro (#c6a96f) in alto, il nome del prodotto in Yeseva One
bordeaux, testi in Fira Sans e un riquadro verde con lotto e scadenza.

## File

| File | Cosa fa |
|---|---|
| `foglio.html` | il documento intero: pagina A4 (o una sola etichetta per l'anteprima e per la misura del testo), font, posizione di ogni etichetta |
| `etichetta.html` | il contenuto di UNA etichetta; due impaginazioni (`orizzontale` per 105×74 e 105×42, `compatto` per 70×37 e 70×42) e tre parti (`unica`, `fronte`, `retro`) |
| `stile.css` | misure e colori; è un modello Jinja: le misure dei caratteri dipendono da `scala` (scelta dal motore perché il testo ci stia) e dall'altezza dell'etichetta |

## Dati disponibili nei modelli

- `e`: un'etichetta (dict, vedi `routes/etichette.dati_stampa`): `nome`, `sottotitolo`, `peso`, `peso_sgocciolato` (sottoli e sottaceti, facoltativo),
  `ingredienti_html` (già con `<strong>` sugli allergeni), `tracce`, `conservazione`, `modalita_uso`,
  `dichiarazioni_extra`, `prodotto_da`, `lavorato_da`, `lotto`, `dicitura_scadenza`, `scadenza`, `piede`.
- `formato`: dict del formato (misure in mm, `layout`), `scala`, `parte`.
- `font_url(nome_file)`, `logo_url`: indirizzi `file://` dei font e del logo.

## Creare uno stile nuovo (es. per il 2027)

1. Copiare questa cartella con un nome nuovo, es. `stili/vivace-2027/`, e modificarla. Se i testi usano un
   carattere diverso da Fira Sans, aggiungere `stile.json` con `corpo_pt` e `altezza_x`. `corpo_pt` è il corpo dei
   testi a scala 1, come in `stile.css`; `altezza_x` è l'altezza della x divisa per il corpo (OS/2 sxHeight / unitsPerEm).
   Il motore li usa per controllare il minimo di legge. Esempio: `../classico-giallo/stile.json`. Senza il file
   valgono 6,8 pt e 0,527 (Fira Sans).
2. Provarla dalla pagina **Formati e stili** del modulo (anteprima con dati veri).
3. Sceglierla come stile attivo in **Formati e stili**.

Le etichette già stampate restano archiviate in PDF con lo stile con cui sono nate: cambiare stile non
modifica il passato. **Non modificare uno stile già usato per stampe archiviate**: per cambiarlo, crearne
uno nuovo (così una ristampa di un lotto vecchio esce identica).
