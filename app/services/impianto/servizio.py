"""Servizio che sorveglia l'impianto di alimentazione (processo separato dal gestionale web).

Avvio:  RUOLO=impianto python -m app.services.impianto.servizio
(nel docker-compose è il servizio "impianto": stessa immagine e stesso database del gestionale; un
aggiornamento del gestionale web non interrompe la sorveglianza di un pasto in corso).

Comportamento
- Modalità manuale: nessuna connessione all'impianto; il servizio resta in attesa e ricontrolla
  le impostazioni ogni minuto.
- Controllo periodico (ogni `impianto_controllo_min`, 5 minuti se l'impianto non risponde):
  fotografia dello schermo + orari dei pasti. Salvato in impianto_controlli. Su Telegram (gruppo
  sistema) SOLO: un riepilogo al giorno, impianto non raggiungibile (dopo 3 tentativi) o di nuovo
  raggiungibile, orologio dell'impianto spostato di oltre 2 minuti, stato sconosciuto.
- Orari dei pasti cambiati sull'impianto: tra un controllo e l'altro si rileggono solo gli orari
  (file di pochi byte, niente fotografia) ogni 10 minuti, così anche un pasto anticipato viene seguito
  dall'inizio; se al risveglio per un pasto lo schermo mostra un prossimo pasto diverso da quello
  atteso, idem. In entrambi i casi messaggio nel gruppo dei pasti con gli orari prima e dopo.
- Pasto: da `impianto_anticipo_min` minuti prima del prossimo pasto (orario letto sullo schermo,
  convertito in ora reale con lo scarto dell'orologio dell'impianto) una fotografia ogni
  `impianto_foto_s` secondi finché l'impianto torna in attesa. Se il pasto non parte entro 20 minuti
  dall'orario → allarme "pasto non partito".
- Fine linea: valori confermati → impianto_letture_linee; in automatico registrati subito in
  uso_pasti, con verifica restano proposte da approvare in Alimentazione. Messaggi nel gruppo dei
  pasti (`impianto_chat_pasti`): inizio pasto, fine di ogni linea, riepilogo a fine pasto.
- Anomalie (siero insufficiente, fase bloccata, stato sconosciuto, linea non letta): evento con la
  fotografia dello schermo, inviata su Telegram (siero nel gruppo dei pasti, le altre nel gruppo sistema).
"""
import html
import io
import logging
import os
import time as orologio
from datetime import datetime, timedelta

from . import (crea_lettore, impostazione, modalita, cartella_dati, percorso_chiave,
               MANUALE, AUTOMATICO, NOMI_MODALITA)
from .base import ATTESA_ORARIO, SCONOSCIUTA, COMPONENTI
from .pasto import (TracciaPasto, PASTO_INIZIATO, PASTO_CONCLUSO, LINEA_INIZIATA, LINEA_CONCLUSA,
                    LINEA_NON_LETTA, SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA)

log = logging.getLogger("impianto")
TENTATIVI_PRIMA_DI_AVVISARE = 3
MINUTI_PASTO_NON_PARTITO = 20
MINUTI_CONTROLLO_ORARI = 10
SECONDI_SCARTO_OROLOGIO = 120
NOMI_COMPONENTI = {"acqua": "acqua", "siero": "siero", "farina": "farina"}


def _q(v):
    return "–" if v is None else f"{v:.2f}".replace(".", ",") + " q"


def _hm(t):
    return t.strftime("%H:%M") if t else "?"


