"""Etichette dei lotti: anteprima, stampa (PDF archiviato), download; formati dei fogli e stili.

- Lo stile attivo è l'impostazione "stile_etichette" (cartella in templates/prodotti/etichette/stili/).
- Ogni stampa genera un PDF in data/prodotti/etichette/AAAA/<lotto>_<sha8>.pdf, registrato in
  stampe_etichette con l'impronta sha256 e la copia JSON dei dati stampati. Non si sovrascrive né si
  cancella (il database lo impedisce): una ristampa è una stampa nuova.
- Modalità "unica" = un'etichetta per confezione; "fronte_retro" = due etichette per confezione (fronte
  con marchio/nome/peso e retro con tutto il resto), utile sulle etichette piccole.
"""
import base64
import json
import os
from collections import OrderedDict
from datetime import datetime

from flask import abort, current_app, jsonify, render_template, request, send_file

from app import db
from app.moduli.prodotti.models import FormatoEtichetta, Impostazione, Lotto, StampaEtichetta
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.comune import dati_richiesta, errore, numero, utente
from app.moduli.prodotti.services import etichette as motore
from app.moduli.prodotti.services.ingredienti import testo_html
from app.utils.decorators import write_required

CARTELLA_STILI = "prodotti/etichette/stili"
PIEDE_PREDEFINITO = "www.cabianca.eu · @cabianca.eu"
MODALITA = {"unica": "Un'etichetta per confezione", "fronte_retro": "Fronte e retro (due etichette per confezione)",
            "piegata": "Piegata sul cordino (salumi: fronte e retro sulla stessa etichetta)"}


# ---------------------------------------------------------------- aiuti

def _cartella_modulo():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stili_disponibili():
    radice = os.path.join(_cartella_modulo(), "templates", CARTELLA_STILI)
    return sorted(d for d in os.listdir(radice) if os.path.isfile(os.path.join(radice, d, "foglio.html")))


def stile_attivo():
    s = Impostazione.leggi("stile_etichette", "base-2026")
    return s if s in stili_disponibili() else stili_disponibili()[0]


def cartella_pdf():
    from app.moduli import percorso_database
    return os.path.join(os.path.dirname(percorso_database(current_app, "prodotti")), "prodotti", "etichette")


def formato_dict(f):
    return {c.name: getattr(f, c.name) for c in FormatoEtichetta.__table__.columns}


def dati_stampa(l):
    """Tutto ciò che va sull'etichetta di un lotto (dict `e` dei modelli di stile)."""
    et = l.etichetta_dati
    scad = l.data_scadenza
    peso = et.get("peso") or ""
    return {
        "nome": et.get("nome") or l.prodotto.nome, "sottotitolo": et.get("sottotitolo") or "",
        "peso": peso, "dicitura_peso": "Contenuto netto" if peso.endswith(("ml", " l")) else "Peso netto",
        "ingredienti_html": _ingredienti_html(l.ingredienti_testo), "tracce": et.get("tracce") or "",
        "conservazione": et.get("conservazione") or "", "modalita_uso": et.get("modalita_uso") or "",
        "dichiarazioni_extra": et.get("dichiarazioni_extra") or "", "prodotto_da": et.get("prodotto_da") or "",
        "lavorato_da": et.get("lavorato_da") or "", "lotto": l.codice,
        "dicitura_scadenza": et.get("dicitura_scadenza") or "Da consumarsi preferibilmente entro il",
        "scadenza": f"{scad[8:10]}/{scad[5:7]}/{scad[:4]}" if scad else "",
        "piede": Impostazione.leggi("piede_etichette", PIEDE_PREDEFINITO),
    }


def _ingredienti_html(testo):
    """Elenco ingredienti in HTML con "Ingredienti:" in grassetto, come nelle etichette storiche."""
    html = testo_html(testo or "")
    for prefisso in ("Ingredienti:", "Ingredienti :"):
        if html.startswith(prefisso):
            return f"<b>Ingredienti:</b>{html[len(prefisso):]}"
    return html


