"""Aiuti condivisi dalle pagine del modulo Prodotti."""
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user

from app import db


def utente():
    """Nome da salvare in creato_da / modificato_da (registro: chi ha fatto cosa)."""
    if not current_user.is_authenticated:
        return None
    return current_user.display_name or current_user.username


def adesso():
    return datetime.now().isoformat(timespec="seconds")


def fornitori():
    """Fornitori dell'anagrafica del gestionale (Contact type=fornitore), per le tendine."""
    from app.models import Contact
    return (Contact.query.filter_by(type="fornitore").filter(Contact.active.isnot(False))
            .order_by(Contact.name).all())


def nome_fornitore(fornitore_id):
    from app.models import Contact
    if not fornitore_id:
        return None
    c = db.session.get(Contact, int(fornitore_id))
    return c.name if c else None


def crea_fornitore(nome):
    """Nuovo fornitore nell'anagrafica del gestionale, creato al volo dalle finestre del modulo.

    È l'unico punto in cui il modulo scrive nel database del nucleo: un contatto minimo (solo il nome),
    da completare poi in Anagrafica se serve.
    """
    from app.models import Contact
    nome = (nome or "").strip()
    if not nome:
        return None
    esistente = Contact.query.filter(db.func.lower(Contact.name) == nome.lower(), Contact.type == "fornitore").first()
    if esistente:
        return esistente
    c = Contact(type="fornitore", name=nome, notes="Creato dal modulo Prodotti")
    db.session.add(c)
    db.session.commit()
    return c


def dati_richiesta():
    """Dati di un POST: JSON (finestre con JavaScript) oppure modulo HTML classico."""
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict()


def errore(messaggio, codice=400):
    return jsonify(ok=False, error=messaggio), codice


def numero(valore, intero=False):
    """'1,5' → 1.5 ; '' → None. Accetta la virgola italiana."""
    if valore is None:
        return None
    testo = str(valore).strip().replace(",", ".")
    if not testo:
        return None
    try:
        return int(float(testo)) if intero else float(testo)
    except ValueError:
        return None


def vero(valore):
    return str(valore).lower() in ("1", "true", "on", "si", "sì", "yes")
