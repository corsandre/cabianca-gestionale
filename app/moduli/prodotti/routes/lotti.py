"""Libro dei lotti: elenco con filtri, scheda del lotto, finestra "Nuovo lotto", cambio di stato.

Flusso della finestra "Nuovo lotto" (static/lotti.js):
  1. si sceglie il prodotto (o se ne crea uno nuovo);
  2. GET /prodotti/lotti/prepara → ricetta proposta, codice lotto e scadenza calcolati, ingredienti con le
     quantità scalate sui pezzi e fornitore/lotto del fornitore PRECOMPILATI con quelli usati l'ultima
     volta per la stessa materia prima;
  3. si controlla/corregge e si salva (POST /prodotti/lotti/salva).

Il lotto conserva una COPIA dei dati di etichetta del prodotto (`dati_etichetta`) e del testo degli
ingredienti: se in futuro il prodotto cambia, il registro mostra com'era quel lotto.
Correzioni: permesse, ma il database registra ogni modifica nello storico (schema.py).
"""
import json
from datetime import date

from flask import jsonify, redirect, render_template, request, url_for

from app import db
from app.moduli.prodotti.models import Lotto, LottoIngrediente, MateriaPrima, Prodotto, Ricetta, Storico
from app.moduli.prodotti.routes import bp
from app.moduli.prodotti.routes.catalogo import _dati_modale_prodotto
from app.moduli.prodotti.routes.comune import (
    adesso, crea_fornitore, dati_richiesta, errore, fornitori, nome_fornitore, numero, utente, vero,
)
from app.moduli.prodotti.services import ingredienti as ing
from app.moduli.prodotti.services.allergeni import ALLERGENI, descrivi
from app.moduli.prodotti.services.lotti import (
    arrotonda_quantita, codice_lotto, da_iso, data_scadenza, fattore_scala,
)
from app.utils.decorators import write_required


# ---------------------------------------------------------------- dati per la finestra

def dati_etichetta(p):
    """Copia dei dati del prodotto che finiscono in etichetta, salvata nel lotto."""
    return {"nome": p.nome, "sottotitolo": p.sottotitolo, "peso": p.peso_testo,
            "dicitura_scadenza": Prodotto.TIPI_SCADENZA.get(p.tipo_scadenza), "conservazione": p.conservazione,
            "modalita_uso": p.modalita_uso, "tracce": p.tracce, "prodotto_da": p.prodotto_da,
            "lavorato_da": p.lavorato_da, "dichiarazioni_extra": p.dichiarazioni_extra,
            "formato_etichetta_id": p.formato_etichetta_id}


def ultima_provenienza(materia_prima_id):
    """Fornitore e lotto del fornitore usati l'ultima volta per questa materia prima (per precompilare)."""
    r = (LottoIngrediente.query.filter_by(materia_prima_id=materia_prima_id)
         .join(Lotto).order_by(Lotto.data_produzione.desc(), LottoIngrediente.id.desc()).first())
    if not r:
        return None
    return {"fornitore_id": r.fornitore_id, "fornitore_nome": r.fornitore_nome or "",
            "lotto_fornitore": r.lotto_fornitore or "", "rif_documento": r.rif_documento or "",
            "produzione_propria": bool(r.produzione_propria)}


def righe_da_ricetta(ricetta, pezzi):
    """Ingredienti del lotto proposti dalla ricetta, scalati sui pezzi e con la provenienza precompilata."""
    fattore = fattore_scala(ricetta.resa_pezzi, pezzi)
    out = []
    for x in ricetta.righe:
        m = x.materia_prima
        riga = {"materia_prima_id": m.id, "nome": m.nome, "quantita": arrotonda_quantita(x.quantita * fattore),
                "unita": x.unita, "fornitore_id": m.fornitore_id, "fornitore_nome": m.fornitore_nome or "",
                "lotto_fornitore": "", "rif_documento": "", "produzione_propria": bool(m.produzione_propria),
                "precompilato": False}
        ultima = ultima_provenienza(m.id)
        if ultima:
            riga.update(ultima, precompilato=True)
        out.append(riga)
    return out


