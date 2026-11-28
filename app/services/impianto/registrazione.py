"""Dalle letture dell'impianto ai consumi del gestionale.

- salva_lettura_linea: memorizza i quantitativi letti per una linea (ImpiantoLinea, stato "proposta").
- registra: li scrive in uso_pasti come dato reale (fonte "impianto"), usando la stessa funzione
  dell'inserimento a mano (registra_pasto: % sostituzione e stime dei pasti successivi).
  - in automatico (sovrascrivi_manuali=False) un pasto già inserito a mano non viene toccato: vale
    la correzione dell'utente, la lettura resta proposta con una nota;
  - con l'approvazione esplicita (modalità con verifica) la lettura sostituisce quanto c'è.
- Si registra sempre l'orario effettivo del pasto (inizio della linea 1): serve a scalare il siero dal
  carico giusto anche quando gli orari standard cambiano dopo (seguono quelli del PC). Inizio del pasto = inizio della linea 1
  (le linee successive partono normalmente 20-40 minuti dopo); sconosciuto se il servizio ha
  agganciato il pasto già in corso.
- Quantitativi arrotondati a 2 decimali di quintale, come nell'inserimento a mano. Siero sotto 0,15 q
  su una linea = non erogato, spostato nell'acqua (normalizza_siero).
- Il numero del pasto (1-3) è la posizione dell'orario tra quelli impostati sull'impianto: un pasto
  rinviato (es. 14:39 invece di 12:50) resta il pasto 2; un pasto anticipato fino a un'ora (orario spostato
  sul PC mentre parte, es. 13:05 con 13:10 in memoria) resta il suo (3.1.3).
- Cicli accavallati (3.5.0): una lettura va al ciclo attivo, salvo che sia stata spostata su un ciclo in
  avvio (sposta: pulsante «Sposta sul ciclo nuovo», per i pasti dei piccoli, che mangiano prima dei
  grandi con una ricetta e un orario loro). Due letture dello stesso pasto e linea dello stesso ciclo si
  sommano: il pasto di ogni ciclo si ricalcola dalle sue letture. Orario effettivo e siero vengono solo
  dalle letture del ciclo attivo.
"""
from datetime import datetime, timedelta

from app import db



def normalizza_siero(reale):
    """Siero sotto SIERO_MINIMO_Q su una linea = non erogato (residuo a cisterna vuota): va nell'acqua."""
    from app.services.allevamento_scorte import SIERO_MINIMO_Q
    r = dict(reale)
    if r.get("siero") is not None and 0 < r["siero"] < SIERO_MINIMO_Q:
        r["acqua"] = round((r.get("acqua") or 0) + r["siero"], 4)
        r["siero"] = 0.0
    return r


# orari più vicini di così sono lo stesso pasto diviso (27/10: 11:55 linea 1, 13:00 linee 2-3); 120 dalla 3.5.0:
# con i cicli accavallati il pasto dei piccoli parte prima di quello dei grandi e il PC impiega circa un'ora
MINUTI_STESSO_PASTO = 120


def gruppi_orari(orari_impianto):
    """Orari del PC raggruppati per pasto: quelli a meno di MINUTI_STESSO_PASTO dal precedente sono lo stesso
    pasto dato in due volte (es. una linea con il siero rimasto del carico vecchio, le altre dopo lo scarico)."""
    gruppi = []
    for o in sorted(orari_impianto or []):
        m = o.hour * 60 + o.minute
        if gruppi and m - (gruppi[-1][-1].hour * 60 + gruppi[-1][-1].minute) < MINUTI_STESSO_PASTO:
            gruppi[-1].append(o)
        else:
            gruppi.append([o])
    return gruppi


MINUTI_ANTICIPO = 60        # un pasto può partire fino a un'ora prima dell'orario che il servizio ha in memoria


def numero_pasto(orario, orari_impianto):
    """Numero del pasto (1-3): quanti pasti del PC sono già cominciati all'orario letto sullo schermo, contando
    anche quelli impostati fino a MINUTI_ANTICIPO dopo. L'orario sul PC può cambiare mentre il pasto parte e il
    servizio rilegge gli orari ogni 10 minuti: il 17/11/2026 il pasto delle 13:05 è stato letto con gli orari
    07:55, 13:10, 17:30 in memoria e senza tolleranza era diventato il pasto 1 (sovrascrivendo quello delle 7:55).
    Un pasto rinviato (14:39 invece di 12:50) resta il pasto 2."""
    if not orari_impianto:
        return None
    minuti = lambda t: t.hour * 60 + t.minute
    n = sum(1 for g in gruppi_orari(orari_impianto) if minuti(g[0]) <= minuti(orario) + MINUTI_ANTICIPO)
    return max(1, min(3, n))


