"""Conteggio dei capi per box: struttura della stalla, ultimo censimento ± eventi successivi.

Spostato qui da routes/allevamento.py nella 3.1.4 (prima lo importavano dieci servizi dalle route).
`applica_eventi` è il calcolo puro, provato da tests/test_conteggio.py; `live_count` legge dal
database e lo chiama. Le import di app e modelli sono dentro le funzioni, così il modulo si
importa anche senza l'app (test).
"""
from datetime import date

# Struttura fisica fissa
CAP_PER_BOX = {
    **{i: 1 for i in range(1, 10)},
    **{i: 2 for i in range(10, 16)},
    **{i: 3 for i in range(16, 22)},
    **{i: 4 for i in range(22, 37)},
    **{i: 5 for i in range(37, 43)},
    **{i: 7 for i in range(43, 50)},
    **{i: 6 for i in range(50, 55)},
}
LINEA_PER_BOX = {
    **{i: 1 for i in range(1, 22)},
    **{i: 2 for i in range(22, 37)},
    **{i: 3 for i in range(37, 55)},
}
POSTI_PER_BOX_STANDARD = {
    **{i: 40 for i in range(1, 10)},
    **{i: 26 for i in range(10, 16)},
    **{i: 10 for i in range(16, 22)},
    **{i: 38 for i in range(22, 37)},
    **{i: 38 for i in range(37, 43)},
    **{i: 31 for i in range(43, 49)},
    49: 32,
    50: 47, 51: 47, 52: 46, 53: 45, 54: 45,
}
CAPANNONI = [1, 2, 3, 4, 5, 6, 7]
# categorie delle uscite al macello (Spostamento.categoria_uscita)
CATEGORIE_USCITA = ("fine_ciclo", "scarto_sottopeso", "agriturismo", "venduti_agriturismo")
BOX_PER_CAP = {
    1: list(range(1, 10)), 2: list(range(10, 16)), 3: list(range(16, 22)),
    4: list(range(22, 37)), 5: list(range(37, 43)), 7: list(range(43, 50)),
    6: list(range(50, 55)),
}
POSTI_PER_CAP = {cap: sum(POSTI_PER_BOX_STANDARD[b] for b in boxes) for cap, boxes in BOX_PER_CAP.items()}
BOX = range(1, 55)


def ciclo_attivo():
    from app.models import Ciclo
    return Ciclo.query.filter_by(attivo=True).order_by(Ciclo.data_inizio.desc()).first()


def ciclo_in_avvio():
    """Il ciclo nuovo aperto mentre il vecchio è ancora attivo (3.5.0, cicli accavallati), o None."""
    from app.models import Ciclo
    return Ciclo.query.filter_by(in_avvio=True).order_by(Ciclo.data_inizio.desc()).first()


def cicli_in_corso():
    """Ciclo attivo e ciclo in avvio (di norma solo il primo)."""
    return [c for c in (ciclo_attivo(), ciclo_in_avvio()) if c]


def avviso_ciclo_in_avvio(ciclo, box=None, cap=None, caps=None):
    """Per il bot (3.5.0): con un ciclo in avvio, un evento registrato sul ciclo attivo in un box (o capannone)
    senza capi del ciclo attivo è probabilmente dei piccoli. Testo dell'avviso o None."""
    nuovo = ciclo_in_avvio()
    if not nuovo or not ciclo:
        return None
    live = live_count(ciclo)
    if box:
        if live.get(box, 0) > 0:
            return None
        dove = f"Il box {box}"
    else:
        capannoni = [cap] if cap else list(caps or [])
        if not capannoni or any(live.get(b, 0) > 0 for c in capannoni for b in BOX_PER_CAP.get(c, [])):
            return None
        dove = f"Il CAP {capannoni[0]}" if len(capannoni) == 1 else "Questi capannoni"
    return (f"⚠️ {dove} non ha capi nel ciclo attivo «{ciclo.nome}». Se è del ciclo nuovo «{nuovo.nome}», "
            f"elimina questa registrazione e inseriscila dal gestionale scegliendo quel ciclo.")


CHIAVE_SESSIONE_CICLO = "allevamento_ciclo"


def ciclo_scelto():
    """Il ciclo su cui lavorano le pagine dell'allevamento: quello del modulo (campo nascosto ciclo_id,
    aggiunto a ogni modulo della pagina, così due schede aperte su cicli diversi non si confondono),
    poi ?ciclo=<id> (che lo ricorda per l'utente), poi quello ricordato, altrimenti il ciclo attivo.
    Per ora solo cicli in corso (attivo o in avvio). Bot, impianto e avvisi usano sempre ciclo_attivo()."""
    from flask import has_request_context, request, session
    from app import db
    from app.models import Ciclo
    if not has_request_context():
        return ciclo_attivo()
    cid = request.form.get("ciclo_id", type=int) if request.method == "POST" else None
    if cid is None:
        cid = request.args.get("ciclo", type=int)
        if cid is not None:
            session[CHIAVE_SESSIONE_CICLO] = cid
    if cid is None:
        cid = session.get(CHIAVE_SESSIONE_CICLO)
    if cid is not None:
        c = db.session.get(Ciclo, cid)
        if c and (c.attivo or c.in_avvio):
            return c
    return ciclo_attivo()


