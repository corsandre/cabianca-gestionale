# Stile etichette «classico-giallo»

Ricrea le etichette storiche di Fattoria Ca' Bianca, fatte in Illustrator fino al 2026 (cartelle in
`~/Desktop/etichette/Etichette prodotti`). Richiesto da Andrea il 25/11/2026.

- **Colori**, misurati sui PDF originali:
  - sfondo crema `#fdf0c5`;
  - bordeaux `#a32658` per i nomi, l'elenco ingredienti e le voci;
  - verde `#33ab60` per «Ingredienti:» e il peso;
  - verde scuro `#307e3b` per i valori e gli allergeni.
- **Caratteri**:
  - Yeseva One per nomi e testi, come negli originali;
  - lotto e data in Fira Sans, perché gli originali usavano Myriad Pro, che non è un carattere libero.
- **Impaginazione**: come le etichette storiche.
  - Logo e nome a sinistra, testi a destra.
  - In fondo, lotto e scadenza a sinistra e il peso grande in verde a destra.
  - Con fronte e retro, il fronte ha logo grande, nome, peso e sito.
- **Allergeni**: in verde scuro e in maiuscolo, quindi diversi dal resto dell'elenco come chiede il
  Reg. UE 1169/2011. Le etichette storiche invece non li evidenziavano.

## Minimo di legge

Yeseva One ha la «x» alta il 50% del corpo, quindi l'altezza minima di 1,2 mm corrisponde a **6,8 pt**. Lo dichiara
`stile.json` (`altezza_x: 0.5`, `corpo_pt: 7.0`), che il motore usa per gli avvisi. Yeseva One è un carattere largo:
sul formato Piccolo (63,5×38,1) il testo ci sta a norma solo con **fronte e retro**, che è la modalità proposta di
default per quel formato.

## Stampa

Lo sfondo crema arriva fino al bordo dell'etichetta e consuma toner: per le prove si può usare lo stile
`base-2026`, che ha lo sfondo bianco. Se la stampante sposta un po' la stampa, sul bordo dell'etichetta resta un filo
bianco: si corregge con lo spostamento X/Y del formato (foglio di calibrazione).

Prova di tutti i formati:

```
RUOLO=sviluppo PYTHONPATH=. .venv/bin/python scripts/prova_stile_etichette.py <cartella> classico-giallo
```

Non modificare questo stile dopo averlo usato per delle stampe archiviate. Per cambiarlo se ne crea uno nuovo
(vedi `../base-2026/LEGGIMI.md`).
