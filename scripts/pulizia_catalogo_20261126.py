"""Pulizia del catalogo del 26/11/2026 (richiesta di Andrea) per la prodotti 2.0.0 (contenitori). Da lanciare
UNA volta, DOPO il deploy della 2.0.0 (servono le migrazioni 5 e 6), con sqlite3 e senza Flask:

    python3 scripts/pulizia_catalogo_20261126.py data/prodotti.db           # cosa farebbe, senza scrivere
    python3 scripts/pulizia_catalogo_20261126.py data/prodotti.db --fai     # lo fa
    (in Docker: docker compose exec -T web python - /app/data/prodotti.db --fai < scripts/pulizia_catalogo_20261126.py)

Cosa fa:
1. elimina i due lotti di prova (L251126-TRI, L251126-CAC), con ingredienti, confezioni, stampe e PDF. Lo
   storico ne conserva la copia;
2. «Marmellata» → «Confettura»: per legge la marmellata è solo di agrumi (dir. 2001/113/CE, D.Lgs. 50/2004).
   Il nome «Marmellata di X» diventa «Confettura di X» e la categoria «Confetture e marmellate» diventa «Confetture»;
3. il prodotto diventa GENERICO: un solo prodotto per nome (es. «Confettura di fichi»), con i contenitori
   nella ricetta. Contenitore dal peso e dalla categoria del prodotto importato:
   - confetture e mostarde: solo vasetto da 150 g o 300 g; gli altri formati non si fanno più;
   - conserve, sottaceti e sughi: 150 g e 300 g, 250 g → vasetto da 300 g, passata → bottiglia da 750 g,
     pesto → vasetto da 100 g;
   - pasta, farine, sacchettini, salumi e forno: busta, sacchetto, sacchettino, salume, pezzo da forno.
   I doppioni (stesso nome e categoria) si UNISCONO nel primo che ha un contenitore. La ricetta di un doppione
   di un formato che si fa ancora, se ha ingredienti diversi, diventa una versione in più del prodotto rimasto
   (nome «dall'etichetta da N g»); le altre si scartano. I prodotti rimasti senza contenitore si eliminano: le confetture che c'erano solo
   da 100/250 g e la mostarda di zucca cedrina senza peso;
4. sigle nuove per le confetture (CFI, CAL…), visto che non hanno lotti;
5. peso e formato del prodotto, colonne della 1.x non più usate, si svuotano.
Prima di scrivere fa una copia in backups/prodotti_pre_pulizia_20261126.db.
"""
import os
import re
import sqlite3
import sys

LOTTI_DI_PROVA = ("L251126-TRI", "L251126-CAC")
CHI = "Pulizia catalogo 26/11/2026"


def contenitore_per(nome, peso, categoria):
    """Nome del contenitore (migrazione 6) per un prodotto importato dalla 1.x, o None se quel formato non si fa più."""
    peso = peso or 0
    if categoria in ("Confetture e marmellate", "Confetture", "Mostarde"):
        return {150: "Vasetto 150 g", 300: "Vasetto 300 g"}.get(peso)
    if categoria in ("Conserve e sottoli", "Sottaceti e agrodolci", "Passate e sughi"):
        if nome == "Pesto":
            return "Vasetto pesto 100 g"
        if nome.startswith("Passata") and peso == 750:
            return "Bottiglia passata 750 g"
        return {150: "Vasetto 150 g", 250: "Vasetto 300 g", 300: "Vasetto 300 g"}.get(peso)
    if categoria == "Pasta fresca ripiena" or (categoria == "Altro" and nome.startswith("Pasta")):
        return {250: "Busta pasta 250 g", 500: "Busta pasta 500 g"}.get(peso)
    if categoria == "Farine":
        return "Sacchetto farina 500 g" if peso == 500 else None
    if categoria == "Frutta secca e spezie":
        return f"Sacchettino {peso:g} g" if peso else None
    if categoria == "Salumi":
        return "Salume (peso variabile)"
    if categoria == "Prodotti da forno":
        return "Pezzo da forno (peso variabile)"
    return None


def proponi_sigla(nome):
    """Come app/moduli/prodotti/services/lotti.proponi_sigla."""
    vuote = {"di", "del", "della", "delle", "dei", "e", "al", "alla", "allo", "con", "in", "da", "a", "il", "la"}
    parole = [p for p in re.findall(r"[A-Za-zÀ-ÿ]+", nome or "") if p.lower() not in vuote]
    if not parole:
        return ""
    s = parole[0][:3] if len(parole) == 1 else parole[0][0] + parole[1][:2]
    return re.sub(r"[^A-Z0-9]", "", s.upper())[:8]