def componi(e, formato, stile, scala=1.0, modo="singola", parte="unica", pagine=None, guide=False):
    """HTML del documento delle etichette con lo stile indicato."""
    fonts = os.path.join(_cartella_modulo(), "static", "fonts")
    # logo in PNG (600 dpi, trasparente, ricavato da app/static/img/logo.svg con WeasyPrint + pdftocairo -transp):
    # l'SVG è un disegno complesso che WeasyPrint ridisegna in ogni etichetta, e rendeva i PDF 5-10 volte più lenti
    logo = os.path.join(_cartella_modulo(), "static", "img", "logo-etichette.png")
    return render_template(f"{CARTELLA_STILI}/{stile}/foglio.html", cartella_stile=f"{CARTELLA_STILI}/{stile}",
                           e=e, formato=formato, scala=scala, modo=modo, parte=parte, pagine=pagine or [],
                           guide=guide, logo_url="file://" + logo,
                           font_url=lambda nome: "file://" + os.path.join(fonts, nome))


def parti_per(modalita):
    return ["fronte", "retro"] if modalita in ("fronte_retro", "piegata") else ["unica"]


def formato_parti(formato, modalita):
    """Misure su cui si disegnano le parti: con «piegata» fronte e retro sono le due metà dell'etichetta
    (services/etichette.formato_meta), altrimenti l'etichetta intera."""
    return motore.formato_meta(formato) if modalita == "piegata" else formato


def etichette_per_confezione(modalita):
    """Quante etichette del foglio servono per una confezione (fronte e retro separati = 2)."""
    return 2 if modalita == "fronte_retro" else 1


def pdf_fogli(e, formato, stile, modalita, n_confezioni, guide=False):
    """PDF dei fogli A4 per `n_confezioni` confezioni: ogni parte si disegna UNA volta e si copia in tutte le
    posizioni (services/etichette.foglio_da_etichette). Una sola scala per tutto (la più piccola), così fronte
    e retro hanno caratteri coerenti. Con `guide` sotto c'è il contorno tratteggiato delle etichette (prove su
    carta normale). Restituisce (pdf, sha256, fogli, n_etichette, misura)."""
    m = misura(e, formato, stile, modalita)
    scale = m[0]
    scala, fp = min(scale.values()), formato_parti(formato, modalita)
    disegni = {p: motore.pdf(componi(e, fp, stile, scala, "singola", p), _cartella_modulo())[0] for p in scale}
    if modalita == "piegata":
        disegni = {"unica": motore.piega(disegni["fronte"], disegni["retro"], formato)}
    parti = list(disegni)
    elenco = [p for _ in range(n_confezioni) for p in parti]
    posti, per_foglio = motore.posizioni(formato), len(motore.posizioni(formato))
    pagine = [[(x, y, parte) for (x, y), parte in zip(posti, elenco[i:i + per_foglio])]
              for i in range(0, len(elenco), per_foglio)]
    sotto = motore.pdf(html_guide(formato), _cartella_modulo())[0] if guide else None
    dati, impronta = motore.foglio_da_etichette(disegni, pagine, formato, sotto=sotto)
    return dati, impronta, len(pagine), len(elenco), m


def html_guide(formato):
    """Pagina A4 con il contorno tratteggiato di ogni etichetta del foglio (per le prove su carta normale)."""
    w, h = formato["larghezza_mm"], formato["altezza_mm"]
    caselle = "".join(f'<div style="position:absolute;left:{x}mm;top:{y}mm;width:{w}mm;height:{h}mm;'
                      f'box-sizing:border-box;border:0.2mm dashed #999"></div>' for x, y in motore.posizioni(formato))
    return f'<!doctype html><html><head><style>@page{{size:A4;margin:0}}</style></head><body style="margin:0">{caselle}</body></html>'


# Misure già fatte (la ricerca della scala richiede ~10 disegni): l'anteprima e poi la stampa dello stesso
# lotto, o due anteprime uguali, la riusano. La chiave contiene tutti i dati dell'etichetta, quindi una
# modifica qualsiasi rifà la misura.
_MISURE = OrderedDict()


