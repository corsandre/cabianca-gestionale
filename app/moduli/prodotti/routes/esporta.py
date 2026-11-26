"""Export del libro lotti e del ricettario, in PDF (da mostrare in un controllo) ed Excel (per lavorarci).

- Libro lotti: stessi filtri della pagina (routes/lotti.lotti_filtrati). PDF orizzontale con un blocco per
  lotto e i suoi ingredienti; Excel con due fogli, «Lotti» e «Ingredienti» (una riga per ingrediente,
  comodo da filtrare per fornitore o lotto del fornitore).
- Ricettario: tutte le ricette (anche le versioni vecchie) o una sola (?ricetta=<id>); PDF con una
  ricetta per pagina, Excel con fogli «Ricette» e «Ingredienti».
- Richiamo: PDF dei lotti trovati dalla ricerca della pagina Richiamo (routes/richiamo.py).
"""
import os
from datetime import datetime
from io import BytesIO

from flask import abort, current_app, render_template, request, send_file

from app import db
from app.moduli.prodotti.models import Lotto, Prodotto, Ricetta
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.comune import utente
from app.moduli.prodotti.routes.lotti import filtri_lotti, lotti_filtrati
from app.moduli.prodotti.services import etichette as motore
from app.moduli.prodotti.services import ingredienti as ing
from app.moduli.prodotti.services.allergeni import descrivi


def _cartella_modulo():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pdf_da_modello(modello, nome_file, **dati):
    """Rende un modello di templates/prodotti/stampe/ in PDF e lo manda al browser (si apre nel visore)."""
    fonts = os.path.join(_cartella_modulo(), "static", "fonts")
    html = render_template(modello, generato=datetime.now().strftime("%d/%m/%Y %H:%M"), utente=utente(),
                           logo_url="file://" + os.path.join(current_app.root_path, "static", "img", "logo.svg"),
                           font_url=lambda n: "file://" + os.path.join(fonts, n), testo_html=ing.testo_html, **dati)
    dati_pdf, _ = motore.pdf(html, _cartella_modulo())
    return send_file(BytesIO(dati_pdf), mimetype="application/pdf", download_name=nome_file,
                     as_attachment=request.args.get("scarica") == "1")