def elimina_lotto(con, codice, cartella_pdf):
    r = con.execute("SELECT id FROM lotti WHERE codice=?", (codice,)).fetchone()
    if not r:
        print(f"  lotto {codice}: non c'è (già eliminato?)")
        return []
    lid = r[0]
    pdf = [p for (p,) in con.execute("SELECT pdf_path FROM stampe_etichette WHERE lotto_id=?", (lid,))]
    print(f"  elimino il lotto {codice} con {len(pdf)} stampe")
    con.execute("UPDATE lotti SET stato='annullato', stato_motivo='ELIMINATO: lotto di prova (Andrea, 26/11/2026)', "
                "modificato_da=?, modificato_il=strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), "
                "cancellazione_autorizzata=1 WHERE id=?", (CHI, lid))
    con.execute("DELETE FROM stampe_etichette WHERE lotto_id=?", (lid,))
    for tabella in ("lotti_ingredienti", "lotti_confezioni"):
        con.execute(f"UPDATE {tabella} SET modificato_da=? WHERE lotto_id=?", (CHI, lid))
        con.execute(f"DELETE FROM {tabella} WHERE lotto_id=?", (lid,))
    con.execute("DELETE FROM lotti WHERE id=?", (lid,))
    return [os.path.join(cartella_pdf, p) for p in pdf]


def elimina_prodotto(con, pid):
    if con.execute("SELECT count(*) FROM lotti WHERE prodotto_id=?", (pid,)).fetchone()[0]:
        raise SystemExit(f"Il prodotto {pid} ha dei lotti: non lo elimino. Niente è stato scritto.")
    ricette = "SELECT id FROM ricette WHERE prodotto_id=?"
    con.execute(f"DELETE FROM ricette_contenitori WHERE ricetta_id IN ({ricette})", (pid,))
    con.execute(f"DELETE FROM ricette_righe WHERE ricetta_id IN ({ricette})", (pid,))
    con.execute("DELETE FROM ricette WHERE prodotto_id=?", (pid,))
    con.execute("DELETE FROM prodotti WHERE id=?", (pid,))


def materie(con, ricetta_id):
    return [m for (m,) in con.execute("SELECT materia_prima_id FROM ricette_righe WHERE ricetta_id=? ORDER BY ordine, id",
                                      (ricetta_id,))]


def unisci(con, principale, doppione, peso, tieni_ricette):
    """Sposta nel prodotto principale le ricette (se diverse, e solo di un formato che si fa ancora) e i lotti
    del doppione, poi lo elimina."""
    rif = [materie(con, r) for (r,) in con.execute("SELECT id FROM ricette WHERE prodotto_id=?", (principale,))]
    for rid, in con.execute("SELECT id FROM ricette WHERE prodotto_id=? ORDER BY versione", (doppione,)).fetchall():
        if not tieni_ricette:
            continue
        if materie(con, rid) in rif:
            continue                                   # stessi ingredienti: è la stessa ricetta
        versione = con.execute("SELECT coalesce(max(versione), 0) + 1 FROM ricette WHERE prodotto_id=?",
                               (principale,)).fetchone()[0]
        con.execute("UPDATE ricette SET prodotto_id=?, versione=?, nome=? WHERE id=?",
                    (principale, versione, f"dall'etichetta da {peso:g} g" if peso else "dall'etichetta", rid))
        rif.append(materie(con, rid))
        print(f"      la ricetta del doppione ha ingredienti diversi: diventa la v{versione}")
    con.execute("UPDATE lotti SET prodotto_id=?, modificato_da=? WHERE prodotto_id=?", (principale, CHI, doppione))
    elimina_prodotto(con, doppione)