def salva_lettura_linea(data, evento, orari_impianto, inizio=None):
    """Crea o aggiorna la lettura di una linea da un evento linea_conclusa."""
    from app.models import ImpiantoLinea
    r, t = evento.dati["reale"], evento.dati["teorico"]
    l = ImpiantoLinea.query.filter_by(data=data, orario_pasto=evento.pasto, linea=evento.linea).first()
    if l is None:
        l = ImpiantoLinea(data=data, orario_pasto=evento.pasto, linea=evento.linea, stato="proposta")
        db.session.add(l)
    elif l.stato in ("registrata", "approvata"):
        return l          # già nel gestionale: una seconda lettura non cambia niente
    l.pasto = numero_pasto(evento.pasto, orari_impianto)
    q = lambda v: None if v is None else round(v, 2)
    l.acqua_qli, l.siero_qli, l.farina_qli, l.totale_qli = q(r["acqua"]), q(r["siero"]), q(r["farina"]), q(r["totale"])
    l.acqua_teorica_qli, l.siero_teorico_qli, l.farina_teorica_qli = q(t.get("acqua")), q(t.get("siero")), q(t.get("farina"))
    l.conferme, l.confermato = evento.dati["conferme"], evento.dati["confermato"]
    l.inizio, l.fine = inizio, evento.istante
    return l


def _ciclo_della_lettura(lettura):
    from app.models import Ciclo
    from app.services.allevamento_conteggio import ciclo_attivo as _get_ciclo_attivo
    return db.session.get(Ciclo, lettura.ciclo_id) if lettura.ciclo_id else _get_ciclo_attivo()


def _letture_del_pasto(data, pasto, linea, ciclo_id, escludi_id=None):
    """Letture già nel gestionale (registrate o approvate) di quel pasto e linea per quel ciclo
    (ciclo_id None = ciclo attivo)."""
    from app.models import ImpiantoLinea
    q = ImpiantoLinea.query.filter(ImpiantoLinea.data == data, ImpiantoLinea.pasto == pasto,
                                   ImpiantoLinea.linea == linea,
                                   ImpiantoLinea.stato.in_(("registrata", "approvata")))
    q = q.filter(ImpiantoLinea.ciclo_id.is_(None) if ciclo_id is None else ImpiantoLinea.ciclo_id == ciclo_id)
    if escludi_id is not None:
        q = q.filter(ImpiantoLinea.id != escludi_id)
    return q.order_by(ImpiantoLinea.orario_pasto).all()


def _somma(letture, campo):
    valori = [getattr(l, campo) for l in letture if getattr(l, campo) is not None]
    return round(sum(valori), 2) if valori else None


def _scrivi_pasto(ciclo, data, pasto, linea, letture, nota_extra=""):
    """Scrive in uso_pasti il pasto di un ciclo come somma delle sue letture del PC."""
    from app.services.allevamento_pasti import registra_pasto
    riga = registra_pasto(ciclo_id=ciclo.id, data=data, pasto=pasto, linea=linea,
                          mangime_qli=_somma(letture, "farina_qli"), siero_qli=_somma(letture, "siero_qli"),
                          acqua_qli=_somma(letture, "acqua_qli"))
    riga.fonte = "impianto"
    orari = ", ".join(f"{l.orario_pasto:%H:%M}" for l in letture)
    riga.note = (f"Letto dal PC di alimentazione (pasto delle {orari}" +
                 (f", {letture[-1].conferme} letture concordi" if len(letture) == 1 else ", somma delle letture") +
                 ")" + nota_extra)
    db.session.flush()
    for l in letture:
        l.uso_pasto_id = riga.id
    return riga


def _aggiorna_orario_effettivo(data, pasto):
    """Orario effettivo del pasto dall'inizio della linea 1 delle letture del ciclo attivo (le letture
    spostate su un ciclo in avvio non contano). Si scrive una volta; se era stato preso da una lettura poi
    spostata si ricalcola, e si toglie se non resta nessuna lettura del ciclo attivo."""
    from app.models import ImpiantoLinea, OrarioPastoEffettivo
    from app.services.allevamento_scorte import invalida_orari_effettivi
    inizi = [l.inizio for l in ImpiantoLinea.query.filter(
        ImpiantoLinea.data == data, ImpiantoLinea.pasto == pasto, ImpiantoLinea.linea == 1,
        ImpiantoLinea.ciclo_id.is_(None), ImpiantoLinea.inizio.isnot(None),
        ImpiantoLinea.stato.in_(("registrata", "approvata"))).all()]
    ora = min(inizi).replace(second=0, microsecond=0).time() if inizi else None
    ope = OrarioPastoEffettivo.query.filter_by(data=data, pasto=pasto).first()
    if ope is None:
        if ora:
            db.session.add(OrarioPastoEffettivo(data=data, pasto=pasto, ora=ora, operatore="impianto"))
            invalida_orari_effettivi()
    elif ope.operatore == "impianto" and ope.ora != ora:
        if ora:
            ope.ora = ora
        else:
            db.session.delete(ope)
        invalida_orari_effettivi()