def excel(fogli, nome_file):
    """fogli: lista di (titolo, intestazioni, righe). Intestazione in grassetto, filtri, colonne a misura."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    wb.remove(wb.active)
    for titolo, intestazioni, righe in fogli:
        ws = wb.create_sheet(titolo[:31])
        ws.append(intestazioni)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="009D5A")
        for r in righe:
            ws.append(list(r))
        ws.freeze_panes = "A2"
        if righe:
            ws.auto_filter.ref = ws.dimensions
        for i, testa in enumerate(intestazioni, 1):
            larghezza = max([len(str(testa))] + [len(str(r[i - 1] or "")) for r in righe[:500]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(10, larghezza + 2), 60)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=nome_file,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _data_it(iso):
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def descrivi_filtri(f):
    parti = []
    if f["dal"] or f["al"]:
        parti.append(f"periodo {_data_it(f['dal']) or 'inizio'} – {_data_it(f['al']) or 'oggi'}")
    if f["prodotto"]:
        p = db.session.get(Prodotto, int(f["prodotto"]))
        parti.append(f"prodotto {p.nome_completo if p else '?'}")
    if f["stato"]:
        parti.append(f"stato {Lotto.STATI.get(f['stato'], f['stato'])}")
    if f["q"]:
        parti.append(f"ricerca «{f['q']}»")
    return ", ".join(parti) or "tutti i lotti"


# ---------------------------------------------------------------- libro lotti

@bp.route("/lotti/esporta.<formato>")
def esporta_lotti(formato):
    f = filtri_lotti(request.args)
    lotti = lotti_filtrati(f)
    oggi = datetime.now().strftime("%Y%m%d")
    if formato == "pdf":
        # nel PDF dal più vecchio al più recente, come un registro
        return pdf_da_modello("prodotti/stampe/libro_lotti.html", f"libro_lotti_{oggi}.pdf", orizzontale=True,
                              titolo="Libro dei lotti", sottotitolo=descrivi_filtri(f),
                              filtri_testo=descrivi_filtri(f).capitalize(), lotti=list(reversed(lotti)),
                              stati=Lotto.STATI)
    if formato != "xlsx":
        abort(404)
    righe_lotti, righe_ing = [], []
    for l in reversed(lotti):
        righe_lotti.append([l.codice, l.prodotto.nome_completo, _data_it(l.data_produzione), _data_it(l.data_scadenza),
                            l.pezzi_prodotti, l.confezioni_testo, l.ricetta.etichetta if l.ricetta else "", Lotto.STATI.get(l.stato),
                            l.stato_motivo or "", descrivi(l.allergeni_lista), (l.ingredienti_testo or "").replace("**", ""),
                            l.creato_da or "", l.note or ""])
        for r in l.ingredienti:
            righe_ing.append([l.codice, l.prodotto.nome_completo, _data_it(l.data_produzione), r.nome, r.quantita,
                              r.unita, "sì" if r.produzione_propria else "", r.fornitore_nome or "",
                              r.lotto_fornitore or "", r.rif_documento or ""])
    return excel([
        ("Lotti", ["Codice", "Prodotto", "Produzione", "Scadenza", "Pezzi", "Confezioni", "Ricetta", "Stato", "Motivo stato",
                   "Allergeni", "Ingredienti in etichetta", "Registrato da", "Note"], righe_lotti),
        ("Ingredienti", ["Codice lotto", "Prodotto", "Produzione", "Ingrediente", "Quantità", "Unità",
                         "Produzione propria", "Fornitore", "Lotto fornitore", "Documento"], righe_ing),
    ], f"libro_lotti_{oggi}.xlsx")


# ---------------------------------------------------------------- ricettario

def _ricetta_dict(r, lotti_per_ricetta):
    righe = [x.materia_prima.come_riga_ricetta(x.quantita, x.unita) for x in r.righe]
    perc = ing.percentuali(righe)
    testo = ing.testo_ingredienti(righe)
    return {
        "prodotto": r.prodotto.nome_completo, "sigla": r.prodotto.sigla, "versione": r.etichetta,
        "resa_pezzi": r.resa_pezzi, "resa_kg": r.resa_kg, "attiva": r.attiva, "contenitori": r.contenitori_testo,
        "predefinita": r.prodotto.ricetta_default_id == r.id, "creato_il": r.creato_il, "creato_da": r.creato_da,
        "n_lotti": lotti_per_ricetta.get(r.id, 0), "procedimento": r.procedimento, "note_haccp": r.note_haccp,
        "ingredienti_html": ing.testo_html(testo), "ingredienti_testo": testo.replace("**", ""), "allergeni": descrivi(ing.allergeni_presenti(righe)),
        "righe": [{"nome": x.materia_prima.nome, "etichetta": x.materia_prima.nome_etichetta,
                   "quantita": f"{x.quantita:g} {x.unita}", "quantita_num": x.quantita, "unita": x.unita,
                   "percentuale": f"{perc.get(x.materia_prima.nome_etichetta, 0):g}".replace(".", ","),
                   "allergeni": descrivi(x.materia_prima.allergeni_lista),
                   "fornitore": "produzione propria" if x.materia_prima.produzione_propria
                   else (x.materia_prima.fornitore_nome or "")} for x in r.righe],
    }


@bp.route("/ricettario/esporta.<formato>")
def esporta_ricettario(formato):
    query = Ricetta.query.join(Prodotto)
    if request.args.get("ricetta"):
        query = query.filter(Ricetta.id == int(request.args["ricetta"]))
    elif request.args.get("solo_attive") == "1":
        query = query.filter(Ricetta.attiva.is_(True))
    ricette = query.order_by(Prodotto.nome, Ricetta.versione).all()
    lotti_per_ricetta = dict(db.session.query(Lotto.ricetta_id, db.func.count(Lotto.id)).group_by(Lotto.ricetta_id))
    dati = [_ricetta_dict(r, lotti_per_ricetta) for r in ricette]
    oggi = datetime.now().strftime("%Y%m%d")
    nome = f"ricetta_{ricette[0].prodotto.sigla}_v{ricette[0].versione}" if request.args.get("ricetta") and ricette \
        else f"ricettario_{oggi}"
    if formato == "pdf":
        return pdf_da_modello("prodotti/stampe/ricettario.html", f"{nome}.pdf", orizzontale=False,
                              titolo="Ricettario", sottotitolo=f"{len(dati)} " + ("ricetta" if len(dati) == 1 else "ricette"), ricette=dati)
    if formato != "xlsx":
        abort(404)
    return excel([
        ("Ricette", ["Prodotto", "Sigla", "Versione", "Resa pezzi", "Resa kg", "Contenitori", "In uso", "Proposta per i lotti",
                     "Lotti fatti", "Allergeni", "Ingredienti in etichetta", "Procedimento", "Note HACCP", "Creata il"],
         [[d["prodotto"], d["sigla"], d["versione"], d["resa_pezzi"], d["resa_kg"], d["contenitori"], "sì" if d["attiva"] else "no",
           "sì" if d["predefinita"] else "", d["n_lotti"], d["allergeni"],
           d["ingredienti_testo"],
           d["procedimento"] or "", d["note_haccp"] or "", _data_it(d["creato_il"])] for d in dati]),
        ("Ingredienti", ["Prodotto", "Versione", "Materia prima", "In etichetta", "Quantità", "Unità", "%",
                         "Allergeni", "Fornitore abituale"],
         [[d["prodotto"], d["versione"], x["nome"], x["etichetta"], x["quantita_num"], x["unita"], x["percentuale"],
           x["allergeni"], x["fornitore"]] for d in dati for x in d["righe"]]),
    ], f"{nome}.xlsx")
