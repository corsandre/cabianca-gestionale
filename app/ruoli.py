"""Ruoli dei processi del gestionale (variabile d'ambiente RUOLO), dalla 3.4.0.

Lo stesso codice gira in più container (docker-compose.yml); RUOLO dice a create_app() che cosa fare.
Lo scopo è poter aggiornare il SITO (anche con moduli nuovi come Prodotti) riavviando solo il
container `web`, senza fermare il bot Telegram, i lavori programmati e l'impianto.

| RUOLO      | dove                      | sito | migra lo schema | scheduler + bot | moduli |
|------------|---------------------------|------|-----------------|-----------------|--------|
| completo   | default (installazione    |  sì  |       sì        |       sì        |   sì   |
|            | LAN, compose vecchio)     |      |                 |                 |        |
| web        | container `web`           |  sì  |       sì        |       no        |   sì   |
| servizi    | container `servizi`       |  no  |       no        |       sì        |   sì   |
| impianto   | container `impianto`      |  no  |       no        |       no        |   no   |
| sviluppo   | in locale (flask run)     |  sì  |       sì        |       no        |   sì   |

Regole che ne derivano:
- lo schema di gestionale.db (e dei moduli) lo modifica UN solo processo, quello del sito: prima
  della 3.4.0 lo facevano sito e impianto insieme a ogni avvio (corsa nascosta dagli except);
- chi non migra (servizi, impianto) all'avvio aspetta che il sito abbia aggiornato lo schema
  (vedi attendi_schema_nucleo in app/__init__.py);
- "sviluppo" non avvia mai il bot: due bot con lo stesso token si rubano i messaggi (409 Conflict).
"""
import os

COMPLETO, WEB, SERVIZI, IMPIANTO, SVILUPPO = "completo", "web", "servizi", "impianto", "sviluppo"
RUOLI = (COMPLETO, WEB, SERVIZI, IMPIANTO, SVILUPPO)


def ruolo_corrente():
    """RUOLO dall'ambiente; vuoto o assente = completo (come prima della 3.4.0)."""
    r = (os.environ.get("RUOLO") or COMPLETO).strip().lower()
    if r not in RUOLI:
        raise ValueError(f"RUOLO sconosciuto: {r!r} (validi: {', '.join(RUOLI)})")
    return r


def migra_schema(ruolo):
    """Questo processo è il proprietario dello schema dei database?"""
    return ruolo in (COMPLETO, WEB, SVILUPPO)


def avvia_servizi(ruolo):
    """Questo processo fa girare scheduler (backup, cassa, email, avvisi...) e bot Telegram?"""
    return ruolo in (COMPLETO, SERVIZI)


def carica_moduli(ruolo):
    """Questo processo carica i moduli (Prodotti...)? L'impianto no: usa solo i suoi dati."""
    return ruolo != IMPIANTO


def confronta_versioni(a, b):
    """-1, 0, 1 come a <, =, > b. "3.10.0" > "3.9.9". Le parti non numeriche valgono 0."""
    def parti(v):
        out = []
        for p in str(v or "0").split("-")[0].split("."):
            out.append(int(p) if p.isdigit() else 0)
        return out + [0] * (3 - len(out))
    pa, pb = parti(a), parti(b)
    return (pa > pb) - (pa < pb)
