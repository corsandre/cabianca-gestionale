"""Motore delle etichette: geometria dei fogli A4 pretagliati, adattamento del testo, PDF con WeasyPrint.

Senza Flask: riceve l'HTML già composto dai modelli (templates/prodotti/etichette/stili/<stile>/) e
restituisce PDF o misure. Le route (routes/etichette.py) fanno da tramite con database e template.

Come funziona l'adattamento del testo
-------------------------------------
Ogni stile ha una "scala" dei caratteri (1 = misure di progetto). Per un'etichetta si cerca, con una
ricerca a metà fra 0,5 e 1,4, la scala più grande a cui il testo non sborda (nessun pezzo di testo
sotto il bordo dell'etichetta né su una pagina in più): con poco testo i caratteri crescono, con
tanto testo si riducono. Il corpo minimo del testo che ne risulta si
confronta con il minimo di legge (Reg. UE 1169/2011, art. 13 e allegato IV: altezza della "x" di almeno
1,2 mm, oppure 0,9 mm se la superficie maggiore della confezione è sotto gli 80 cm²). Per Fira Sans
l'altezza della x è circa 0,53 volte il corpo: 1,2 mm ≈ 6,5 pt, 0,9 mm ≈ 4,8 pt.
"""
import hashlib
import os
import threading

PT_PER_MM = 72 / 25.4
ALTEZZA_X_FIRA = 0.527                 # altezza della x / corpo, per Fira Sans
A4 = (210.0, 297.0)


def posizioni(formato):
    """Angolo in alto a sinistra (mm) di ogni etichetta del foglio, riga per riga.

    `formato`: dict con larghezza_mm, altezza_mm, colonne, righe, margine_sup_mm, margine_sx_mm,
    passo_orizz_mm, passo_vert_mm (vuoti = uguali alla misura: etichette attaccate), offset_x_mm,
    offset_y_mm (calibrazione della stampante: spostano tutto).
    """
    passo_x = formato.get("passo_orizz_mm") or formato["larghezza_mm"]
    passo_y = formato.get("passo_vert_mm") or formato["altezza_mm"]
    x0 = (formato.get("margine_sx_mm") or 0) + (formato.get("offset_x_mm") or 0)
    y0 = (formato.get("margine_sup_mm") or 0) + (formato.get("offset_y_mm") or 0)
    return [(round(x0 + c * passo_x, 3), round(y0 + r * passo_y, 3))
            for r in range(formato["righe"]) for c in range(formato["colonne"])]


def controlla_formato(formato):
    """Elenco dei problemi di un formato (vuoto se va bene): etichette fuori dal foglio A4."""
    problemi = []
    pos = posizioni(dict(formato, offset_x_mm=0, offset_y_mm=0))
    destra = max(x for x, _ in pos) + formato["larghezza_mm"]
    sotto = max(y for _, y in pos) + formato["altezza_mm"]
    if destra > A4[0] + 0.01:
        problemi.append(f"le etichette escono a destra del foglio ({destra:.1f} mm su 210)")
    if sotto > A4[1] + 0.01:
        problemi.append(f"le etichette escono in fondo al foglio ({sotto:.1f} mm su 297)")
    return problemi