def testo_da_righe(righe):
    """Elenco ingredienti di legge dalle righe del lotto (materie prime del database)."""
    dati = []
    for r in righe:
        m = db.session.get(MateriaPrima, numero(r.get("materia_prima_id"), intero=True) or 0)
        if m:
            dati.append(m.come_riga_ricetta(numero(r.get("quantita")), r.get("unita")))
    testo = ing.testo_ingredienti(dati)
    return testo, ing.allergeni_presenti(dati)


@bp.route("/lotti/prepara")
def prepara_lotto():
    p = db.session.get(Prodotto, numero(request.args.get("prodotto_id"), intero=True) or 0)
    if not p:
        return errore("Prodotto non trovato.", 404)
    giorno = da_iso(request.args.get("data")) or date.today()
    pezzi = numero(request.args.get("pezzi"), intero=True)
    ricette = [r for r in p.ricette if r.attiva]
    ricetta = None
    if request.args.get("ricetta_id"):
        ricetta = db.session.get(Ricetta, int(request.args["ricetta_id"]))
    ricetta = ricetta or p.ricetta_predefinita
    if pezzi is None and ricetta and ricetta.resa_pezzi:
        pezzi = ricetta.resa_pezzi
    esistenti = [c for (c,) in db.session.query(Lotto.codice).filter(Lotto.codice.like(f"L{giorno:%d%m%y}-%"))]
    righe = righe_da_ricetta(ricetta, pezzi) if ricetta else []
    testo, allergeni = testo_da_righe(righe)
    scad = data_scadenza(giorno, p.durata_giorni)
    return jsonify(ok=True, prodotto={"id": p.id, "nome": p.nome_completo, "sigla": p.sigla,
                                      "tracce": p.tracce or "", "durata_giorni": p.durata_giorni},
                   ricette=[{"id": r.id, "etichetta": r.etichetta, "resa_pezzi": r.resa_pezzi} for r in ricette],
                   ricetta_id=ricetta.id if ricetta else None, pezzi=pezzi, data=giorno.isoformat(),
                   codice=codice_lotto(giorno, p.sigla, esistenti),
                   scadenza=scad.isoformat() if scad else "", righe=righe,
                   ingredienti_testo=testo, ingredienti_html=ing.testo_html(testo),
                   allergeni=allergeni, allergeni_testo=descrivi(allergeni))


@bp.route("/lotti/testo-ingredienti", methods=["POST"])
def testo_ingredienti_lotto():
    """Elenco ingredienti ricalcolato dalle righe del lotto (pulsante "ripristina dalla ricetta")."""
    testo, allergeni = testo_da_righe(dati_richiesta().get("righe") or [])
    return jsonify(ok=True, testo=testo, html=ing.testo_html(testo), allergeni=allergeni,
                   allergeni_testo=descrivi(allergeni))


@bp.route("/lotti/anteprima-testo", methods=["POST"])
def anteprima_testo():
    """Testo con **grassetto** → HTML, per l'anteprima mentre si corregge il testo a mano."""
    return jsonify(ok=True, html=ing.testo_html(dati_richiesta().get("testo") or ""))


# ---------------------------------------------------------------- libro lotti

@bp.route("/lotti")
def lotti():
    f = {k: (request.args.get(k) or "").strip() for k in ("dal", "al", "prodotto", "stato", "q")}
    query = Lotto.query.join(Prodotto)
    if f["dal"]:
        query = query.filter(Lotto.data_produzione >= f["dal"])
    if f["al"]:
        query = query.filter(Lotto.data_produzione <= f["al"])
    if f["prodotto"]:
        query = query.filter(Lotto.prodotto_id == int(f["prodotto"]))
    if f["stato"]:
        query = query.filter(Lotto.stato == f["stato"])
    if f["q"]:
        query = query.filter(db.or_(Lotto.codice.ilike(f"%{f['q']}%"), Prodotto.nome.ilike(f"%{f['q']}%")))
    elenco = query.order_by(Lotto.data_produzione.desc(), Lotto.id.desc()).limit(500).all()
    return render_template("prodotti/lotti.html", lotti=elenco, filtri=f,
                           prodotti=Prodotto.query.order_by(Prodotto.nome).all(), stati=Lotto.STATI,
                           apri_nuovo=request.args.get("nuovo"), **dati_finestra_lotto())


