"""Dati per la pagina Analisi dell'allevamento.

Prepara le serie giornaliere grezze del ciclo (capi, età e peso stimati per
linea, pasti con Brix del siero) più entrate di animali, mortalità, uscite e
consegne. Aggregazioni,
filtri (periodo, linea, per capo/totali) e grafici si calcolano nel browser,
così cambiare filtro non richiede di ricaricare la pagina.
"""
from datetime import date, timedelta

from app.models import UsoPasto, EventoMortalita, ConsegnaSiero, ConsegnaMangime, Censimento, Spostamento


def _capi_per_linea(conteggio, linea_per_box):
    capi = {l: 0 for l in (1, 2, 3)}
    for box, n in conteggio.items():
        if box in linea_per_box:
            capi[linea_per_box[box]] += n
    return capi


def _entrate(ciclo, censimenti, conteggi, live_count, linea_per_box):
    """Animali entrati: i censimenti che aumentano i capi rispetto al giorno prima (consegne di
    suinetti registrate con un censimento) più gli spostamenti di tipo entrata. Un censimento di
    riassetto (stesso totale, box diversi) non è un'entrata."""
    entrate = []
    for c in censimenti:
        dopo = {l: 0 for l in (1, 2, 3)}
        for cb in conteggi[c.id]:
            if cb.box_numero in linea_per_box:
                dopo[linea_per_box[cb.box_numero]] += cb.quantita
        prima = _capi_per_linea(live_count(ciclo, al_giorno=c.data - timedelta(days=1)), linea_per_box)
        n = sum(dopo.values()) - sum(prima.values())
        if n > 0:
            entrate.append({"data": c.data.isoformat(), "n": n, "origine": "censimento",
                            "L": {l: max(0, dopo[l] - prima[l]) for l in (1, 2, 3)}})
    for s in Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="entrata").all():
        l = linea_per_box.get(s.box_destinazione)
        entrate.append({"data": s.data.isoformat(), "n": s.quantita, "origine": "entrata",
                        "L": {x: (s.quantita if x == l else 0) for x in (1, 2, 3)}})
    return sorted(entrate, key=lambda e: e["data"])


def _rapporto_impostato():
    """Rapporto di diluizione impostato sul PC per la ricetta in uso (solo con il collegamento attivo)."""
    import json
    from app import db
    from app.models import Setting
    from app.services.impianto import modalita, MANUALE
    if modalita() == MANUALE:
        return None
    r = db.session.get(Setting, "impianto_ricetta")
    return (json.loads(r.value) if r and r.value else {}).get("rapporto")


def dati_analisi(ciclo):
    from app.routes.allevamento import _live_count, LINEA_PER_BOX
    from app.services.allevamento_scorte import get_setting_float, peso_da_giorni

    oggi = date.today()
    censimenti = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(Censimento.data, Censimento.id).all()
    conteggi = {c.id: c.conteggi.all() for c in censimenti}

    pasti_per_giorno = {}
    for p in UsoPasto.query.filter_by(ciclo_id=ciclo.id).all():
        pasti_per_giorno.setdefault(p.data, {}).setdefault(p.linea, []).append({
            "pasto": p.pasto, "mang": p.mangime_qli, "siero": p.siero_qli, "acqua": p.acqua_qli,
            "brix": p.perc_ss_siero_rif, "stimato": bool(p.stimato),
        })

    # prima dei censimenti non ci sono capi, quindi niente dati per capo: si parte dal primo
    inizio = censimenti[0].data if censimenti else ciclo.data_inizio
    giorni = []
    d = inizio
    while d <= oggi:
        capi = {l: 0 for l in (1, 2, 3)}
        for box, n in _live_count(ciclo, al_giorno=d).items():
            if box in LINEA_PER_BOX:
                capi[LINEA_PER_BOX[box]] += n

        # età media per linea: dall'ultimo censimento fino a d, proiettata a d
        eta = {}
        ultimi = [c for c in censimenti if c.data <= d]
        if ultimi:
            u = ultimi[-1]
            somma = {l: [0, 0] for l in (1, 2, 3)}
            for cb in conteggi[u.id]:
                l = LINEA_PER_BOX.get(cb.box_numero)
                if l and cb.giorni_vita is not None and cb.quantita:
                    somma[l][0] += (cb.giorni_vita + (d - u.data).days) * cb.quantita
                    somma[l][1] += cb.quantita
            eta = {l: round(s / n, 1) for l, (s, n) in somma.items() if n}
        peso = {}
        for l, e in eta.items():
            p = peso_da_giorni(e)
            if p is not None:
                peso[l] = round(p, 1)

        giorni.append({"data": d.isoformat(), "capi": capi, "eta": eta, "peso": peso,
                       "pasti": pasti_per_giorno.get(d, {})})
        d += timedelta(days=1)

    uscite = [{"data": s.data.isoformat(), "box": s.box_origine, "linea": LINEA_PER_BOX.get(s.box_origine),
               "n": s.quantita, "categoria": s.categoria_uscita, "peso": s.peso_medio_kg}
              for s in Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="uscita").order_by(Spostamento.data).all()]
    morti = [{"data": m.data.isoformat(), "cap": m.capannone_numero, "box": m.box_numero,
              "n": m.quantita, "causa": m.causa or ""}
             for m in EventoMortalita.query.filter_by(ciclo_id=ciclo.id).order_by(EventoMortalita.data).all()]
    consegne_siero = [{"data": c.data.isoformat(), "q": c.quantita_qli, "brix": c.perc_sostanza_secca,
                       "speditore": c.speditore_rel.etichetta if c.speditore_rel else None}
                      for c in ConsegnaSiero.query.filter_by(ciclo_id=ciclo.id).order_by(ConsegnaSiero.data).all()]
    consegne_mangime = [{"data": c.data.isoformat(), "q": c.quantita_qli, "tipo": c.tipo_mangime}
                        for c in ConsegnaMangime.query.filter_by(ciclo_id=ciclo.id).order_by(ConsegnaMangime.data).all()]

    return {
        "ciclo": {"nome": ciclo.nome, "inizio": ciclo.data_inizio.isoformat()},
        "oggi": oggi.isoformat(),
        "perc_ss_mangime": get_setting_float("allevamento_perc_ss_mangime") or 100,
        "rapporto_impostato": _rapporto_impostato(),
        "giorni": giorni,
        "entrate": _entrate(ciclo, censimenti, conteggi, _live_count, LINEA_PER_BOX),
        "uscite": uscite,
        "morti": morti,
        "consegne_siero": consegne_siero,
        "consegne_mangime": consegne_mangime,
    }
