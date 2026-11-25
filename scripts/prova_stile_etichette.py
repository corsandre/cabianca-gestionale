"""Prova di uno stile delle etichette con testi veri di Fattoria Ca' Bianca, un foglio per formato.

Uso (in locale, con un database qualsiasi: servono solo i formati del modulo):
    RUOLO=sviluppo PYTHONPATH=. .venv/bin/python scripts/prova_stile_etichette.py <cartella_uscita> [stile]
Scrive un PDF per formato con il contorno tratteggiato delle etichette e stampa il corpo del testo
ottenuto (⚠ = sotto il minimo di legge). Usato il 25/11/2026 per la proposta dello stile base-2026.
"""
import sys
from app import create_app, db
from app.moduli.prodotti.services.ingredienti import testo_html
a = create_app()
STILE = sys.argv[2] if len(sys.argv) > 2 else "base-2026"
PROD = ("Fattoria Ca' Bianca Società Agricola S.S. – Via Costa S. Caterina 1, Ossalengo, "
        "26022 Castelverde (CR), Italia")
def e(**k):
    base = dict(sottotitolo="", tracce="", dichiarazioni_extra="", conservazione="", modalita_uso="",
                prodotto_da=PROD, lavorato_da="", dicitura_scadenza="Da consumarsi preferibilmente entro il",
                piede="www.cabianca.eu · @cabianca.eu", dicitura_peso="Peso netto")
    base.update(k)
    base["ingredienti_html"] = "<b>Ingredienti:</b> " + testo_html(k["ingredienti"])
    return base
prove = [
  ("Grande", "unica", e(nome="Tortelli di zucca", sottotitolo="Pasta artigianale ripiena all'uovo – prodotto congelato", peso="500 g",
     ingredienti="farina di **GRANO** tenero tipo 00, semola di **GRANO** duro, zucca, mostarda (frutta, zucchero, essenza di **SENAPE**), Grana Padano DOP (**LATTE**, sale, caglio, conservante: lisozima da **UOVO**), amaretti (contengono **UOVA**), **UOVA**, sale, pepe, olio extravergine di oliva.",
     tracce="FRUTTA A GUSCIO", conservazione="Conservare in congelatore a -18 °C. Una volta scongelato non ricongelare.",
     modalita_uso="Cuocere da congelati in acqua bollente salata per circa 5 minuti.", lotto="L241126-ZUC", scadenza="24/02/2027")),
  ("Grande", "unica", e(nome="Marubini di carne", sottotitolo="Pasta artigianale ripiena all'uovo – prodotto congelato", peso="500 g",
     ingredienti="farina di **GRANO** tenero tipo 00, semola di **GRANO** duro, carne di bovino, carne di suino, mortadella (con **PISTACCHI**), Grana Padano DOP (**LATTE**, sale, caglio, conservante: lisozima da **UOVO**), **UOVA**, sale, pepe, noce moscata, olio extravergine di oliva, cipolla, carota, vino bianco, pomodoro, aromi naturali.",
     conservazione="Conservare in congelatore a -18 °C. Una volta scongelato non ricongelare.",
     modalita_uso="Cuocere da congelati in acqua bollente salata per circa 5 minuti.", lotto="L241126-MAR", scadenza="24/02/2027")),
  ("Medio", "unica", e(nome="Mostarda di zucca violino", peso="150 g",
     ingredienti="zucca violino, zucchero, succo di limone, essenza di **SENAPE**.", conservazione="Dopo l'apertura conservare in frigorifero.",
     lotto="L061126-MZV", scadenza="06/11/2027")),
  ("Piccolo", "fronte_retro", e(nome="Marmellata di fichi", peso="100 g", ingredienti="fichi freschi, zucchero.",
     dichiarazioni_extra="Frutta utilizzata: 60 g per 100 g. Zuccheri totali: 55 g per 100 g.",
     conservazione="Dopo l'apertura conservare in frigorifero e consumare entro 10 giorni.", lotto="L050826-MFI", scadenza="05/08/2027")),
  ("Salumi", "unica", e(nome="Salame Ca' Bianca", peso="", ingredienti="carne di suino, sale, aromi naturali, spezie, vino, conservante: E252.",
     tracce="aglio", dichiarazioni_extra="Budello non edibile.", conservazione="Conservare in luogo fresco e asciutto.",
     lavorato_da="laboratorio CE IT H5A03", lotto="L6084", scadenza="30/06/2027")),
]
with a.test_request_context():
    from app.moduli.prodotti.routes import etichette as et
    from app.moduli.prodotti.models import FormatoEtichetta
    from app.moduli.prodotti.services import etichette as motore
    formati = {f.nome: et.formato_dict(f) for f in FormatoEtichetta.query.all()}
    pagine, info = [], []
    for nome_f, modalita, dati in prove:
        fd = formati[nome_f]
        scale, corpo, soglia, avviso = et.misura(dati, fd, STILE, modalita)
        parti = list(scale)
        elenco = [p for _ in range(fd["colonne"] * fd["righe"] // len(parti)) for p in parti]
        pagine.append([(x, y, dati, p) for (x, y), p in zip(motore.posizioni(fd), elenco)])
        html = et.componi(dati, fd, STILE, min(scale.values()), "foglio", pagine=[pagine[-1]], guide=True)
        pdf, _ = motore.pdf(html, et._cartella_modulo())
        open(f"{sys.argv[1]}/{len(info)+1}_{nome_f}.pdf", "wb").write(pdf)
        info.append(f"{dati['nome']} – {fd['nome']} {fd['larghezza_mm']:g}×{fd['altezza_mm']:g} – {modalita} – corpo {corpo} pt" + (" ⚠" if avviso else ""))
    print("\n".join(info))