# Fino alla 3.0.3 tutti gli eventi del giorno del censimento si applicavano dopo il censimento,
# anche quelli registrati prima: il censimento del 16/11/2026, fatto alle 14:39 con il box 5 già
# senza il morto del mattino, lo ha fatto togliere due volte. Da questa data conta l'ora di
# registrazione; per i censimenti precedenti (ricostruiti a posteriori) resta la regola vecchia,
# così i conti dei giorni passati non cambiano.
REGOLA_ORA_CENSIMENTO_DAL = date(2026, 11, 16)


def eventi_dopo_censimento(modello, cens):
    """Condizione per i decessi o gli spostamenti (modello) da applicare a un censimento:
    quelli dei giorni successivi e, nel giorno del censimento, solo quelli registrati dopo
    averlo salvato — quelli registrati prima sono già dentro i capi contati."""
    from app import db
    if cens.data < REGOLA_ORA_CENSIMENTO_DAL or cens.created_at is None:
        if hasattr(modello, "tipo"):
            # entrate dello stesso giorno di un censimento vecchio: il censimento d'arrivo le contiene già
            # (3.1.1: entrate del ciclo 05/2026 registrate dopo, con la data dei censimenti d'arrivo)
            return db.or_(modello.data > cens.data, db.and_(modello.data == cens.data, modello.tipo != "entrata"))
        return modello.data >= cens.data
    return db.or_(modello.data > cens.data,
                  db.and_(modello.data == cens.data, modello.created_at > cens.created_at))


def applica_eventi(conteggi, morti, spostamenti):
    """Capi per box (1–54) dai capi del censimento {box: capi} e dagli eventi successivi.

    morti: oggetti con box_numero (o None), capannone_numero, quantita.
    spostamenti: oggetti con tipo, box_origine, box_destinazione, quantita, box_svuotati (righe con
    box_numero e capi, per i camion su più box).

    Decessi e spostamenti si sommano senza fermarsi a zero a metà strada: l'ordine in cui si
    applicano non deve contare (prima si applicavano tutti i decessi e poi gli spostamenti, e un
    box che scendeva sotto zero perdeva il decesso: 12/10 box 16 contato 3 invece di 2).
    Lo zero si applica solo al risultato finale."""
    count = {b: 0 for b in BOX}
    count.update(conteggi)

    for m in morti:
        if m.box_numero:
            count[m.box_numero] = count.get(m.box_numero, 0) - m.quantita
        else:
            boxes_cap = BOX_PER_CAP.get(m.capannone_numero, [])
            if boxes_cap:
                per_box = m.quantita // len(boxes_cap)
                resto = m.quantita % len(boxes_cap)
                for i, b in enumerate(boxes_cap):
                    sottrai = per_box + (1 if i < resto else 0)
                    count[b] = count.get(b, 0) - sottrai

    for s in spostamenti:
        if s.tipo == "interno":
            if s.box_origine:
                count[s.box_origine] = count.get(s.box_origine, 0) - s.quantita
            if s.box_destinazione:
                count[s.box_destinazione] = count.get(s.box_destinazione, 0) + s.quantita
        elif s.tipo == "entrata":
            if s.box_svuotati:      # camion di suinetti in più box (3.1.1): i capi di ogni box in spostamenti_box
                for r in s.box_svuotati:
                    count[r.box_numero] = count.get(r.box_numero, 0) + r.capi
            elif s.box_destinazione:
                count[s.box_destinazione] = count.get(s.box_destinazione, 0) + s.quantita
        elif s.tipo == "uscita":
            if s.box_svuotati:      # camion da più box (3.0): i capi tolti da ogni box sono in spostamenti_box
                for r in s.box_svuotati:
                    count[r.box_numero] = count.get(r.box_numero, 0) - r.capi
            elif s.box_origine:
                count[s.box_origine] = count.get(s.box_origine, 0) - s.quantita

    return {b: max(0, n) for b, n in count.items()}


def live_count(ciclo, al_giorno=None):
    """Capi per box: ultimo censimento ± mortalità e spostamenti successivi
    (vedi eventi_dopo_censimento per quelli del giorno stesso).
    Con al_giorno ricostruisce la situazione a quella data (censimento e
    eventi fino a quel giorno incluso), altrimenti ad adesso."""
    from app.models import Censimento, EventoMortalita, Spostamento
    q_cens = Censimento.query.filter_by(ciclo_id=ciclo.id)
    if al_giorno:
        q_cens = q_cens.filter(Censimento.data <= al_giorno)
    ultimo = q_cens.order_by(Censimento.data.desc(), Censimento.id.desc()).first()
    if not ultimo:
        return {b: 0 for b in BOX}

    morti = EventoMortalita.query.filter(
        EventoMortalita.ciclo_id == ciclo.id,
        eventi_dopo_censimento(EventoMortalita, ultimo),
        *([EventoMortalita.data <= al_giorno] if al_giorno else []),
    ).all()
    spostamenti = Spostamento.query.filter(
        Spostamento.ciclo_id == ciclo.id,
        eventi_dopo_censimento(Spostamento, ultimo),
        *([Spostamento.data <= al_giorno] if al_giorno else []),
    ).all()
    return applica_eventi({cb.box_numero: cb.quantita for cb in ultimo.conteggi.all()}, morti, spostamenti)