def misura(e, formato, stile, modalita):
    """Scala che fa stare il testo, per ogni parte; corpo del testo risultante e avviso di legge."""
    chiave = json.dumps([e, formato, stile, modalita], sort_keys=True, default=str)
    if chiave in _MISURE:
        _MISURE.move_to_end(chiave)
        return _MISURE[chiave]
    risultato = _misura(e, formato, stile, modalita)
    _MISURE[chiave] = risultato
    while len(_MISURE) > 200:
        _MISURE.popitem(last=False)
    return risultato


PARAMETRI_STILE_PREDEFINITI = {"corpo_pt": 6.8, "altezza_x": motore.ALTEZZA_X_FIRA}


def parametri_stile(stile):
    """Misure del testo dichiarate dallo stile in stile.json (facoltativo):
    corpo_pt = corpo dei testi a scala 1 (come in stile.css), altezza_x = altezza della x / corpo del carattere
    dei testi. Servono per il controllo del minimo di legge."""
    p = dict(PARAMETRI_STILE_PREDEFINITI)
    percorso = os.path.join(_cartella_modulo(), "templates", CARTELLA_STILI, stile, "stile.json")
    if os.path.exists(percorso):
        with open(percorso, encoding="utf-8") as f:
            p.update({k: v for k, v in json.load(f).items() if k in p})
    return p


def _misura(e, formato, stile, modalita):
    base = _cartella_modulo()
    fp = formato_parti(formato, modalita)
    scale = {p: motore.scala_che_ci_sta(lambda s, p=p: componi(e, fp, stile, s, "singola", p), base)
             for p in parti_per(modalita)}
    ps = parametri_stile(stile)
    corpo = round(ps["corpo_pt"] * min(scale.values()), 1)
    soglia = motore.soglia_pt(altezza_x=ps["altezza_x"])
    avviso = None
    if corpo < soglia:
        avviso = (f"Testo piccolo: corpo {corpo} pt, sotto i {soglia} pt richiesti (altezza della x 1,2 mm). "
                  f"Scegliere un formato più grande, «fronte e retro», o accorciare i testi. "
                  f"Il minimo è 0,9 mm (≈{motore.soglia_pt(True, ps['altezza_x'])} pt) solo se la superficie "
                  f"maggiore della confezione è sotto gli 80 cm².")
    return scale, corpo, soglia, avviso


def _lotto_e_formato(id, d):
    l = db.session.get(Lotto, id)
    if not l:
        abort(404)
    fid = numero(d.get("formato_id"), intero=True) or l.etichetta_dati.get("formato_etichetta_id") \
        or l.prodotto.formato_etichetta_id
    f = db.session.get(FormatoEtichetta, fid or 0) or FormatoEtichetta.query.filter_by(attivo=True).first()
    modalita = d.get("modalita") if d.get("modalita") in MODALITA else modalita_proposta(f, l.prodotto)
    return l, f, modalita


def modalita_proposta(formato, prodotto=None):
    """Salumi: piegata sul cordino; etichette piccole: fronte e retro; le altre: un'etichetta."""
    if prodotto is not None and (prodotto.categoria or "") == "Salumi":
        return "piegata"
    return "fronte_retro" if formato.layout == "compatto" else "unica"


# ---------------------------------------------------------------- anteprima e stampa

def immagini_anteprima(e, fd, stile, modalita, scale, dpi=220):
    """PNG di ogni parte (dritta, per leggerla); con «piegata» anche l'etichetta intera come si stampa."""
    fp = formato_parti(fd, modalita)
    immagini, pdf_parti = [], {}
    for parte, scala in scale.items():
        pdf, _ = motore.pdf(componi(e, fp, stile, scala, "singola", parte), _cartella_modulo())
        pdf_parti[parte] = pdf
        immagini.append({"parte": parte, "src": "data:image/png;base64,"
                         + base64.b64encode(motore.png_anteprima(pdf, dpi=dpi)).decode()})
    if modalita == "piegata":
        # stessa scala per le due metà, come nella stampa
        scala = min(scale.values())
        pdf_parti = {p: motore.pdf(componi(e, fp, stile, scala, "singola", p), _cartella_modulo())[0] for p in scale}
        intera = motore.piega(pdf_parti["fronte"], pdf_parti["retro"], fd)
        immagini.append({"parte": "come si stampa (piega al centro, sul cordino)", "src": "data:image/png;base64,"
                         + base64.b64encode(motore.png_anteprima(intera, dpi=int(dpi * 0.7))).decode()})
    return immagini


