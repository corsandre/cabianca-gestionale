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
MODALITA = {"unica": "Un'etichetta per confezione", "fronte_retro": "Fronte e retro (due etichette per confezione)"}


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
    logo = os.path.join(current_app.root_path, "static", "img", "logo.svg")
    return render_template(f"{CARTELLA_STILI}/{stile}/foglio.html", cartella_stile=f"{CARTELLA_STILI}/{stile}",
                           e=e, formato=formato, scala=scala, modo=modo, parte=parte, pagine=pagine or [],
                           guide=guide, logo_url="file://" + logo,
                           font_url=lambda nome: "file://" + os.path.join(fonts, nome))


def parti_per(modalita):
    return ["fronte", "retro"] if modalita == "fronte_retro" else ["unica"]


def misura(e, formato, stile, modalita):
    """Scala che fa stare il testo, per ogni parte; corpo del testo risultante e avviso di legge."""
    base = _cartella_modulo()
    scale = {p: motore.scala_che_ci_sta(lambda s, p=p: componi(e, formato, stile, s, "singola", p), base)
             for p in parti_per(modalita)}
    corpo = round(6.8 * min(scale.values()), 1)          # 6.8 pt = corpo del testo a scala 1 (stile.css)
    soglia = motore.soglia_pt()
    avviso = None
    if corpo < soglia:
        avviso = (f"Testo piccolo: corpo {corpo} pt, sotto i {soglia} pt richiesti (altezza della x 1,2 mm). "
                  f"Scegliere un formato più grande, «fronte e retro», o accorciare i testi. "
                  f"Il minimo è 0,9 mm (≈{motore.soglia_pt(True)} pt) solo se la superficie maggiore della "
                  f"confezione è sotto gli 80 cm².")
    return scale, corpo, soglia, avviso


def _lotto_e_formato(id, d):
    l = db.session.get(Lotto, id)
    if not l:
        abort(404)
    fid = numero(d.get("formato_id"), intero=True) or l.etichetta_dati.get("formato_etichetta_id") \
        or l.prodotto.formato_etichetta_id
    f = db.session.get(FormatoEtichetta, fid or 0) or FormatoEtichetta.query.filter_by(attivo=True).first()
    modalita = d.get("modalita") if d.get("modalita") in MODALITA else (
        "fronte_retro" if f.layout == "compatto" else "unica")
    return l, f, modalita


# ---------------------------------------------------------------- anteprima e stampa

@bp.route("/lotti/<int:id>/etichette/prova", methods=["POST"])
def prova_etichetta(id):
    """Anteprima: immagine dell'etichetta (o di fronte e retro) alla scala che ci sta, con gli avvisi."""
    d = dati_richiesta()
    l, f, modalita = _lotto_e_formato(id, d)
    stile = d.get("stile") if d.get("stile") in stili_disponibili() else stile_attivo()
    e, fd = dati_stampa(l), formato_dict(f)
    scale, corpo, soglia, avviso = misura(e, fd, stile, modalita)
    immagini = []
    for parte, scala in scale.items():
        pdf, _ = motore.pdf(componi(e, fd, stile, scala, "singola", parte), _cartella_modulo())
        png = motore.png_anteprima(pdf, dpi=220)
        immagini.append({"parte": parte, "src": "data:image/png;base64," + base64.b64encode(png).decode()})
    n = numero(d.get("n_confezioni"), intero=True) or l.pezzi_prodotti or f.per_foglio
    n_etichette = n * len(scale)
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
    scale, corpo, soglia, avviso = misura(e, fd, stile, modalita)

    # etichette in fila: per ogni confezione le sue parti (fronte, retro), poi a pagine
    elenco = [p for _ in range(n_confezioni) for p in scale]
    posti, per_foglio = motore.posizioni(fd), f.per_foglio
    pagine = [[(x, y, e, parte) for (x, y), parte in zip(posti, elenco[i:i + per_foglio])]
              for i in range(0, len(elenco), per_foglio)]
    # una sola scala per tutto il foglio (la più piccola), così fronte e retro hanno caratteri coerenti
    html = componi(e, fd, stile, min(scale.values()), "foglio", pagine=pagine)
    dati_pdf, impronta = motore.pdf(html, _cartella_modulo())

    anno = l.data_produzione[:4]
    cartella = os.path.join(cartella_pdf(), anno)
    os.makedirs(cartella, exist_ok=True)
    nome = f"{l.codice}_{impronta[:8]}.pdf"
    percorso = os.path.join(cartella, nome)
    if not os.path.exists(percorso):                    # stesso contenuto = stesso file: mai sovrascrivere
        with open(percorso, "wb") as fh:
            fh.write(dati_pdf)
    s = StampaEtichetta(lotto_id=l.id, formato_id=f.id, stile=stile, n_etichette=len(elenco),
                        pdf_path=f"{anno}/{nome}", sha256=impronta, creato_da=utente(),
                        dati=json.dumps({"etichetta": e, "formato": fd, "modalita": modalita,
                                         "n_confezioni": n_confezioni, "scala": min(scale.values()),
                                         "corpo_pt": corpo, "generata": datetime.now().isoformat(timespec="seconds")},
                                        ensure_ascii=False))
    db.session.add(s)
    db.session.commit()
    return jsonify(ok=True, url=f"/prodotti/etichette/{s.id}.pdf", fogli=len(pagine), n_etichette=len(elenco),
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