def registra(lettura, operatore="impianto", sovrascrivi_manuali=False):
    """Scrive la lettura in uso_pasti (con le altre letture dello stesso pasto, linea e ciclo).
    Restituisce la riga UsoPasto, o None se non scritta."""
    from app.models import UsoPasto

    ciclo = _ciclo_della_lettura(lettura)
    if not ciclo or not lettura.pasto:
        lettura.note = "Non registrata: nessun ciclo attivo o numero del pasto sconosciuto."
        return None
    esistente = UsoPasto.query.filter_by(ciclo_id=ciclo.id, data=lettura.data, pasto=lettura.pasto,
                                         linea=lettura.linea).first()
    if (esistente and not esistente.stimato and esistente.fonte != "impianto" and not sovrascrivi_manuali):
        lettura.note = "Pasto già inserito a mano: vale il dato inserito, lettura lasciata come proposta."
        return None

    letture = _letture_del_pasto(lettura.data, lettura.pasto, lettura.linea, lettura.ciclo_id,
                                 escludi_id=lettura.id) + [lettura]
    letture.sort(key=lambda l: l.orario_pasto)
    riga = _scrivi_pasto(ciclo, lettura.data, lettura.pasto, lettura.linea, letture,
                         "" if operatore == "impianto" else f", approvato da {operatore}")
    lettura.stato = "registrata" if operatore == "impianto" else "approvata"
    lettura.decisa_da = operatore
    lettura.decisa_il = datetime.utcnow()

    # orario effettivo del pasto (inizio della linea 1), una volta per pasto. Con il collegamento attivo
    # si registra sempre: gli orari standard seguono quelli del PC e cambiano quando un pasto viene spostato,
    # quindi solo l'orario effettivo conserva l'ora vera dei pasti già fatti (serve all'attribuzione del siero).
    if lettura.ciclo_id is None:
        _aggiorna_orario_effettivo(lettura.data, lettura.pasto)
    return riga


def _ricalcola_pasto(ciclo, ciclo_id, data, pasto, linea):
    """Riscrive il pasto di un ciclo dalle letture rimaste; se non ne resta nessuna toglie la riga letta dal
    PC (un pasto inserito a mano resta)."""
    from app.models import UsoPasto, ImpiantoLinea
    letture = _letture_del_pasto(data, pasto, linea, ciclo_id)
    if letture:
        return _scrivi_pasto(ciclo, data, pasto, linea, letture)
    riga = UsoPasto.query.filter_by(ciclo_id=ciclo.id, data=data, pasto=pasto, linea=linea).first()
    if riga and riga.fonte == "impianto":
        ImpiantoLinea.query.filter_by(uso_pasto_id=riga.id).update({"uso_pasto_id": None})
        db.session.delete(riga)
    return None


def sposta(lettura, ciclo_destinazione, operatore):
    """Sposta una lettura del PC su un ciclo in avvio (ciclo_destinazione) o la riporta sul ciclo attivo
    (ciclo_destinazione None). Se era già nel gestionale riscrive il pasto di tutti e due i cicli."""
    from app.services.allevamento_conteggio import ciclo_attivo as _get_ciclo_attivo
    from app.services.allevamento_pasti import dopo_modifica_carichi_siero
    from app.services.allevamento_scorte import invalida_attribuzione_siero
    attivo = _get_ciclo_attivo()
    if ciclo_destinazione is not None and not ciclo_destinazione.in_avvio:
        raise ValueError("Si può spostare una lettura solo su un ciclo in avvio.")
    if not lettura.pasto:
        raise ValueError("Numero del pasto sconosciuto.")
    nuovo_id = ciclo_destinazione.id if ciclo_destinazione is not None else None
    if lettura.ciclo_id == nuovo_id:
        return
    vecchio_id = lettura.ciclo_id
    ciclo_vecchio = _ciclo_della_lettura(lettura)
    lettura.ciclo_id = nuovo_id
    ciclo_nuovo = ciclo_destinazione or attivo
    if lettura.stato in ("registrata", "approvata"):
        if ciclo_vecchio:
            _ricalcola_pasto(ciclo_vecchio, vecchio_id, lettura.data, lettura.pasto, lettura.linea)
        if ciclo_nuovo:
            _ricalcola_pasto(ciclo_nuovo, nuovo_id, lettura.data, lettura.pasto, lettura.linea)
        _aggiorna_orario_effettivo(lettura.data, lettura.pasto)
    nome = ciclo_nuovo.nome if ciclo_nuovo else "ciclo attivo"
    lettura.note = f"Spostata su «{nome}» da {operatore} il {datetime.now():%d/%m %H:%M}."
    db.session.flush()
    invalida_attribuzione_siero()
    dopo_modifica_carichi_siero()


def scarta(lettura, operatore):
    lettura.stato = "scartata"
    lettura.decisa_da = operatore
    lettura.decisa_il = datetime.utcnow()
