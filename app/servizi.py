"""Processo dei "servizi" del gestionale: scheduler e bot Telegram, senza sito (dalla 3.4.0).

Avvio (container `servizi` in docker-compose.yml):
    python -m app.servizi

Contiene tutto quello che prima girava dentro il sito e che non deve fermarsi quando il sito
viene aggiornato: backup notturno, sincronizzazione cassa, lettura email e fatture, avvisi
dell'allevamento, controllo del server, bot Telegram dell'allevamento.
La logica dei lavori NON cambia: è sempre _init_scheduler() in app/__init__.py, chiamata da
create_app() perché RUOLO=servizi (vedi app/ruoli.py).

Lo schema del database lo aggiorna il sito: all'avvio questo processo aspetta che il sito
abbia portato gestionale.db alla sua versione (_attendi_schema_nucleo).
"""
import logging
import os
import signal
import threading

log = logging.getLogger(__name__)


def main():
    os.environ.setdefault("RUOLO", "servizi")
    from app import create_app
    app = create_app()
    if not hasattr(app, "scheduler"):
        log.error("Scheduler non avviato: controllare RUOLO (deve essere 'servizi') e il registro")

    fermati = threading.Event()

    def chiudi(signum, _frame):
        log.info("Segnale %s: chiudo lo scheduler e termino", signum)
        fermati.set()

    signal.signal(signal.SIGTERM, chiudi)   # docker compose stop / down
    signal.signal(signal.SIGINT, chiudi)    # Ctrl+C in locale
    log.info("Servizi del gestionale avviati (scheduler + bot)")
    fermati.wait()
    sched = getattr(app, "scheduler", None)
    if sched is not None:
        sched.shutdown(wait=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