@bp.route("/lotti/<int:id>/etichette/prova", methods=["POST"])
def prova_etichetta(id):
    """Anteprima: immagine dell'etichetta (o di fronte e retro) alla scala che ci sta, con gli avvisi."""
    d = dati_richiesta()
    l, f, modalita = _lotto_e_formato(id, d)
    stile = d.get("stile") if d.get("stile") in stili_disponibili() else stile_attivo()
    e, fd = dati_stampa(l), formato_dict(f)
    scale, corpo, soglia, avviso = misura(e, fd, stile, modalita)
    immagini = immagini_anteprima(e, fd, stile, modalita, scale)
    n = numero(d.get("n_confezioni"), intero=True) or l.pezzi_prodotti or f.per_foglio
    n_etichette = n * etichette_per_confezione(modalita)
    return jsonify(ok=True, immagini=immagini, scala=min(scale.values()), corpo_pt=corpo, soglia_pt=soglia,
                   avviso=avviso, formato=f.descrizione, modalita=modalita, n_etichette=n_etichette,
                   fogli=motore.fogli_necessari(n_etichette, f.per_foglio), stile=stile,
                   problemi_formato=motore.controlla_formato(fd))


@bp.route("/lotti/<int:id>/etichette/stampa", methods=["POST"])
@write_required
def stampa_etichette(id):
    """Genera il PDF dei fogli, lo archivia e restituisce l'indirizzo per aprirlo."""
    d = dati_richiesta()
    l, f, modalita = _lotto_e_formato(id, d)
    n_confezioni = numero(d.get("n_confezioni"), intero=True)
    if not n_confezioni or n_confezioni < 1:
        return errore("Indicare quante confezioni etichettare.")
    if n_confezioni > 2000:
        return errore("Troppe etichette in una volta (massimo 2000 confezioni).")
    stile = stile_attivo()
    e, fd = dati_stampa(l), formato_dict(f)
    problemi = motore.controlla_formato(fd)
    if problemi:
        return errore("Formato non valido: " + "; ".join(problemi))
    dati_pdf, impronta, n_fogli, n_etichette, (scale, corpo, soglia, avviso) = pdf_fogli(e, fd, stile, modalita, n_confezioni)

    anno = l.data_produzione[:4]
    cartella = os.path.join(cartella_pdf(), anno)
    os.makedirs(cartella, exist_ok=True)
    nome = f"{l.codice}_{impronta[:8]}.pdf"
    percorso = os.path.join(cartella, nome)
    if not os.path.exists(percorso):                    # stesso contenuto = stesso file: mai sovrascrivere
        with open(percorso, "wb") as fh:
            fh.write(dati_pdf)
    s = StampaEtichetta(lotto_id=l.id, formato_id=f.id, stile=stile, n_etichette=n_etichette,
                        pdf_path=f"{anno}/{nome}", sha256=impronta, creato_da=utente(),
                        dati=json.dumps({"etichetta": e, "formato": fd, "modalita": modalita,
                                         "n_confezioni": n_confezioni, "scala": min(scale.values()),
                                         "corpo_pt": corpo, "generata": datetime.now().isoformat(timespec="seconds")},
                                        ensure_ascii=False))
    db.session.add(s)
    db.session.commit()
    return jsonify(ok=True, url=f"/prodotti/etichette/{s.id}.pdf", fogli=n_fogli, n_etichette=n_etichette,
                   avviso=avviso)


@bp.route("/etichette/<int:id>.pdf")
def scarica_etichette(id):
    s = db.session.get(StampaEtichetta, id)
    if not s:
        abort(404)
    percorso = os.path.realpath(os.path.join(cartella_pdf(), s.pdf_path))
    if not percorso.startswith(os.path.realpath(cartella_pdf()) + os.sep) or not os.path.exists(percorso):
        abort(404)
    scarica = request.args.get("scarica") == "1"
    return send_file(percorso, mimetype="application/pdf", as_attachment=scarica,
                     download_name=os.path.basename(s.pdf_path))