class Servizio:

    def __init__(self, app):
        self.app = app
        self.lettore = None
        self.firma = None
        self.traccia = TracciaPasto()
        self.ultimo_controllo = None
        self.ultimi_orari = None         # ultima rilettura dei soli orari
        self.scarto_s = None             # ora reale − ora dell'impianto
        self.prossimo_pc = None          # prossimo pasto, orologio dell'impianto
        self.orari = []
        self.guasti = 0
        self.avvisato_guasto = False
        self.riepilogo_del = None
        self.pasto_mancato_avvisato = None
        self.inizio_pasto = None
        self.inizio_linee = {}
        self.linee_pasto = []

    # ── Telegram ───────────────────────────────────────────────────────────
    def _manda(self, testo, canale, png=None):
        from app.services.telegram_bot import send_telegram_message, send_telegram_foto
        if canale == "nessuno":
            return
        if png:
            send_telegram_foto(png, testo, canale)
        else:
            send_telegram_message(testo, canale)

    def _chat_pasti(self):
        return impostazione("impianto_chat_pasti")

    # ── configurazione ─────────────────────────────────────────────────────
    def _aggiorna_lettore(self):
        chiave_mtime = os.path.getmtime(percorso_chiave()) if os.path.exists(percorso_chiave()) else None
        firma = (modalita(), impostazione("impianto_tipo"), impostazione("impianto_host"),
                 impostazione("impianto_porta"), impostazione("impianto_utente"), chiave_mtime)
        if firma != self.firma:
            if self.lettore:
                self.lettore.chiudi()
            self.lettore = crea_lettore()
            self.firma = firma
            self.ultimo_controllo = None
            log.info("configurazione impianto: %s", NOMI_MODALITA.get(firma[0]))
        return self.lettore

    # ── giro principale ────────────────────────────────────────────────────
    def giro(self):
        """Un passo del servizio. Restituisce i secondi di attesa prima del prossimo."""
        with self.app.app_context():
            if modalita() == MANUALE or not self._aggiorna_lettore():
                if self.lettore:
                    self.lettore.chiudi()
                    self.lettore = None
                return 60
            adesso = datetime.now()
            if self.traccia.in_corso or self._pasto_vicino(adesso):
                self._fotografa(adesso)
                return max(15, int(impostazione("impianto_foto_s") or 60))
            intervallo = timedelta(minutes=5 if self.guasti else int(impostazione("impianto_controllo_min") or 60))
            if not self.ultimo_controllo or adesso - self.ultimo_controllo >= intervallo:
                self._controllo(adesso)
            elif not self.guasti and (not self.ultimi_orari
                                      or adesso - self.ultimi_orari >= timedelta(minutes=MINUTI_CONTROLLO_ORARI)):
                self._controlla_orari(adesso)
            return 60

    def _controlla_orari(self, adesso):
        """Rilettura leggera dei soli orari: se sono cambiati, controllo completo (che avvisa)."""
        self.ultimi_orari = adesso
        try:
            orari = self.lettore.orari_pasti()
        except Exception as e:      # i guasti li gestisce il controllo periodico
            log.info("rilettura orari non riuscita: %s", e)
            return
        if self.orari and orari and orari != self.orari:
            self._controllo(adesso)

    def _prossimo_reale(self, adesso):
        if self.prossimo_pc is None or self.scarto_s is None:
            return None
        p = datetime.combine(adesso.date(), self.prossimo_pc) + timedelta(seconds=self.scarto_s)
        if p < adesso - timedelta(hours=12):   # orario già passato da molto: è il pasto di domani
            p += timedelta(days=1)
        return p

    def _pasto_vicino(self, adesso):
        p = self._prossimo_reale(adesso)
        if p is None:
            return False
        anticipo = timedelta(minutes=int(impostazione("impianto_anticipo_min") or 5))
        return p - anticipo <= adesso <= p + timedelta(minutes=MINUTI_PASTO_NON_PARTITO) \
            and self.pasto_mancato_avvisato != p

    # ── controllo periodico ────────────────────────────────────────────────
    def _controllo(self, adesso):
        from app import db
        from app.models import ImpiantoControllo
        esito = self.lettore.controllo()
        self.ultimo_controllo = self.ultimi_orari = adesso
        l = esito.lettura
        precedente = ImpiantoControllo.query.filter_by(raggiungibile=True).order_by(ImpiantoControllo.istante.desc()).first()
        c = ImpiantoControllo(istante=adesso, raggiungibile=esito.raggiungibile, errore=esito.errore)
        if esito.raggiungibile:
            c.fase, c.stato, c.ora_pc, c.prossimo_pasto = l.fase, l.stato, l.ora_pc, l.prossimo_pasto
            c.orari = ",".join(_hm(o) for o in esito.orari)
            if l.ora_pc:
                c.scarto_orologio_s = int((adesso - datetime.combine(adesso.date(), l.ora_pc)).total_seconds())
                if abs(c.scarto_orologio_s) > 12 * 3600:   # a cavallo della mezzanotte
                    c.scarto_orologio_s -= 86400 if c.scarto_orologio_s > 0 else -86400
        db.session.add(c)
        db.session.commit()

        if not esito.raggiungibile:
            self.guasti += 1
            if self.guasti >= TENTATIVI_PRIMA_DI_AVVISARE and not self.avvisato_guasto:
                self.avvisato_guasto = True
                self._manda(f"⚠️ <b>Impianto non raggiungibile</b> da {self.guasti} tentativi.\n"
                            f"{html.escape(esito.errore or '')}", "sistema")
            return
        if self.avvisato_guasto:
            self._manda("✅ Impianto di nuovo raggiungibile.", "sistema")
        self.guasti, self.avvisato_guasto = 0, False

        atteso, atteso_reale = self.prossimo_pc, self._prossimo_reale(adesso)
        self.orari = esito.orari
        if l.prossimo_pasto:
            self.prossimo_pc = l.prossimo_pasto
        if c.scarto_orologio_s is not None:
            self.scarto_s = c.scarto_orologio_s
        if precedente:
            if precedente.orari and c.orari and c.orari != precedente.orari:
                self._avvisa_orari(adesso, precedente.orari, c.orari, l.prossimo_pasto)
            elif (atteso and atteso_reale and l.prossimo_pasto and l.prossimo_pasto != atteso and l.in_attesa
                  and not self.traccia.in_corso
                  and atteso_reale > adesso - timedelta(minutes=MINUTI_PASTO_NON_PARTITO)):
                # orari uguali ma il pasto atteso non è più il prossimo e non è stato fatto (es. saltato a mano)
                testo = (f"🕐 Il pasto delle {_hm(atteso)} non è più in programma: sull'impianto il "
                         f"prossimo pasto è alle {_hm(l.prossimo_pasto)}.")
                self._salva_evento("orari_cambiati", adesso, testo, atteso)
                self._manda(testo, self._chat_pasti())
            if (precedente.scarto_orologio_s is not None and c.scarto_orologio_s is not None
                    and abs(c.scarto_orologio_s - precedente.scarto_orologio_s) > SECONDI_SCARTO_OROLOGIO):
                self._manda(f"🕐 L'orologio dell'impianto si è spostato: ora è {self._scarto_testo(c.scarto_orologio_s)}.", "sistema")
        if l.fase not in (ATTESA_ORARIO, SCONOSCIUTA) and not self.traccia.in_corso:
            # servizio avviato (o riavviato) a pasto già in corso: lo si segue da qui
            for evento in self.traccia.aggiorna(adesso, l):
                self._evento(evento, None)
        if l.fase == SCONOSCIUTA:
            self._anomalia(STATO_SCONOSCIUTO, adesso, f"Stato dell'impianto mai visto: {html.escape(l.stato or '?')}",
                           esito.immagine_png)
        if self.riepilogo_del != adesso.date() and adesso.hour >= 6:
            self.riepilogo_del = adesso.date()
            self._manda(f"🟢 Impianto OK – pasti {c.orari.replace(',', ' · ')} – prossimo alle {_hm(l.prossimo_pasto)}"
                        f" – orologio dell'impianto {self._scarto_testo(c.scarto_orologio_s)}", "sistema")

    def _avvisa_orari(self, adesso, prima, dopo, prossimo):
        testo = (f"🕐 <b>Orari dei pasti cambiati</b> sull'impianto: {prima.replace(',', ' · ')} → "
                 f"{dopo.replace(',', ' · ')}" + (f"\nProssimo pasto alle {_hm(prossimo)}." if prossimo else ""))
        self._salva_evento("orari_cambiati", adesso, testo)
        self._manda(testo, self._chat_pasti())

    @staticmethod
    def _scarto_testo(s):
        if s is None:
            return "non letto"
        if abs(s) < 60:
            return "allineato"
        return f"{'indietro' if s > 0 else 'avanti'} di {abs(s) // 60} min"

    # ── pasto ──────────────────────────────────────────────────────────────
    def _fotografa(self, adesso):
        try:
            img, lettura = self.lettore.fotografa()
        except Exception as e:
            self.lettore.chiudi()
            self.guasti += 1
            log.warning("fotografia non riuscita: %s", e)
            if self.guasti == 5:
                self._manda(f"⚠️ Durante il pasto l'impianto non risponde da 5 tentativi ({html.escape(str(e))}).", "sistema")
            return
        self.guasti = 0
        if (lettura.in_attesa and lettura.prossimo_pasto and self.prossimo_pc
                and lettura.prossimo_pasto != self.prossimo_pc and not self.traccia.in_corso):
            # svegliati per un pasto che sullo schermo non c'è più: orario cambiato dall'ultimo controllo
            self._controllo(adesso)          # rilegge gli orari, li salva e avvisa
            return
        if lettura.in_attesa and lettura.prossimo_pasto:
            p = self._prossimo_reale(adesso)
            if (not self.traccia.in_corso and p and adesso > p + timedelta(minutes=MINUTI_PASTO_NON_PARTITO - 1)
                    and self.pasto_mancato_avvisato != p):
                self.pasto_mancato_avvisato = p
                self._anomalia("pasto_non_partito", adesso,
                               f"⚠️ <b>Pasto delle {_hm(self.prossimo_pc)} non partito</b>: l'impianto è ancora in attesa.",
                               self._png(img))
            self.prossimo_pc = lettura.prossimo_pasto
        for evento in self.traccia.aggiorna(adesso, lettura):
            self._evento(evento, img)

    @staticmethod
    def _png(img):
        if img is None:
            return None
        b = io.BytesIO()
        img.save(b, "PNG")
        return b.getvalue()

    def _salva_evento(self, tipo, istante, messaggio, orario=None, linea=None, png=None, anomalia=False):
        from app import db
        from app.models import ImpiantoEvento
        percorso = None
        if png:
            rel = os.path.join("anomalie", f"{istante:%Y%m%d-%H%M%S}-{tipo}.png")
            os.makedirs(os.path.join(cartella_dati(), "anomalie"), exist_ok=True)
            with open(os.path.join(cartella_dati(), rel), "wb") as f:
                f.write(png)
            percorso = rel
        db.session.add(ImpiantoEvento(istante=istante, tipo=tipo, orario_pasto=orario, linea=linea,
                                      messaggio=messaggio, immagine=percorso, anomalia=anomalia))
        db.session.commit()

    def _anomalia(self, tipo, istante, messaggio, png, orario=None, linea=None, canale="sistema"):
        self._salva_evento(tipo, istante, messaggio, orario, linea, png, anomalia=True)
        self._manda(messaggio, canale, png)

    def _evento(self, e, img):
        from app import db
        from .registrazione import salva_lettura_linea, registra
        chat = self._chat_pasti()
        if e.tipo == PASTO_INIZIATO:
            self.inizio_pasto, self.inizio_linee, self.linee_pasto = e.istante, {}, []
            self._salva_evento(e.tipo, e.istante, None, e.pasto)
            self._manda(f"🐷 Pasto delle {_hm(e.pasto)} iniziato.", chat)
        elif e.tipo == LINEA_INIZIATA:
            self.inizio_linee[e.linea] = e.istante
            self._salva_evento(e.tipo, e.istante, None, e.pasto, e.linea)
        elif e.tipo == LINEA_CONCLUSA and e.pasto is None:
            self._anomalia(LINEA_NON_LETTA, e.istante,
                           f"⚠️ Linea {e.linea}: valori letti ma orario del pasto non leggibile sullo schermo, "
                           f"lettura non salvata: {e.dati['reale']}", self._png(img), None, e.linea)
        elif e.tipo == LINEA_CONCLUSA:
            lettura = salva_lettura_linea(e.istante.date(), e, self.orari, inizio=self.inizio_linee.get(e.linea))
            registrata = None
            if modalita() == AUTOMATICO and lettura.confermato:
                registrata = registra(lettura)
            db.session.commit()
            r = e.dati["reale"]
            self.linee_pasto.append(r)       # valori, non la riga del database: il riepilogo arriva in un giro successivo
            valori = " · ".join(f"{NOMI_COMPONENTI[k]} {_q(r[k])}" for k in COMPONENTI)
            if registrata:
                esito = "registrata nel gestionale"
            elif lettura.stato == "proposta" and lettura.note:
                esito = html.escape(lettura.note)
            else:
                esito = "da approvare in Alimentazione"
            avviso = "" if lettura.confermato else "\n⚠️ Valori letti una sola volta: da controllare."
            self._salva_evento(e.tipo, e.istante, valori, e.pasto, e.linea)
            self._manda(f"✅ <b>Linea {e.linea}</b> (pasto delle {_hm(e.pasto)}): {valori} – totale {_q(r['totale'])}\n"
                        f"{esito}{avviso}", chat)
        elif e.tipo == PASTO_CONCLUSO:
            tot = {k: sum(l.get(k) or 0 for l in self.linee_pasto) for k in COMPONENTI}
            durata = round((e.istante - self.inizio_pasto).total_seconds() / 60) if self.inizio_pasto else None
            self._salva_evento(e.tipo, e.istante, None, e.pasto)
            self._manda(f"🏁 Pasto delle {_hm(e.pasto)} concluso" + (f" in {durata} min" if durata else "") +
                        f": {len(self.linee_pasto)} linee – " + " · ".join(f"{k} {_q(v)}" for k, v in tot.items()), chat)
        elif e.tipo == SIERO_INSUFFICIENTE:
            self._anomalia(e.tipo, e.istante,
                           f"🥛 <b>Siero insufficiente</b> sulla linea {e.linea}: {_q(e.dati['reale'])} invece di "
                           f"{_q(e.dati['teorico'])}. Cisterna finita?", self._png(img), e.pasto, e.linea, canale=chat)
        elif e.tipo == FASE_BLOCCATA:
            self._anomalia(e.tipo, e.istante,
                           f"⚠️ <b>Fase bloccata</b>: «{e.dati['fase']}» da {e.dati['minuti']} min sulla linea {e.linea}.",
                           self._png(img), e.pasto, e.linea)
        elif e.tipo == STATO_SCONOSCIUTO:
            self._anomalia(e.tipo, e.istante, f"❓ Stato dell'impianto mai visto: «{html.escape(e.dati.get('stato') or '?')}».",
                           self._png(img), e.pasto, e.linea)
        elif e.tipo == LINEA_NON_LETTA:
            self._anomalia(e.tipo, e.istante,
                           f"⚠️ Linea {e.linea} del pasto delle {_hm(e.pasto)} non letta: valori da inserire a mano.",
                           self._png(img), e.pasto, e.linea)


def main():
    os.environ["RUOLO"] = "impianto"
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    from app import create_app
    servizio = Servizio(create_app())
    log.info("servizio impianto avviato")
    while True:
        try:
            attesa = servizio.giro()
        except Exception:
            log.exception("errore nel servizio impianto")
            attesa = 60
        orologio.sleep(attesa)


if __name__ == "__main__":
    main()
