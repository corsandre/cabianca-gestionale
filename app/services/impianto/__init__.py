"""Collegamento opzionale all'impianto di alimentazione: configurazione e creazione del lettore.

Configurazione nelle impostazioni del gestionale (tabella settings), modificabile da Impostazioni
allevamento: nessun dato dell'impianto è nel codice o nel .env, così ogni azienda ha i suoi.
In modalità manuale (default) non viene creato nessun lettore e non c'è nessuna connessione.

Credenziali: chiave SSH privata in <cartella dati>/impianto/chiave (generata da Impostazioni);
in alternativa, solo per prove, la password nella variabile d'ambiente IMPIANTO_PASSWORD.
"""
import os

from .base import MANUALE, VERIFICA, AUTOMATICO, MODALITA, NOMI_MODALITA  # noqa: F401

TIPI = {"em2000": "EM2000"}
DEFAULTS = {
    "impianto_modalita": MANUALE,
    "impianto_tipo": "em2000",
    "impianto_host": "",
    "impianto_porta": "22",
    "impianto_utente": "root",
    "impianto_controllo_min": "60",    # controllo periodico (heartbeat)
    "impianto_foto_s": "60",           # una fotografia ogni N secondi durante il pasto
    "impianto_anticipo_min": "5",      # si comincia a fotografare N minuti prima del pasto
    "impianto_chat_pasti": "allevamento",   # gruppo Telegram dei messaggi dei pasti: allevamento/sistema/nessuno
}


def impostazione(chiave):
    from app.models import Setting
    s = Setting.query.get(chiave)
    return s.value if s and s.value not in (None, "") else DEFAULTS.get(chiave, "")


def modalita():
    m = impostazione("impianto_modalita")
    return m if m in MODALITA else MANUALE


def cartella_dati():
    from flask import current_app
    return os.path.abspath(os.path.join(current_app.root_path, "..", "data", "impianto"))


def percorso_chiave():
    return os.path.join(cartella_dati(), "chiave")


def crea_lettore():
    """Lettore dell'impianto configurato, o None in modalità manuale / se manca l'indirizzo."""
    if modalita() == MANUALE or not impostazione("impianto_host"):
        return None
    chiave = percorso_chiave() if os.path.exists(percorso_chiave()) else None
    tipo = impostazione("impianto_tipo")
    if tipo == "em2000":
        from .em2000 import LettoreEM2000
        return LettoreEM2000(
            host=impostazione("impianto_host"), porta=impostazione("impianto_porta"),
            utente=impostazione("impianto_utente"), chiave=chiave,
            password=None if chiave else os.environ.get("IMPIANTO_PASSWORD"),
            known_hosts=os.path.join(cartella_dati(), "known_hosts"))
    raise ValueError(f"tipo di impianto non gestito: {tipo}")


def genera_chiave():
    """Crea (o sostituisce) la coppia di chiavi SSH ed25519 per il collegamento all'impianto.
    Restituisce la chiave pubblica da aggiungere sul PC dell'impianto (authorized_keys)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    os.makedirs(cartella_dati(), exist_ok=True)
    k = Ed25519PrivateKey.generate()
    privata = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                              serialization.NoEncryption())
    pubblica = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH)
    with open(percorso_chiave(), "wb") as f:
        f.write(privata)
    os.chmod(percorso_chiave(), 0o600)
    testo = pubblica.decode() + " gestionale-cabianca"
    with open(percorso_chiave() + ".pub", "w") as f:
        f.write(testo + "\n")
    return testo


def chiave_pubblica():
    p = percorso_chiave() + ".pub"
    return open(p).read().strip() if os.path.exists(p) else None
