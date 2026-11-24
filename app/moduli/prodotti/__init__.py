"""Modulo PRODOTTI: ricettario, libro dei lotti ed etichette dei prodotti trasformati.

Mappa del modulo: LEGGIMI.md in questa cartella. Regole dei moduli: README, «Moduli e ruoli dei processi».

Interfaccia verso il nucleo (usata da app/moduli/__init__.py):
    NOME, VERSIONE, DATABASE
    migra(app)     porta data/prodotti.db alla versione del codice (schema.py)
    registra(app)  registra il blueprint (routes.py)
    stato(app)     informazioni per /salute
"""
import os

NOME = "prodotti"
VERSIONE = "1.0.0-dev"
DATABASE = "prodotti.db"          # in data/, accanto a gestionale.db


def migra(app):
    from app.moduli import percorso_database
    from app.moduli.migrazioni import applica
    from app.moduli.prodotti.schema import MIGRAZIONI
    percorso = percorso_database(app, NOME)
    cartella_backup = os.path.join(app.root_path, "..", "backups")
    prima, dopo, copia = applica(percorso, MIGRAZIONI, NOME, cartella_backup, VERSIONE)
    if dopo != prima:
        app.logger.info(f"Prodotti: database aggiornato dalla versione {prima} alla {dopo}"
                        + (f" (copia di sicurezza: {copia})" if copia else ""))


def registra(app):
    from app.moduli.prodotti.routes import bp
    app.register_blueprint(bp)


def stato(app):
    from app.moduli import percorso_database
    from app.moduli.migrazioni import versione_attuale
    return {"schema": versione_attuale(percorso_database(app, NOME))}
