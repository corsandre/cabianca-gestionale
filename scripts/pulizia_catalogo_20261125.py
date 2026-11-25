"""Pulizia del catalogo importato dalle etichette storiche (25/11/2026, richiesta di Andrea: «metti tu durata
dei prodotti e pulisci»). Da lanciare UNA volta, con sqlite3 e senza Flask:

    python3 scripts/pulizia_catalogo_20261125.py data/prodotti.db
    (in Docker: docker compose exec -T web python - /app/data/prodotti.db < scripts/pulizia_catalogo_20261125.py)

Le scelte e da dove vengono:
- DURATA (giorni) e tipo di scadenza ricavati dalle etichette vecchie (data del lotto → data «entro»):
  * marmellate, mostarde, sottaceti, sottoli, sughi, frutta secca, spezie: 365 giorni (12 mesi su tutte le
    etichette recenti). Fanno eccezione la Marmellata di fragole, 180 giorni come sull'etichetta del 2023, e la
    Mostarda di mele, 90 giorni come sull'etichetta del 2025;
  * pasta fresca ripiena congelata: 90 giorni (etichetta del 24/11/2026: lotto 24/11 → 24/02);
  * farine 330 giorni (etichette 2022: circa 11 mesi); grani, semola e pasta di Saragolla 365.
  * NON impostata (si scrive la data nel lotto) dove le etichette non la danno e inventarla sarebbe un rischio:
    salumi (la stabilisce il laboratorio che li lavora), pesto, torta di rose, focaccia.
- CONSERVAZIONE e MODALITÀ D'USO: testi puliti (l'import aveva incollato pezzi del fronte).
  Per la pasta il testo è quello dell'etichetta del 24/11/2026.
- RICETTE della pasta: Tortelli di zucca, Tortelli ricotta e spinaci e Marubini sono riallineati all'elenco
  ingredienti dell'etichetta più recente (24/11/2026), più completo di quello del 2024. Le ricette non sono
  ancora usate in nessun lotto, quindi si possono modificare.
- MATERIE PRIME: nomi di legge (farina di GRANO tenero tipo 00, olio extravergine di oliva, Grana Padano DOP
  con i suoi ingredienti, ricotta vaccina (LATTE), amaretti (contengono UOVA), mostarda (… SENAPE)). Corretti
  due refusi dell'import: «zucchero sale» (sono due ingredienti) e «senape 1334/2007/CE» (è l'essenza di senape).
- FORMATO dell'etichetta dal peso: fino a 100 g Piccolo, fino a 200 g Medio, oltre Grande; salumi Salumi.
- Ogni prodotto resta «da verificare»: lo spegne chi ricontrolla la scheda.
"""
import json
import sqlite3
import sys

CONS_VASETTO = "Conservare in luogo fresco e asciutto, lontano da fonti di calore. Dopo l'apertura conservare in frigorifero."
CONS_SOTTOLIO = ("Conservare in luogo fresco e asciutto, lontano da fonti di calore. Dopo l'apertura conservare in "
                 "frigorifero con il prodotto sempre coperto d'olio.")
CONS_ASCIUTTO = "Conservare in luogo fresco e asciutto."
CONS_PASTA = "Conservare in congelatore a -18 °C. Una volta scongelato non ricongelare."
USO_PASTA = "Cuocere da congelati in acqua bollente salata per circa 5 minuti."
SOTT_PASTA = "Pasta artigianale ripiena all'uovo – prodotto congelato"

