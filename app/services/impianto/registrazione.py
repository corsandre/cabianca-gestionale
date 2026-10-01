"""Dalle letture dell'impianto ai consumi del gestionale.

- salva_lettura_linea: memorizza i quantitativi letti per una linea (ImpiantoLinea, stato "proposta").
- registra: li scrive in uso_pasti come dato reale (fonte "impianto"), usando la stessa funzione
  dell'inserimento a mano (registra_pasto: % sostituzione e stime dei pasti successivi).
  - in automatico (sovrascrivi_manuali=False) un pasto già inserito a mano non viene toccato: vale
    la correzione dell'utente, la lettura resta proposta con una nota;
  - con l'approvazione esplicita (modalità con verifica) la lettura sostituisce quanto c'è.
- Se il pasto è partito più di 15 minuti dopo l'orario standard del gestionale, si registra anche
  l'orario effettivo (serve a scalare il siero dal carico giusto).
- Il numero del pasto (1-3) è la posizione dell'orario tra quelli impostati sull'impianto: un pasto
  rinviato (es. 14:39 invece di 12:50) resta il pasto 2.
"""
from datetime import datetime, timedelta

from app import db

MINUTI_ORARIO_EFFETTIVO = 15


def numero_pasto(orario, orari_impianto):
    if not orari_impianto:
        return None
    n = sum(1 for o in sorted(orari_impianto) if o <= orario)
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
    l.acqua_qli, l.siero_qli, l.farina_qli, l.totale_qli = r["acqua"], r["siero"], r["farina"], r["totale"]
    l.acqua_teorica_qli, l.siero_teorico_qli, l.farina_teorica_qli = t.get("acqua"), t.get("siero"), t.get("farina")
    l.conferme, l.confermato = evento.dati["conferme"], evento.dati["confermato"]
    l.inizio, l.fine = inizio, evento.istante
    return l


def registra(lettura, operatore="impianto", sovrascrivi_manuali=False):
    """Scrive la lettura in uso_pasti. Restituisce la riga UsoPasto, o None se non scritta."""
    from app.models import UsoPasto, OrarioPastoEffettivo
    from app.routes.allevamento import _get_ciclo_attivo
    from app.services.allevamento_pasti import registra_pasto
    from app.services.allevamento_scorte import orario_pasto, invalida_orari_effettivi

    ciclo = _get_ciclo_attivo()
    if not ciclo or not lettura.pasto:
        lettura.note = "Non registrata: nessun ciclo attivo o numero del pasto sconosciuto."
        return None
    esistente = UsoPasto.query.filter_by(ciclo_id=ciclo.id, data=lettura.data, pasto=lettura.pasto,
                                         linea=lettura.linea).first()
    if (esistente and not esistente.stimato and esistente.fonte != "impianto" and not sovrascrivi_manuali):
        lettura.note = "Pasto già inserito a mano: vale il dato inserito, lettura lasciata come proposta."
        return None

    riga = registra_pasto(ciclo_id=ciclo.id, data=lettura.data, pasto=lettura.pasto, linea=lettura.linea,
                          mangime_qli=lettura.farina_qli, siero_qli=lettura.siero_qli,
                          acqua_qli=lettura.acqua_qli)
    riga.fonte = "impianto"
    riga.note = (f"Letto dal PC di alimentazione (pasto delle {lettura.orario_pasto:%H:%M}, "
                 f"{lettura.conferme} letture concordi)" + ("" if operatore == "impianto" else f", approvato da {operatore}"))
    db.session.flush()
    lettura.uso_pasto_id = riga.id
    lettura.stato = "registrata" if operatore == "impianto" else "approvata"
    lettura.decisa_da = operatore
    lettura.decisa_il = datetime.utcnow()

    # pasto partito molto dopo l'orario standard → orario effettivo (una volta per pasto)
    standard = orario_pasto(lettura.pasto)
    if lettura.inizio and standard:
        scarto = abs((lettura.inizio - datetime.combine(lettura.data, standard)).total_seconds()) / 60
        if scarto > MINUTI_ORARIO_EFFETTIVO and not OrarioPastoEffettivo.query.filter_by(
                data=lettura.data, pasto=lettura.pasto).first():
            db.session.add(OrarioPastoEffettivo(data=lettura.data, pasto=lettura.pasto,
                                                ora=(lettura.inizio - timedelta(seconds=lettura.inizio.second)).time(),
                                                operatore="impianto"))
            invalida_orari_effettivi()
    return riga


def scarta(lettura, operatore):
    lettura.stato = "scartata"
    lettura.decisa_da = operatore
    lettura.decisa_il = datetime.utcnow()