# ---------------------------------------------------------------- formati, stili, impostazioni (pagina «Formati e stili»)

# Dati d'esempio per provare formati e stili senza un lotto (testi veri dei tortelli di zucca)
ESEMPIO = {
    "nome": "Tortelli di zucca", "sottotitolo": "Pasta artigianale ripiena all'uovo – prodotto congelato",
    "peso": "500 g", "dicitura_peso": "Peso netto",
    "ingredienti_html": "<b>Ingredienti:</b> farina di <strong>GRANO</strong> tenero tipo 00, semola di "
                        "<strong>GRANO</strong> duro, zucca, mostarda (frutta, zucchero, essenza di <strong>SENAPE</strong>), "
                        "Grana Padano DOP (<strong>LATTE</strong>, sale, caglio, conservante: lisozima da <strong>UOVO</strong>), "
                        "amaretti (contengono <strong>UOVA</strong>), <strong>UOVA</strong>, sale, pepe, olio extravergine di oliva.",
    "tracce": "FRUTTA A GUSCIO", "conservazione": "Conservare in congelatore a -18 °C. Una volta scongelato non ricongelare.",
    "modalita_uso": "Cuocere da congelati in acqua bollente salata per circa 5 minuti.", "dichiarazioni_extra": "",
    "prodotto_da": "", "lavorato_da": "", "lotto": "L241126-ZUC",
    "dicitura_scadenza": "Da consumarsi preferibilmente entro il", "scadenza": "24/02/2027", "piede": "",
}


@bp.route("/formati")
def formati():
    elenco = FormatoEtichetta.query.order_by(FormatoEtichetta.id).all()
    return render_template("prodotti/formati.html", formati=elenco, stili=stili_disponibili(), stile=stile_attivo(),
                           piede=Impostazione.leggi("piede_etichette", PIEDE_PREDEFINITO),
                           produttore=Impostazione.leggi("produttore", ""),
                           problemi={f.id: motore.controlla_formato(formato_dict(f)) for f in elenco},
                           formati_json=[formato_dict(f) for f in elenco])


@bp.route("/formati/salva", methods=["POST"])
@write_required
def salva_formato():
    from flask_login import current_user
    if current_user.role != "admin":                       # JSON, non la pagina 403 di admin_required
        return errore("Solo l'amministratore modifica i formati.", 403)
    d = dati_richiesta()
    f = db.session.get(FormatoEtichetta, int(d["id"])) if d.get("id") else FormatoEtichetta()
    if f is None:
        return errore("Formato non trovato.", 404)
    nome = (d.get("nome") or "").strip()
    if not nome:
        return errore("Il nome è obbligatorio.")
    misure = {}
    for c in ("larghezza_mm", "altezza_mm", "margine_sup_mm", "margine_sx_mm", "passo_orizz_mm", "passo_vert_mm",
              "offset_x_mm", "offset_y_mm"):
        misure[c] = numero(d.get(c))
    for c in ("colonne", "righe"):
        misure[c] = numero(d.get(c), intero=True)
    if not all(misure[c] and misure[c] > 0 for c in ("larghezza_mm", "altezza_mm", "colonne", "righe")):
        return errore("Misure, colonne e righe devono essere maggiori di zero.")
    for c in ("margine_sup_mm", "margine_sx_mm", "offset_x_mm", "offset_y_mm"):
        misure[c] = misure[c] or 0
    problemi = motore.controlla_formato(misure)
    if problemi:
        return errore("Formato non valido: " + "; ".join(problemi))
    for c, v in misure.items():
        setattr(f, c, v)
    f.nome, f.uso = nome, (d.get("uso") or "").strip() or None
    f.codice_foglio = (d.get("codice_foglio") or "").strip() or None
    f.layout = d.get("layout") if d.get("layout") in ("orizzontale", "compatto") else "orizzontale"
    f.attivo = str(d.get("attivo", True)).lower() not in ("false", "0", "")
    db.session.add(f)
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/formati/impostazioni", methods=["POST"])
@write_required
def salva_impostazioni_etichette():
    from flask_login import current_user
    if current_user.role != "admin":
        return errore("Solo l'amministratore modifica le impostazioni.", 403)
    d = dati_richiesta()
    if d.get("stile") not in stili_disponibili():
        return errore("Stile sconosciuto.")
    Impostazione.scrivi("stile_etichette", d["stile"])
    Impostazione.scrivi("piede_etichette", (d.get("piede") or "").strip())
    if (d.get("produttore") or "").strip():
        Impostazione.scrivi("produttore", d["produttore"].strip())
    db.session.commit()
    return jsonify(ok=True)


