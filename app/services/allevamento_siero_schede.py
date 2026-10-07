"""Schede «Brix del siero» e «Sostituzione con siero» della pagina Alimentazione.

- Valore attuale: con il collegamento all'impianto attivo, quello impostato sul PC (impianto_parametri,
  % del siero della ricetta in uso da impianto_ricetta), con l'ora dell'ultima lettura e dell'ultimo
  cambio; in manuale, il Brix del carico in uso e la sostituzione dell'ultimo giorno con consumi.
- Grafico degli ultimi 15 giorni: i valori applicati davvero, dai consumi registrati (Brix di
  riferimento pesato sul siero di ogni pasto; sostituzione = s.s. del siero sulla s.s. totale).
"""
import json
from datetime import timedelta

from app import db


def _json(chiave):
    from app.models import Setting
    s = db.session.get(Setting, chiave)
    try:
        return json.loads(s.value) if s and s.value else None
    except ValueError:
        return s.value if s else None


def serie_giornaliere(ciclo, oggi, giorni=15, perc_ss_mangime=100):
    from app.models import UsoPasto
    dal = oggi - timedelta(days=giorni - 1)
    per_giorno = {}
    for p in UsoPasto.query.filter(UsoPasto.ciclo_id == ciclo.id, UsoPasto.data >= dal, UsoPasto.data <= oggi).all():
        d = per_giorno.setdefault(p.data, {"siero": 0.0, "siero_brix": 0.0, "ss_siero": 0.0, "ss_farina": 0.0})
        brix = p.perc_ss_siero_rif or 0
        d["siero"] += p.siero_qli or 0
        d["siero_brix"] += (p.siero_qli or 0) * brix
        d["ss_siero"] += (p.siero_qli or 0) * brix / 100
        d["ss_farina"] += (p.mangime_qli or 0) * perc_ss_mangime / 100
    serie = []
    for i in range(giorni):
        g = dal + timedelta(days=i)
        d = per_giorno.get(g)
        brix = d["siero_brix"] / d["siero"] if d and d["siero"] else None
        tot = (d["ss_siero"] + d["ss_farina"]) if d else 0
        sost = d["ss_siero"] / tot * 100 if d and tot else None
        serie.append({"data": g.isoformat(), "brix": round(brix, 2) if brix is not None else None,
                      "sost": round(sost, 1) if sost is not None else None})
    return serie


def schede(ciclo, oggi, collegato, brix_carico, perc_ss_mangime=100):
    """Dati per le due schede: valori attuali, provenienza, orari e serie dei 15 giorni."""
    from app.models import ImpiantoEvento
    serie = serie_giornaliere(ciclo, oggi, perc_ss_mangime=perc_ss_mangime) if ciclo else []
    out = {"serie": serie, "collegato": collegato, "brix": None, "sost": None, "ricetta": None,
           "letto_il": None, "cambiato_il": None}
    par = _json("impianto_parametri") if collegato else None
    if par:
        ricetta = (_json("impianto_ricetta") or {}).get("nome")
        siero = par.get("siero") or {}
        if ricetta not in siero and siero:      # ricetta in uso non nota: quella con più siero
            ricetta = max(siero, key=siero.get)
        out.update(brix=par.get("brix"), sost=siero.get(ricetta), ricetta=ricetta, letto_il=_json("impianto_parametri_letto"))
        ultimo = ImpiantoEvento.query.filter_by(tipo="parametri_cambiati").order_by(ImpiantoEvento.istante.desc()).first()
        out["cambiato_il"] = ultimo.istante.isoformat(timespec="minutes") if ultimo else None
    else:
        out["brix"] = brix_carico
        ultimi = [v["sost"] for v in serie if v["sost"] is not None]
        out["sost"] = ultimi[-1] if ultimi else None
    return out
