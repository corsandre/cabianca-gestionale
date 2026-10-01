"""Costruisce il campionario dei caratteri e delle frasi dello schermo di EM2000
(app/services/impianto/em2000/campionario.json) da schermate di cui si conosce il contenuto.

Uso:  python scripts/em2000_addestra.py <cartella con le schermate PNG>

Le schermate e i testi qui sotto vengono dal pasto delle 07:00 del 01/10/2026 (valori verificati a
occhio). Per insegnare un nuovo stato o un nuovo carattere: aggiungere la schermata con il suo testo
e rilanciare. Lo script si ferma se un testo non si allinea ai caratteri trovati, così un campionario
sbagliato non viene mai salvato.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from PIL import Image  # noqa: E402

from app.services.impianto.em2000 import schermo as S  # noqa: E402

# schermata: {zona: testo}. Zone tabella: (componente, colonna); stato1/stato2 sono frasi intere.
NOTE = {
    "f-065809.png": {"ora_pc": "06.53.53", "pasto_attuale": "18:00", "prossimo_pasto": "07:00", "linea": "L3 G1",
                     "stato1": "ATTESA ORARIO", "stato2": "ATTESA",
                     ("acqua", "teorico"): "4,58 Qli", ("acqua", "reale"): "4,72 Qli",
                     ("siero", "teorico"): "16,66 Qli", ("siero", "reale"): "16,65 Qli",
                     ("farina", "teorico"): "5,00 Qli", ("farina", "reale"): "4,99 Qli",
                     ("totale", "teorico"): "26,23 Qli", ("totale", "reale"): "26,36 Qli"},
    "f-070437.png": {"stato1": "CICLO AUTOMATICO", "stato2": "ATTESA INIZIO CICLO"},
    "f-070518.png": {"stato1": "CICLO AUTOMATICO", "stato2": "PREPARAZIONE RICETTA"},
    "f-070559.png": {"stato1": "CICLO AUTOMATICO", "stato2": "STABILIZZAZIONE"},
    "f-071024.png": {"stato1": "CICLO AUTOMATICO", "stato2": "MISCELAZIONE"},
    "f-071616.png": {"stato1": "CICLO AUTOMATICO", "stato2": "RIEMPIMENTO TUBO"},
    "f-071717.png": {"stato1": "CICLO AUTOMATICO", "stato2": "DISTRIBUZIONE BOX NR. 1"},
    "f-072033.png": {"stato1": "CICLO AUTOMATICO", "stato2": "DOSAGGIO ACQUA LAVAGGIO"},
    "f-072417.png": {"stato1": "CICLO AUTOMATICO", "stato2": "ATTESA SVUOTAMENTO"},
    "f-072336.png": {"stato1": "CICLO AUTOMATICO", "stato2": "LAVAGGIO BOX NR. 7"},
    "f-074036.png": {"ora_pc": "07.36.20", "stato1": "CICLO AUTOMATICO", "stato2": "STABILIZZAZIONE ACQUA LAVAGGIO"},
    "f-074138.png": {"stato1": "CICLO AUTOMATICO", "stato2": "SVUOTA BILANCIA"},
    "f-073915.png": {"stato1": "CICLO AUTOMATICO", "stato2": "ATTESA VASCA VUOTA"},
    "f-070821.png": {"ora_pc": "07.04.05"},
    # schermata dal vivo del pasto delle 12:50 (dosaggio in corso: farina ancora in kg)
    "live-131233.png": {"ora_pc": "13.12.33", "pasto_attuale": "12:50", "prossimo_pasto": "18:00", "linea": "L2 G1",
                        ("farina", "reale"): "0 Kg", ("siero", "reale"): "11,68 Qli"},
    "f-080308.png": {"ora_pc": "07.58.52"},
    "f-071555.png": {"pasto_attuale": "07:00", "linea": "L1 G1",
                     ("acqua", "teorico"): "4,27 Qli", ("acqua", "reale"): "4,35 Qli",
                     ("siero", "teorico"): "15,53 Qli", ("siero", "reale"): "15,53 Qli",
                     ("farina", "teorico"): "4,66 Qli", ("farina", "reale"): "4,65 Qli",
                     ("totale", "teorico"): "24,47 Qli", ("totale", "reale"): "24,52 Qli"},
    "f-072235.png": {"ora_pc": "07.18.19", "prossimo_pasto": "14:39"},
    "f-073247.png": {"ora_pc": "07.28.31", "prossimo_pasto": "14:39", "linea": "L2 G1",
                     ("acqua", "teorico"): "4,01 Qli", ("acqua", "reale"): "4,07 Qli",
                     ("siero", "teorico"): "14,57 Qli", ("siero", "reale"): "14,55 Qli",
                     ("farina", "teorico"): "4,37 Qli", ("farina", "reale"): "4,36 Qli",
                     ("totale", "teorico"): "22,94 Qli", ("totale", "reale"): "22,98 Qli"},
    "f-074932.png": {"linea": "L3 G1",
                     ("acqua", "teorico"): "4,59 Qli", ("acqua", "reale"): "4,76 Qli",
                     ("siero", "teorico"): "16,70 Qli", ("siero", "reale"): "16,67 Qli",
                     ("farina", "teorico"): "5,01 Qli", ("farina", "reale"): "5,00 Qli",
                     ("totale", "teorico"): "26,30 Qli", ("totale", "reale"): "26,42 Qli"},
}


def zona(img, nome):
    if isinstance(nome, tuple):
        comp, col = nome
        (x0, x1), (y0, y1) = S.COLONNE[col], S.RIGHE[comp]
        return img.crop((x0, y0, x1, y1))
    return img.crop(S.ZONE[nome])


def main(cartella):
    camp = S.Campionario()
    camp.caratteri, camp.frasi = {}, {}
    errori = []
    for nome_file, testi in NOTE.items():
        img = Image.open(os.path.join(cartella, nome_file)).convert("RGB")
        for z, testo in testi.items():
            if z in ("stato1", "stato2"):
                prefisso = next((p for p in S.PREFISSI_BOX if testo.startswith(p)), None)
                if prefisso:
                    # solo i glifi del prefisso (tutti tranne le cifre finali): il numero del box cambia.
                    # Non si contano le lettere perché nel grassetto alcune si toccano ("LA").
                    gs = S.glifi(zona(img, z))
                    cifre = len(testo[len(prefisso):].strip())
                    camp.frasi["/".join(S.chiave(g) for _, g in gs[:-cifre])] = prefisso
                else:
                    camp.impara_frase(zona(img, z), testo)
            elif not camp.impara_testo(zona(img, z), testo):
                errori.append(f"{nome_file} {z}: '{testo}' non si allinea")
    # le cifre del numero box dopo "NR." si imparano dalla schermata del box 14
    img = Image.open(os.path.join(cartella, "f-072235.png")).convert("RGB")
    gs = S.glifi(zona(img, "stato2"))
    for (_, g), c in zip(gs[-2:], "14"):
        camp.caratteri.setdefault(S.chiave(g), c)
    if errori:
        sys.exit("Campionario NON salvato:\n  " + "\n  ".join(errori))
    camp.salva()
    print(f"campionario salvato: {len(camp.caratteri)} caratteri, {len(camp.frasi)} frasi → {camp.percorso}")


if __name__ == "__main__":
    main(sys.argv[1])