# nome (o prefisso con *) → categoria, durata, conservazione, extra
GRUPPI = [
    ("Marmellata*", "Confetture e marmellate", 365, CONS_VASETTO),
    ("Mostarda*", "Mostarde", 365, CONS_VASETTO),
    ("Cetrioli sottaceto", "Sottaceti e agrodolci", 365, CONS_VASETTO),
    ("Cipolle in agrodolce", "Sottaceti e agrodolci", 365, CONS_VASETTO),
    ("Fagiolini agrodolce", "Sottaceti e agrodolci", 365, CONS_VASETTO),
    ("Giardiniera agrodolce", "Sottaceti e agrodolci", 365, CONS_VASETTO),
    ("Peperoni agrodolce", "Sottaceti e agrodolci", 365, CONS_VASETTO),
    ("Giardiniera sottolio", "Conserve e sottoli", 365, CONS_SOTTOLIO),
    ("Melanzane sottolio", "Conserve e sottoli", 365, CONS_SOTTOLIO),
    ("Prugne sciroppate", "Conserve e sottoli", 365, CONS_VASETTO),
    ("Passata*", "Passate e sughi", 365, CONS_VASETTO),
    ("Peperonata", "Passate e sughi", 365, CONS_VASETTO),
    ("Ragu di Salsiccia", "Passate e sughi", 365, CONS_VASETTO),
    ("Salsa Magnabufèt", "Passate e sughi", 365, CONS_VASETTO),
    ("Pesto", "Passate e sughi", None, None),          # dipende da come è fatto (pastorizzato o no): lo scrive Andrea
    ("Sacchettini*", "Frutta secca e spezie", 365, CONS_ASCIUTTO),
    ("Farina*", "Farine", 330, CONS_ASCIUTTO),
    ("Saragolla", "Farine", 365, CONS_ASCIUTTO),
    ("Semola di Saragolla", "Farine", 365, CONS_ASCIUTTO),
    ("Pasta di Saragolla", "Altro", 365, CONS_ASCIUTTO),
    ("Marubini di carne", "Pasta fresca ripiena", 90, CONS_PASTA),
    ("Tortelli*", "Pasta fresca ripiena", 90, CONS_PASTA),
    ("Torta di rose", "Prodotti da forno", None, None),
    ("Focaccia", "Prodotti da forno", None, None),
    ("Cacciatorino", "Salumi", None, None), ("Cotechino", "Salumi", None, None), ("Pancetta", "Salumi", None, None),
    ("Salame da pentola", "Salumi", None, None), ("Salamelle", "Salumi", None, None),
    ("Salami", "Salumi", None, CONS_ASCIUTTO), ("Stronchino", "Salumi", None, None),
]
DURATE_SPECIALI = {("Marmellata di Fragole", 250.0): 180, ("Mostarda di mele", 150.0): 90}

LAVORATO_DA = {
    "CEE IT H5A03.": "stabilimento CE IT H5A03",
    "Rizzi Giancarlo Paderno Ponchielli (CR).": "Rizzi Giancarlo – Paderno Ponchielli (CR)",
    "Mais Corvino SrL Via Castello, 1, 26020 Formigara CR.": "Mais Corvino S.r.l. – Via Castello 1, 26020 Formigara (CR)",
    "Az. Agr. Il Campagnino 500g.": "Az. Agr. Il Campagnino",
    "Az. Agr. Il Campagnino.": "Az. Agr. Il Campagnino",
    "La Grande Ruota S.r.l.": "La Grande Ruota S.r.l.",
}

# materie prime: nome → (nome_etichetta, allergeni, composta). Le nuove vengono create.
MATERIE = {
    "Farina 00": ("farina di GRANO tenero tipo 00", ["glutine"], None),
    "Olio evo": ("olio extravergine di oliva", [], None),
    "Grana Padano": ("Grana Padano DOP", ["latte", "uova"], "LATTE, sale, caglio, conservante: lisozima da UOVO"),
    "Ricotta": ("ricotta vaccina", ["latte"], "LATTE"),
    "Amaretto": ("amaretti", ["uova"], "contengono UOVA"),
    "Mostarda": ("mostarda", ["senape"], "frutta, zucchero, essenza di SENAPE"),
    "Semola di grano duro": ("semola di GRANO duro", ["glutine"], None),
    "Carne di bovino": ("carne di bovino", [], None),
    "Mortadella": ("mortadella", ["frutta_guscio"], "con PISTACCHI"),
    "Noce moscata": ("noce moscata", [], None),
}

