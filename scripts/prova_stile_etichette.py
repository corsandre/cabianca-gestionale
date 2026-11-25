"""Prova di uno stile delle etichette con testi veri di Fattoria Ca' Bianca: un foglio per formato e modalità.

Uso (in locale, con un database qualsiasi: servono solo i formati del modulo):
    RUOLO=sviluppo PYTHONPATH=. .venv/bin/python scripts/prova_stile_etichette.py <cartella_uscita> [stile]
Per ogni formato attivo usa il suo prodotto tipico (lista `prove`) e lo impagina in tutte e due le modalità
(un'etichetta per confezione / fronte e retro), con il contorno tratteggiato delle etichette. Scrive
prova-formati-etichette.pdf (riepilogo + fogli) e un PNG ingrandito di ogni etichetta; stampa il corpo
del testo ottenuto (⚠ = sotto il minimo di legge).
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
  ("Salumi", "piegata", e(nome="Salame Ca' Bianca", peso="", ingredienti="carne di suino, sale, aromi naturali, spezie, vino, conservante: E252.",
     tracce="aglio", dichiarazioni_extra="Budello non edibile.", conservazione="Conservare in luogo fresco e asciutto.",
     lavorato_da="laboratorio CE IT H5A03", lotto="L6084", scadenza="30/06/2027")),
]
MODALITA = {"unica": "un'etichetta per confezione", "fronte_retro": "fronte e retro (due etichette per confezione)",
            "piegata": "piegata sul cordino (salumi: fronte e retro sulla stessa etichetta)"}

with a.test_request_context():
    from pypdf import PdfWriter
    from app.moduli.prodotti.routes import etichette as et
    from app.moduli.prodotti.models import FormatoEtichetta
    from app.moduli.prodotti.services import etichette as motore
    uscita = sys.argv[1]
    formati = [et.formato_dict(f) for f in FormatoEtichetta.query.filter_by(attivo=True).order_by(FormatoEtichetta.id)]
    # per ogni formato il suo prodotto tipico (il primo di `prove` con quel formato) in «unica» e «fronte e retro»;
    # in più le prove dichiarate con un'altra modalità (es. il salame piegato sul cordino, sul formato Grande)
    tipico = {}
    for nome_f, _modalita, dati in prove:
        tipico.setdefault(nome_f, dati)
    casi = [(fd, tipico.get(fd["nome"]) or prove[0][2], m) for fd in formati for m in ("unica", "fronte_retro")]
    for _nome_f, modalita, dati in prove:
        if modalita == "piegata":
            casi += [(fd, dati, "piegata") for fd in formati if fd["nome"] == "Grande"]
    fogli, righe = [], []
    for fd, dati, modalita in casi:
        per_foglio = fd["colonne"] * fd["righe"]
        conf = per_foglio // et.etichette_per_confezione(modalita)
        pdf, _, _, _, (scale, corpo, soglia, avviso) = et.pdf_fogli(dati, fd, STILE, modalita, conf, guide=True)
        nome_file = f"{uscita}/{len(fogli) + 2:02d}_{fd['nome']}_{modalita}.pdf"
        open(nome_file, "wb").write(pdf)
        fogli.append(nome_file)
        for i, im in enumerate(et.immagini_anteprima(dati, fd, STILE, modalita, scale)):   # ingrandite, da guardare a schermo
            import base64
            nome_parte = list(scale)[i] if i < len(scale) else "stampa"
            open(f"{uscita}/anteprima_{fd['nome']}_{modalita}_{nome_parte}.png", "wb").write(
                base64.b64decode(im["src"].split(",", 1)[1]))
        righe.append((len(fogli) + 1, fd, dati["nome"], MODALITA[modalita], conf, corpo, soglia, avviso))
        print(f"{fd['nome']:<8} {modalita:<13} {dati['nome']:<28} corpo {corpo} pt" + (" ⚠" if avviso else ""))
    # pagina di riepilogo in testa
    tabella = "".join(
        f"<tr><td>{n}</td><td><b>{fd['nome']}</b><br>{fd['larghezza_mm']:g}×{fd['altezza_mm']:g} mm · "
        f"{fd['colonne'] * fd['righe']} per foglio<br><small>{fd.get('codice_foglio') or ''} – {fd.get('uso') or ''}</small></td>"
        f"<td>{nome}</td><td>{mod}<br><small>{conf} confezioni per foglio</small></td>"
        f"<td style='color:{'#b00' if avv else '#080'}'><b>{corpo:g} pt</b><br><small>"
        f"{'sotto il minimo di ' + format(soglia, 'g') + ' pt' if avv else 'leggibile'}</small></td></tr>"
        for n, fd, nome, mod, conf, corpo, soglia, avv in righe)
    copertina = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm; }} body {{ font-family: sans-serif; font-size: 10pt; color: #222; }}
h1 {{ color: #8e1f3f; font-size: 18pt; margin: 0 0 2mm; }} table {{ width: 100%; border-collapse: collapse; margin-top: 6mm; }}
td, th {{ border-bottom: 0.3mm solid #ccc; padding: 2mm; text-align: left; vertical-align: top; }} small {{ color: #666; }}
</style></head><body><h1>Prova delle etichette – stile {STILE}</h1>
<p>Un foglio A4 per ogni formato pretagliato e per ogni modalità. Il tratteggio mostra il contorno delle
etichette (sui fogli veri non si stampa). Stampare in <b>dimensione reale (100%)</b>. Il corpo del testo si
adatta da solo; il minimo di legge è circa {soglia:g} pt con questo stile (altezza della x 1,2 mm).</p>
<table><tr><th>Pag.</th><th>Formato</th><th>Prodotto di prova</th><th>Modalità</th><th>Testo</th></tr>{tabella}</table>
</body></html>"""
    pdf, _ = motore.pdf(copertina, et._cartella_modulo())
    open(f"{uscita}/01_riepilogo.pdf", "wb").write(pdf)
    w = PdfWriter()
    for f in [f"{uscita}/01_riepilogo.pdf"] + fogli:
        w.append(f)
    w.write(f"{uscita}/prova-formati-etichette.pdf")
    print(f"→ {uscita}/prova-formati-etichette.pdf")
