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
    riassetto (stesso totale, box diversi) non è un'entrata. Se nello stesso giorno c'è un'entrata registrata,
    conta quella e non il censimento (sono gli stessi capi)."""
    entrate = []
    spostamenti = Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="entrata").all()
    giorni_entrate = {s.data for s in spostamenti}
    for c in censimenti:
        if c.data in giorni_entrate:
            continue
        dopo = {l: 0 for l in (1, 2, 3)}
        for cb in conteggi[c.id]:
            if cb.box_numero in linea_per_box:
                dopo[linea_per_box[cb.box_numero]] += cb.quantita
        prima = _capi_per_linea(live_count(ciclo, al_giorno=c.data - timedelta(days=1)), linea_per_box)
        n = sum(dopo.values()) - sum(prima.values())
        if n > 0:
            entrate.append({"data": c.data.isoformat(), "n": n, "origine": "censimento",
                            "L": {l: max(0, dopo[l] - prima[l]) for l in (1, 2, 3)}})
    for s in spostamenti:
        per_linea = {x: 0 for x in (1, 2, 3)}
        righe = [(r.box_numero, r.capi) for r in s.box_svuotati] or [(s.box_destinazione, s.quantita)]
        tot_righe = sum(n for _, n in righe) or 1
        for box, n in righe:                # i capi del camion divisi tra le linee come i capi dei box
            if box in linea_per_box:
                per_linea[linea_per_box[box]] += round(s.quantita * n / tot_righe)
        entrate.append({"data": s.data.isoformat(), "n": s.quantita, "origine": "entrata", "L": per_linea})
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


def _rapporto_per_giorno(ciclo):
    """{giorno iso: rapporto impostato} dalle ricette lette con ogni linea, solo i giorni in cui è stato
    uguale per tutte le linee lette (per la linea tratteggiata di Analisi, che cambia nel tempo)."""
    from app.models import ImpiantoLinea
    from app.services.impianto import modalita, MANUALE
    if modalita() == MANUALE:
        return {}
    per_giorno = {}
    q = ImpiantoLinea.query.filter(ImpiantoLinea.data >= ciclo.data_inizio, ImpiantoLinea.rapporto.isnot(None))
    if ciclo.data_fine:                     # ciclo chiuso: solo le letture fino alla fine
        q = q.filter(ImpiantoLinea.data <= ciclo.data_fine)
    for l in q.all():
        per_giorno.setdefault(l.data.isoformat(), set()).add(l.rapporto)
    return {d: v.pop() for d, v in per_giorno.items() if len(v) == 1}


def dati_analisi(ciclo):
    from app.services.allevamento_conteggio import live_count as _live_count, LINEA_PER_BOX
    from app.services.allevamento_scorte import get_setting_float, peso_da_giorni

    from app.services.allevamento_conteggio import oggi_del_ciclo
    oggi = oggi_del_ciclo(ciclo)          # ciclo chiuso: le serie si fermano alla data di fine
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

    # un camion da più box (3.0) conta box per box, così ogni linea ha le sue uscite
    uscite = [{"data": s.data.isoformat(), "box": box, "linea": LINEA_PER_BOX.get(box),
               "n": n, "categoria": s.categoria_uscita, "peso": s.peso_medio_kg}
              for s in Spostamento.query.filter_by(ciclo_id=ciclo.id, tipo="uscita").order_by(Spostamento.data).all()
              for box, n in ([(r.box_numero, r.capi) for r in s.box_svuotati] or [(s.box_origine, s.quantita)])]
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
        "rapporto_impostato": None if ciclo.chiuso else _rapporto_impostato(),
        "rapporto_impostato_giorni": _rapporto_per_giorno(ciclo),
        "giorni": giorni,
        "entrate": _entrate(ciclo, censimenti, conteggi, _live_count, LINEA_PER_BOX),
        "uscite": uscite,
        "morti": morti,
        "consegne_siero": consegne_siero,
        "consegne_mangime": consegne_mangime,
    }