# ricette della pasta dall'etichetta del 24/11/2026 (nomi delle materie prime, in ordine)
RICETTE_PASTA = {
    "Tortelli di zucca alla mantovana": (
        ["Farina 00", "Semola di grano duro", "Zucca", "Mostarda", "Grana Padano", "Amaretto", "Uova", "Sale",
         "Pepe", "Olio evo"], "FRUTTA A GUSCIO"),
    "Tortelli ricotta e spinaci": (
        ["Farina 00", "Semola di grano duro", "Ricotta", "Spinaci", "Grana Padano", "Uova", "Sale", "Pepe",
         "Noce moscata", "Olio evo"], None),
    "Marubini di carne": (
        ["Farina 00", "Semola di grano duro", "Carne di bovino", "Carne di suino", "Mortadella", "Grana Padano",
         "Uova", "Sale", "Pepe", "Noce moscata", "Olio evo", "Cipolla", "Carota", "Vino bianco", "Pomodoro",
         "Aromi naturali"], None),
}
FONTE_PASTA = "Etichette pasta artigianale - lotti 241126_v2.pdf (24/11/2026)"


def materia(con, nome):
    r = con.execute("SELECT id FROM materie_prime WHERE lower(nome)=lower(?)", (nome,)).fetchone()
    if not r:
        raise SystemExit(f"Materia prima non trovata: {nome}")
    return r[0]


def sostituisci_materia(con, prodotto, vecchia, nuove):
    """Nella ricetta v1 (non usata) del prodotto, la riga con la materia `vecchia` diventa le righe `nuove`."""
    rid = con.execute("SELECT ricetta_default_id FROM prodotti WHERE id=?", (prodotto,)).fetchone()[0]
    righe = [r[0] for r in con.execute("SELECT materia_prima_id FROM ricette_righe WHERE ricetta_id=? ORDER BY ordine", (rid,))]
    if vecchia not in righe:
        return
    i = righe.index(vecchia)
    righe[i:i + 1] = nuove
    riscrivi_righe(con, rid, righe)


def riscrivi_righe(con, rid, materie_ids):
    con.execute("DELETE FROM ricette_righe WHERE ricetta_id=?", (rid,))
    for i, mid in enumerate(materie_ids):
        unita = con.execute("SELECT unita FROM materie_prime WHERE id=?", (mid,)).fetchone()[0] or "g"
        con.execute("INSERT INTO ricette_righe (ricetta_id, materia_prima_id, quantita, unita, ordine) VALUES (?,?,0,?,?)",
                    (rid, mid, unita, i))