def main(percorso, fai):
    con = sqlite3.connect(percorso, isolation_level=None)
    con.execute("PRAGMA busy_timeout=30000")
    if not con.execute("SELECT name FROM sqlite_master WHERE name='lotti_confezioni'").fetchone():
        raise SystemExit("Mancano le migrazioni 5 e 6: fare prima il deploy della prodotti 2.0.0.")
    contenitori = dict(con.execute("SELECT nome, id FROM contenitori"))
    ordine = dict(con.execute("SELECT nome, ordine FROM contenitori"))
    if fai:
        cartella_bk = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(percorso))), "backups")
        os.makedirs(cartella_bk, exist_ok=True)
        copia = os.path.join(cartella_bk, "prodotti_pre_pulizia_20261126.db")
        bk = sqlite3.connect(copia)
        con.backup(bk)
        bk.close()
        print("Copia di sicurezza:", copia)
    print("Modo:", "SCRIVO" if fai else "PROVA (niente viene scritto; aggiungere --fai)")
    da_togliere = []
    con.execute("BEGIN IMMEDIATE")
    try:
        # 1. lotti di prova
        print("1. Lotti di prova")
        cartella_pdf = os.path.join(os.path.dirname(os.path.abspath(percorso)), "prodotti", "etichette")
        for codice in LOTTI_DI_PROVA:
            da_togliere += elimina_lotto(con, codice, cartella_pdf)

        # 2. Marmellata → Confettura
        con.execute("UPDATE prodotti SET categoria='Confetture' WHERE categoria='Confetture e marmellate'")
        for pid, nome in con.execute("SELECT id, nome FROM prodotti WHERE nome LIKE 'Marmellata%'").fetchall():
            nuovo = re.sub(r"^Marmellata\b", "Confettura", nome)
            con.execute("UPDATE prodotti SET nome=? WHERE id=?", (nuovo, pid))

        # 3. un prodotto per nome, con i contenitori nella ricetta
        print("2. Prodotti generici e contenitori")
        gruppi = {}
        for pid, nome, peso, cat in con.execute("SELECT id, nome, peso_netto, categoria FROM prodotti "
                                                "ORDER BY categoria, nome, id").fetchall():
            cont = contenitore_per(nome, peso, cat)
            if cont and cont not in contenitori:
                raise SystemExit(f"Contenitore «{cont}» mancante (migrazione 6?). Niente è stato scritto.")
            gruppi.setdefault((nome.strip().lower(), cat), []).append((pid, nome, peso, cont))
        for (_, cat), membri in gruppi.items():
            con_cont = [m for m in membri if m[3]]
            if not con_cont:
                for pid, nome, peso, _ in membri:
                    print(f"  elimino {nome} {f'{peso:g} g' if peso else 'senza peso'} ({cat}): quel formato non si fa più")
                    elimina_prodotto(con, pid)
                continue
            principale = con_cont[0]
            nomi_cont = sorted(set(m[3] for m in con_cont), key=lambda n: (ordine[n], n))
            altri = [m for m in membri if m[0] != principale[0]]
            pesi = ", ".join(f"{m[2]:g} g" if m[2] else "senza peso" for m in membri)
            print(f"  {principale[1]} → {', '.join(nomi_cont)}" + (f"   (uniti: {pesi})" if altri else ""))
            for pid, nome, peso, cont in altri:
                unisci(con, principale[0], pid, peso, tieni_ricette=bool(cont))
            for (rid,) in con.execute("SELECT id FROM ricette WHERE prodotto_id=?", (principale[0],)).fetchall():
                for n in nomi_cont:
                    con.execute("INSERT OR IGNORE INTO ricette_contenitori (ricetta_id, contenitore_id) VALUES (?, ?)",
                                (rid, contenitori[n]))

        # 4. sigle nuove per le confetture
        print("3. Sigle delle confetture")
        usate = {s for (s,) in con.execute("SELECT sigla FROM prodotti WHERE categoria != 'Confetture'")}
        for pid, nome in con.execute("SELECT id, nome FROM prodotti WHERE categoria='Confetture' ORDER BY nome, id").fetchall():
            base = proponi_sigla(nome)
            sigla, n = base, 2
            while sigla in usate:
                sigla, n = f"{base}{n}", n + 1
            usate.add(sigla)
            print(f"  {nome}: {sigla}")
            con.execute("UPDATE prodotti SET sigla=? WHERE id=?", (sigla, pid))

        # 5. colonne della 1.x
        con.execute("UPDATE prodotti SET peso_netto=NULL, formato_etichetta_id=NULL, "
                    "modificato_il=strftime('%Y-%m-%dT%H:%M:%S','now','localtime')")
        con.execute("COMMIT" if fai else "ROLLBACK")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    if fai:
        for f in da_togliere:
            try:
                os.remove(f)
            except OSError:
                pass
    print("Prodotti nel catalogo:", con.execute("SELECT count(*) FROM prodotti").fetchone()[0],
          "| ricette:", con.execute("SELECT count(*) FROM ricette").fetchone()[0],
          "| lotti:", con.execute("SELECT count(*) FROM lotti").fetchone()[0])
    con.close()


if __name__ == "__main__":
    argomenti = [a for a in sys.argv[1:] if a != "--fai"]
    if len(argomenti) != 1:
        print(__doc__)
        sys.exit(2)
    main(argomenti[0], "--fai" in sys.argv)