def dati_finestra_lotto():
    """Quello che serve alla finestra "Nuovo lotto" (inclusa nel libro lotti, nella panoramica e nel lotto)."""
    prodotti = Prodotto.query.filter_by(attivo=True).order_by(Prodotto.nome, Prodotto.peso_netto).all()
    recenti_id = [r[0] for r in db.session.query(Lotto.prodotto_id).group_by(Lotto.prodotto_id)
                  .order_by(db.func.max(Lotto.data_produzione).desc()).limit(6)]
    return {"prodotti_lotto": [{"id": p.id, "nome": p.nome_completo, "sigla": p.sigla,
                                "categoria": p.categoria or "", "ha_ricetta": bool(p.ricette),
                                "recente": p.id in recenti_id} for p in prodotti],
            "fornitori": fornitori(), "allergeni": ALLERGENI,
            "materie_lotto": [{"id": m.id, "nome": m.nome} for m in
                              MateriaPrima.query.filter_by(attiva=True).order_by(MateriaPrima.nome)],
            **_dati_modale_prodotto()}


@bp.route("/lotti/<int:id>")
def lotto(id):
    l = db.session.get(Lotto, id)
    if not l:
        return redirect(url_for("prodotti.lotti"))
    storico = Storico.query.filter(
        db.or_(db.and_(Storico.tabella == "lotti", Storico.riga_id == id),
               db.and_(Storico.tabella == "lotti_ingredienti",
                       Storico.riga_id.in_(db.session.query(LottoIngrediente.id).filter_by(lotto_id=id)))
               )).order_by(Storico.id.desc()).all()
    # righe ingredienti cancellate: non sono più nella tabella, si cercano nel JSON dello storico
    cancellate = Storico.query.filter_by(tabella="lotti_ingredienti", azione="cancellazione").all()
    storico += [s for s in cancellate if json.loads(s.prima).get("lotto_id") == id and s not in storico]
    storico.sort(key=lambda s: s.id, reverse=True)
    return render_template("prodotti/lotto.html", l=l, storico=storico, json=json,
                           ingredienti_html=ing.testo_html(l.ingredienti_testo or ""),
                           allergeni_testo=descrivi(l.allergeni_lista), stati=Lotto.STATI,
                           lotto_json=lotto_json(l), **dati_finestra_lotto())


def lotto_json(l):
    return {"id": l.id, "codice": l.codice, "prodotto_id": l.prodotto_id, "ricetta_id": l.ricetta_id,
            "data": l.data_produzione, "scadenza": l.data_scadenza or "", "pezzi": l.pezzi_prodotti,
            "quantita_kg": l.quantita_kg, "ingredienti_testo": l.ingredienti_testo or "", "note": l.note or "",
            "righe": [{"materia_prima_id": r.materia_prima_id, "nome": r.nome, "quantita": r.quantita,
                       "unita": r.unita, "fornitore_id": r.fornitore_id, "fornitore_nome": r.fornitore_nome or "",
                       "lotto_fornitore": r.lotto_fornitore or "", "rif_documento": r.rif_documento or "",
                       "produzione_propria": bool(r.produzione_propria)} for r in l.ingredienti]}


