#!/usr/bin/env python3
"""
Importa 22 bolle storiche di consegne mangime (30/09/2025 – 24/02/2026).
Eseguire sul host: python3 /home/andrea/cabianca-gestionale/insert_consegne.py
"""
import sqlite3
from datetime import date

DB_PATH = "/app/data/gestionale.db"

CONSEGNE = [
    # (data, bolla, tipo_prodotto, descrizione, quantita_q)
    ("2025-09-30", "020582/C01", "LC 45",     "SUINI LC 45 SBR.RINF.",  98.60),
    ("2025-10-10", "000863/C01", "LC 45",     "SUINI LC 45 SBR.RINF.", 100.00),
    ("2025-10-16", "001308/C01", "LC 45",     "SUINI LC 45 SBR.RINF.", 138.20),
    ("2025-10-21", "001626/C01", "LC 45",     "SUINI LC 45 SBR.RINF.", 140.40),
    ("2025-10-27", "002131/C01", "LC 45",     "SUINI LC 45 SBR.RINF.", 163.60),
    ("2025-11-01", "002640/C01", "LC 45",     "SUINI LC 45 SBR.RINF.", 137.60),
    ("2025-11-06", "003010/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 198.60),
    ("2025-11-13", "003598/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 199.20),
    ("2025-11-20", "004187/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 192.20),
    ("2025-11-27", "004748/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 240.20),
    ("2025-12-04", "005292/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 249.00),
    ("2025-12-12", "005969/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 281.00),
    ("2025-12-19", "006519/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 286.60),
    ("2025-12-31", "007385/C01", "LC 80",     "SUINI LC 80 SBR.RINF.", 288.40),
    ("2026-01-09", "000315/P01", "LC 120",    "SUINI LC 120 SBR.RINF.", 284.00),
    ("2026-01-17", "001376/C01", "LC 120",    "SUINI LC 120 SBR.RINF.", 285.80),
    ("2026-01-24", "001905/C01", "LC 120",    "SUINI LC 120 SBR.RINF.",  49.20),
    ("2026-01-24", "001953/C01", "LC 120",    "SUINI LC 120 SBR.RINF.", 232.40),
    ("2026-01-30", "002382/C01", "LC 120",    "SUINI LC 120 SBR.RINF.", 283.60),
    ("2026-02-06", "002968/C01", "LC 120",    "SUINI LC 120 SBR.RINF.", 280.60),
    ("2026-02-17", "003795/C01", "SP 140/AO", "SUINI SP 140/A0 SBR.RINF.", 285.00),  # ⚠️ usa q.ordinata
    ("2026-02-24", "004330/C01", "SP 140/AO", "SUINI SP 140/A0 SBR.RINF.", 284.00),
]

TOTALE_Q = sum(r[4] for r in CONSEGNE)  # 4698.20


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Assicura che la colonna tipo_prodotto esista
    try:
        cur.execute("ALTER TABLE consegne_alimentari ADD COLUMN tipo_prodotto TEXT")
        con.commit()
        print("Colonna tipo_prodotto aggiunta.")
    except sqlite3.OperationalError:
        print("Colonna tipo_prodotto già presente.")

    # Verifica se ci sono già consegne (evita doppio import)
    cur.execute("SELECT COUNT(*) FROM consegne_alimentari WHERE tipo='mangime'")
    n_existing = cur.fetchone()[0]
    if n_existing > 0:
        print(f"Attenzione: ci sono già {n_existing} consegne mangime nel DB.")
        risposta = input("Continuare comunque? (s/N) ").strip().lower()
        if risposta != "s":
            print("Importazione annullata.")
            con.close()
            return

    # Inserisci le consegne
    inserted = 0
    for data_str, bolla, tipo_prodotto, desc, quantita_q in CONSEGNE:
        nota_extra = " ⚠️ qtà ordinata (ricevuta non confermata)" if bolla == "003795/C01" else ""
        note = f"Bolla {bolla} | {desc}{nota_extra}"
        cur.execute(
            """INSERT INTO consegne_alimentari
               (tipo, data, quantita_q, fornitore, tipo_prodotto, note, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            ("mangime", data_str, quantita_q, "Cons.Agr. Ca' Bianca", tipo_prodotto, note, 1),
        )
        inserted += 1
        print(f"  {data_str}  {bolla:15s}  {tipo_prodotto:10s}  {quantita_q:7.2f} q")

    # Aggiorna giacenza magazzino mangime
    cur.execute(
        "UPDATE magazzino_prodotti SET quantita_attuale_q = ? WHERE tipo = 'mangime'",
        (TOTALE_Q,),
    )
    rows_updated = cur.rowcount
    if rows_updated == 0:
        print("ATTENZIONE: nessun record 'mangime' aggiornato in magazzino_prodotti!")
    else:
        print(f"\nGiacenza mangime aggiornata a {TOTALE_Q} q.")

    con.commit()
    con.close()

    print(f"\n✓ Importate {inserted} consegne. Totale: {TOTALE_Q:.2f} q")


if __name__ == "__main__":
    main()