def main(percorso):
    con = sqlite3.connect(percorso)
    con.execute("PRAGMA busy_timeout=10000")
    con.execute("BEGIN IMMEDIATE")
    if con.execute("SELECT count(*) FROM lotti").fetchone()[0]:
        raise SystemExit("Ci sono già dei lotti: questa pulizia va fatta solo sul catalogo appena importato.")

    # --- materie prime
    for nome, (etichetta, allergeni, composta) in MATERIE.items():
        r = con.execute("SELECT id FROM materie_prime WHERE lower(nome)=lower(?)", (nome,)).fetchone()
        if r:
            con.execute("UPDATE materie_prime SET nome_etichetta=?, allergeni=?, composta=? WHERE id=?",
                        (etichetta, json.dumps(allergeni), composta, r[0]))
        else:
            con.execute("INSERT INTO materie_prime (nome, nome_etichetta, allergeni, composta, note) VALUES (?,?,?,?,?)",
                        (nome, etichetta, json.dumps(allergeni), composta, f"Dall'etichetta {FONTE_PASTA}"))
    # refusi dell'import
    for (pid,) in con.execute("SELECT id FROM prodotti WHERE nome='Fagiolini agrodolce'").fetchall():
        sostituisci_materia(con, pid, materia(con, "Zucchero sale"), [materia(con, "Zucchero"), materia(con, "Sale")])
    for (pid,) in con.execute("SELECT id FROM prodotti WHERE nome IN ('Mostarda di pere', 'Mostarda di zucca')").fetchall():
        sostituisci_materia(con, pid, materia(con, "Senape 1334/2007/CE"), [materia(con, "Essenza di senape")])
    con.execute("UPDATE materie_prime SET attiva=0, note='Refuso dell''import (25/11/2026): non usare' "
                "WHERE nome IN ('Zucchero sale', 'Senape 1334/2007/CE')")

    # --- ricette della pasta
    for nome, (materie, tracce) in RICETTE_PASTA.items():
        pid, rid = con.execute("SELECT id, ricetta_default_id FROM prodotti WHERE nome=?", (nome,)).fetchone()
        riscrivi_righe(con, rid, [materia(con, m) for m in materie])
        con.execute("UPDATE ricette SET procedimento=? WHERE id=?",
                    (f"Ingredienti dall'etichetta {FONTE_PASTA}. Inserire quantità, resa e procedimento.", rid))
        con.execute("UPDATE prodotti SET tracce=? WHERE id=?", (tracce, pid))

    # --- prodotti
    con.execute("UPDATE prodotti SET nome='Torta di rose' WHERE nome='Etichette torte'")
    con.execute("UPDATE prodotti SET unita='g' WHERE nome IN ('Marmellata di Fragole', 'Pesto')")
    formati = dict(con.execute("SELECT nome, id FROM formati_etichetta WHERE attivo"))
    for pid, nome, peso in con.execute("SELECT id, nome, peso_netto FROM prodotti").fetchall():
        gruppo = next((g for g in GRUPPI if (nome == g[0] or (g[0].endswith("*") and nome.startswith(g[0][:-1])))), None)
        if not gruppo:
            print("  senza gruppo:", nome)
            continue
        _, categoria, durata, cons = gruppo
        durata = DURATE_SPECIALI.get((nome, peso), durata)
        if categoria == "Salumi":
            formato = formati.get("Salumi")
        elif peso:
            formato = formati.get("Piccolo") if peso <= 100 else formati.get("Medio") if peso <= 200 else formati.get("Grande")
        else:
            formato = None
        con.execute("UPDATE prodotti SET categoria=?, durata_giorni=?, tipo_scadenza='tmc', conservazione=?, "
                    "formato_etichetta_id=coalesce(?, formato_etichetta_id), "
                    "modificato_il=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?",
                    (categoria, durata, cons, formato, pid))
        if categoria == "Pasta fresca ripiena":
            con.execute("UPDATE prodotti SET sottotitolo=?, modalita_uso=?, lavorato_da=NULL WHERE id=?",
                        (SOTT_PASTA, USO_PASTA, pid))
    for vecchio, nuovo in LAVORATO_DA.items():
        con.execute("UPDATE prodotti SET lavorato_da=? WHERE lavorato_da=?", (nuovo, vecchio))
    con.execute("UPDATE prodotti SET dichiarazioni_extra='Budello non edibile.' WHERE nome='Salami'")
    con.execute("UPDATE prodotti SET tracce='aglio' WHERE nome='Salami'")
    con.commit()
    print("Pulizia fatta:",
          con.execute("SELECT count(*) FROM prodotti WHERE durata_giorni>0").fetchone()[0], "prodotti con durata,",
          con.execute("SELECT count(*) FROM prodotti WHERE formato_etichetta_id IS NOT NULL").fetchone()[0], "con formato.")
    print("Senza durata (data da scrivere nel lotto):",
          [r[0] for r in con.execute("SELECT nome FROM prodotti WHERE durata_giorni IS NULL ORDER BY nome")])
    con.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1])