@bp.route("/lotti/salva", methods=["POST"])
@write_required
def salva_lotto():
    d = dati_richiesta()
    p = db.session.get(Prodotto, numero(d.get("prodotto_id"), intero=True) or 0)
    if not p:
        return errore("Scegliere il prodotto.")
    giorno = da_iso(d.get("data"))
    if not giorno:
        return errore("Data di produzione mancante.")
    codice = (d.get("codice") or "").strip().upper()
    if not codice:
        return errore("Codice lotto mancante.")
    l = db.session.get(Lotto, int(d["id"])) if d.get("id") else Lotto(creato_da=utente())
    if l is None:
        return errore("Lotto non trovato.", 404)
    doppio = Lotto.query.filter(Lotto.codice == codice, Lotto.id != (l.id or 0)).first()
    if doppio:
        return errore(f"Il codice {codice} è già usato (lotto di {doppio.prodotto.nome} del "
                      f"{doppio.data_produzione}). Cambiarlo, ad esempio aggiungendo -2.")

    righe_in = [r for r in (d.get("righe") or []) if (r.get("nome") or r.get("materia_prima_id"))]
    righe = []
    for i, r in enumerate(righe_in):
        mp = db.session.get(MateriaPrima, numero(r.get("materia_prima_id"), intero=True) or 0)
        nome = mp.nome if mp else (r.get("nome") or "").strip()
        propria = vero(r.get("produzione_propria"))
        fid = None if propria else numero(r.get("fornitore_id"), intero=True)
        fnome = None if propria else (nome_fornitore(fid) if fid else (r.get("fornitore_nome") or "").strip() or None)
        if not propria and not fid and fnome:                    # fornitore nuovo scritto a mano
            c = crea_fornitore(fnome)
            fid, fnome = c.id, c.name
        righe.append({"materia_prima_id": mp.id if mp else None, "nome": nome,
                      "quantita": numero(r.get("quantita")), "unita": r.get("unita") or (mp.unita if mp else "g"),
                      "fornitore_id": fid, "fornitore_nome": fnome,
                      "lotto_fornitore": (r.get("lotto_fornitore") or "").strip() or None,
                      "rif_documento": (r.get("rif_documento") or "").strip() or None,
                      "produzione_propria": propria, "ordine": i})
    mancanti = [r["nome"] for r in righe if not r["produzione_propria"] and not r["lotto_fornitore"]]

    l.codice, l.prodotto_id = codice, p.id
    l.ricetta_id = numero(d.get("ricetta_id"), intero=True)
    l.data_produzione = giorno.isoformat()
    scad = da_iso(d.get("scadenza"))
    l.data_scadenza = scad.isoformat() if scad else None
    l.pezzi_prodotti = numero(d.get("pezzi"), intero=True)
    l.quantita_kg = numero(d.get("quantita_kg"))
    testo_auto, allergeni = testo_da_righe(righe)
    l.ingredienti_testo = (d.get("ingredienti_testo") or "").strip() or testo_auto
    l.allergeni_lista = allergeni
    if not l.dati_etichetta or vero(d.get("aggiorna_etichetta")):
        l.dati_etichetta = json.dumps(dati_etichetta(p), ensure_ascii=False)
    l.note = (d.get("note") or "").strip() or None
    if l.id:
        l.modificato_da, l.modificato_il = utente(), adesso()
    db.session.add(l)
    db.session.flush()

    # righe ingredienti: si aggiornano al loro posto (così lo storico registra solo i cambiamenti veri)
    esistenti = list(l.ingredienti)
    for i, r in enumerate(righe):
        riga = esistenti[i] if i < len(esistenti) else LottoIngrediente(lotto_id=l.id)
        cambiata = any(getattr(riga, k) != v for k, v in r.items()) if riga.id else True
        if cambiata:
            for k, v in r.items():
                setattr(riga, k, v)
            riga.modificato_da = utente()
            db.session.add(riga)
    for riga in esistenti[len(righe):]:
        riga.modificato_da = utente()
        db.session.flush()
        db.session.delete(riga)
    db.session.commit()
    avviso = None
    if mancanti:
        avviso = "Manca il lotto del fornitore per: " + ", ".join(mancanti) + ". Si può aggiungere dopo."
    return jsonify(ok=True, id=l.id, codice=l.codice, url=url_for("prodotti.lotto", id=l.id), avviso=avviso)


@bp.route("/lotti/<int:id>/stato", methods=["POST"])
@write_required
def stato_lotto(id):
    l = db.session.get(Lotto, id)
    if not l:
        return errore("Lotto non trovato.", 404)
    d = dati_richiesta()
    if d.get("stato") not in Lotto.STATI:
        return errore("Stato non valido.")
    if d["stato"] in ("ritirato", "annullato") and not (d.get("motivo") or "").strip():
        return errore("Per ritiro o annullamento serve il motivo (resta nel registro).")
    l.stato, l.stato_motivo = d["stato"], (d.get("motivo") or "").strip() or None
    l.modificato_da, l.modificato_il = utente(), adesso()
    db.session.commit()
    return jsonify(ok=True)