def fogli_necessari(n_etichette, per_foglio):
    return max(1, -(-int(n_etichette) // int(per_foglio)))


def soglia_pt(piccola_confezione=False):
    """Corpo minimo (pt) che rispetta l'altezza della x di legge con Fira Sans."""
    mm = 0.9 if piccola_confezione else 1.2
    return round(mm / ALTEZZA_X_FIRA * PT_PER_MM, 1)


# ---------------------------------------------------------------- WeasyPrint

# WeasyPrint (con Pango, HarfBuzz e fontconfig sotto) NON regge due disegni contemporanei nello stesso processo.
# Il sito ha 2 thread (gunicorn.conf.py): il 25/11/2026 due anteprime chieste insieme hanno corrotto la memoria
# ("free(): invalid next size") e fatto cadere il sito con un 502. Per questo ogni uso di WeasyPrint passa da
# questo lucchetto. È rientrante perché scala_che_ci_sta chiama sborda.
_WEASYPRINT = threading.RLock()


def _documento(html, base_url):
    from weasyprint import HTML
    return HTML(string=html, base_url=base_url).render()


def _classi(box):
    el = getattr(box, "element", None)
    return (el.get("class") or "").split() if el is not None else []


def _discendenti(box):
    yield box
    for figlio in getattr(box, "children", []) or []:
        yield from _discendenti(figlio)


def sborda(html, base_url, tolleranza_mm=0.3):
    """True se in qualche elemento .etichetta un testo finisce oltre il bordo inferiore (o destro)."""
    with _WEASYPRINT:                                  # anche la lettura dei box usa oggetti di Pango
        return _sborda(html, base_url, tolleranza_mm)


def _sborda(html, base_url, tolleranza_mm):
    doc = _documento(html, base_url)
    if len(doc.pages) > 1:
        return True                                    # quel che non ci sta finisce su una pagina in più
    toll = tolleranza_mm * PT_PER_MM * 96 / 72        # WeasyPrint misura in px CSS (96 per pollice)
    for pagina in doc.pages:
        for box in _discendenti(pagina._page_box):
            if "etichetta" not in _classi(box):
                continue
            basso = box.position_y + box.border_height()
            destra = box.position_x + box.border_width()
            for d in _discendenti(box):
                if type(d).__name__ == "TextBox":
                    if d.position_y + d.height > basso + toll or d.position_x + d.width > destra + toll:
                        return True
    return False


def scala_che_ci_sta(componi_html, base_url, minima=0.5, massima=1.4, passi=6):
    """La scala più grande (tra minima e massima) a cui l'etichetta non sborda.

    Sopra 1 il testo si ingrandisce per riempire lo spazio libero (più leggibile per il cliente).

    `componi_html(scala)` restituisce l'HTML di UNA etichetta a quella scala. Se nemmeno la minima
    ci sta, restituisce la minima (e chi chiama avvisa).
    """
    with _WEASYPRINT:                                  # tutta la ricerca in fila: niente misure intrecciate
        return _scala_che_ci_sta(componi_html, base_url, minima, massima, passi)


def _scala_che_ci_sta(componi_html, base_url, minima, massima, passi):
    if not sborda(componi_html(massima), base_url):
        return massima
    basso, alto = minima, massima
    if sborda(componi_html(basso), base_url):
        return minima
    for _ in range(passi):
        mezzo = (basso + alto) / 2
        if sborda(componi_html(mezzo), base_url):
            alto = mezzo
        else:
            basso = mezzo
    return round(basso, 3)


def pdf(html, base_url):
    """PDF (bytes) e la sua impronta sha256."""
    with _WEASYPRINT:
        dati = _documento(html, base_url).write_pdf()
    return dati, hashlib.sha256(dati).hexdigest()


def png_anteprima(dati_pdf, dpi=200):
    """Prima pagina del PDF come PNG (anteprima leggibile anche sul telefono). Serve pdftoppm (poppler)."""
    import subprocess
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        sorgente, radice = os.path.join(d, "e.pdf"), os.path.join(d, "e")
        with open(sorgente, "wb") as f:
            f.write(dati_pdf)
        r = subprocess.run(["pdftoppm", "-png", "-r", str(dpi), "-f", "1", "-l", "1", "-singlefile", sorgente, radice],
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(r.stderr.decode(errors="replace")[:300])
        with open(radice + ".png", "rb") as f:
            return f.read()


def html_prova_margini():
    """Foglio A4 con righelli dai 4 bordi (0–20 mm): stampato al 100%, il primo numero che si vede su
    ogni lato è il margine che la stampante non riesce a stampare. Serve per scegliere i fogli di etichette
    (i fogli "al vivo" vanno bene solo se la stampante stampa fino al bordo)."""
    segni = []
    for mm in range(0, 21):
        lungo = mm % 5 == 0
        for lato in ("top", "bottom"):              # righelli sui lati corti, a 1/4 e 3/4 della larghezza
            for x in (52.5, 157.5):
                segni.append(f'<div class="t" style="{lato}:{mm}mm;left:{x - (6 if lungo else 3)}mm;'
                             f'width:{12 if lungo else 6}mm"></div>'
                             # numeri sfalsati su 3 colonne: a 1 mm l'uno dall'altro si sovrapporrebbero
                             f'<div class="n" style="{lato}:{mm - 0.8}mm;left:{x + 7 + (mm % 3) * 4.5}mm">{mm}</div>')
        for lato in ("left", "right"):              # righelli sui lati lunghi, a 1/4 e 3/4 dell'altezza
            for y in (74.25, 222.75):
                segni.append(f'<div class="t v" style="{lato}:{mm}mm;top:{y - (6 if lungo else 3)}mm;'
                             f'height:{12 if lungo else 6}mm"></div>'
                             f'<div class="n" style="{lato}:{mm - 0.8}mm;top:{y + 7 + (mm % 3) * 2.6}mm">{mm}</div>')
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0; }} body {{ margin: 0; font-family: sans-serif; }}
.t {{ position: absolute; border-top: 0.25mm solid #000; height: 0; }}
.t.v {{ border-top: 0; border-left: 0.25mm solid #000; width: 0; }}
.n {{ position: absolute; font-size: 4.6pt; line-height: 1; }}
.testo {{ position: absolute; left: 30mm; right: 30mm; top: 110mm; text-align: center; font-size: 11pt; line-height: 1.5; }}
.cornice {{ position: absolute; left: 0; top: 0; width: 210mm; height: 297mm; box-sizing: border-box; border: 0.6mm solid #009d5a; }}
</style></head><body><div class="cornice"></div>{''.join(segni)}
<div class="testo"><b>Prova dei margini della stampante</b><br>
Stampare su carta normale in <b>dimensione reale (100%)</b>, senza «adatta alla pagina».<br>
Su ogni lato contare le tacche che mancano dal bordo (una ogni millimetro, quelle lunghe ogni 5 mm; i numeri
aiutano): sono i millimetri che la stampante non raggiunge (di solito 3–5). La cornice verde è sul bordo esatto del foglio: se non si vede, è normale.<br><br>
I fogli di etichette «al vivo» (etichette fino al bordo) vanno bene solo se tutti i lati segnano 0.
Altrimenti usare fogli con margini più larghi di questi numeri.</div></body></html>"""