@bp.route("/formati/<int:id>/prova", methods=["POST"])
def prova_formato(id):
    """Anteprima di un formato con uno stile (anche non attivo), sui dati d'esempio."""
    f = db.session.get(FormatoEtichetta, id) or abort(404)
    d = dati_richiesta()
    stile = d.get("stile") if d.get("stile") in stili_disponibili() else stile_attivo()
    modalita = d.get("modalita") if d.get("modalita") in MODALITA else (
        "fronte_retro" if f.layout == "compatto" else "unica")
    e = dict(ESEMPIO, prodotto_da=Impostazione.leggi("produttore", ""),
             piede=Impostazione.leggi("piede_etichette", PIEDE_PREDEFINITO))
    fd = formato_dict(f)
    scale, corpo, soglia, avviso = misura(e, fd, stile, modalita)
    immagini = immagini_anteprima(e, fd, stile, modalita, scale, dpi=200)
    return jsonify(ok=True, immagini=immagini, corpo_pt=corpo, soglia_pt=soglia, avviso=avviso)


@bp.route("/formati/prova-margini.pdf")
def prova_margini():
    """Foglio per misurare i margini che la stampante non stampa (vedi services/etichette.html_prova_margini)."""
    from io import BytesIO
    dati, _ = motore.pdf(motore.html_prova_margini(), _cartella_modulo())
    return send_file(BytesIO(dati), mimetype="application/pdf", download_name="prova_margini_stampante.pdf")


@bp.route("/formati/<int:id>/calibrazione.pdf")
def calibrazione(id):
    """Foglio di calibrazione: contorni e centri di tutte le etichette, da stampare su carta normale.

    Sovrapponendolo controluce a un foglio pretagliato si vede di quanto la stampante sposta la stampa:
    quei millimetri vanno in "spostamento X/Y" del formato (positivi = verso destra / verso il basso).
    """
    f = db.session.get(FormatoEtichetta, id) or abort(404)
    fd = formato_dict(f)
    posti = motore.posizioni(fd)
    w, h = f.larghezza_mm, f.altezza_mm
    caselle = "".join(
        f'<div class="c" style="left:{x}mm;top:{y}mm"><div class="n">{i + 1}</div>'
        f'<div class="h"></div><div class="v"></div></div>' for i, (x, y) in enumerate(posti))
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 0; }} body {{ margin: 0; font-family: sans-serif; }}
.c {{ position: absolute; width: {w}mm; height: {h}mm; box-sizing: border-box; border: 0.2mm solid #000; }}
.n {{ position: absolute; left: 1.5mm; top: 1mm; font-size: 7pt; color: #555; }}
.h {{ position: absolute; left: {w / 2 - 4}mm; top: {h / 2}mm; width: 8mm; border-top: 0.2mm solid #000; }}
.v {{ position: absolute; left: {w / 2}mm; top: {h / 2 - 4}mm; height: 8mm; border-left: 0.2mm solid #000; }}
.t {{ position: absolute; left: 0; right: 0; top: {min(posti[0][1] + h / 2 + 6, 140)}mm; text-align: center; font-size: 8pt; color: #333; }}
</style></head><body>{caselle}
<div class="t">Foglio di calibrazione – {f.descrizione} – spostamento attuale X {f.offset_x_mm:g} mm, Y {f.offset_y_mm:g} mm.<br>
Stampare al 100% su carta normale, sovrapporre al foglio pretagliato controluce e misurare lo scarto.</div>
</body></html>"""
    dati, _ = motore.pdf(html, _cartella_modulo())
    from io import BytesIO
    return send_file(BytesIO(dati), mimetype="application/pdf", download_name=f"calibrazione_{f.nome}.pdf")
