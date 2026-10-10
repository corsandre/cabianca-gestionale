"""Servizio che sorveglia l'impianto di alimentazione (processo separato dal gestionale web).

Avvio:  RUOLO=impianto python -m app.services.impianto.servizio
(nel docker-compose è il servizio "impianto": stessa immagine e stesso database del gestionale; un
aggiornamento del gestionale web non interrompe la sorveglianza di un pasto in corso).

Comportamento
- Modalità manuale: nessuna connessione all'impianto; il servizio resta in attesa e ricontrolla
  le impostazioni ogni minuto.
- Controllo periodico (ogni `impianto_controllo_min`, 5 minuti se l'impianto non risponde):
  fotografia dello schermo + orari dei pasti. Salvato in impianto_controlli. Su Telegram SOLO: un riepilogo al giorno (alle 6:50, con il confronto dei capi per box
  tra gestionale e PC: messaggio solo se ci sono differenze), impianto non raggiungibile (dopo 3 tentativi) o di nuovo
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
- Anomalie (siero o farina insufficiente, cisterna del siero o silos finiti, fase bloccata, stato
  sconosciuto, linea non letta): evento con la fotografia dello schermo, inviata su Telegram (siero,
  farina e silos). Tutti i messaggi dell'impianto vanno nel gruppo scelto nelle impostazioni
  (impianto_chat_pasti, default allevamento).
- Cisterna del siero e silos: "finito ora" quando finiscono durante un dosaggio dopo aver dato una parte
  vera della dose (QUOTA_FINITO_ORA; se erano già segnati vuoti serve più di metà dose, altrimenti sono i
  pochi kg che pompa e coclea tirano prima di fermarsi). Si ricorda quando, nell'impostazione
  impianto_vuoto_siero / impianto_vuoto_silos_<n>. Finché restano vuoti: "ancora vuoto" una volta al
  giorno (per un silos con la coclea a 0 "saltato da EM2000": EM2000 ricorda la sostituzione e non
  riprova la coclea finché non finiscono gli altri). "Di nuovo in uso" quando tornano a dare la dose piena.
- Impostazioni dell'impianto (Brix del siero, % del siero nelle ricette): rilette con gli orari; se
  cambiano, messaggio nel gruppo dei pasti. L'ultimo valore visto è in impianto_parametri.
- EM2000 su un'altra schermata (es. Menu principale): avviso, controlli ogni 5 minuti finché non torna
  su Situazione impianto, poi conferma. Il riepilogo giornaliero parte solo con dati leggibili.
- Lettura incompleta: in una schermata riconosciuta qualcosa non si legge (riga della ricetta mai
  vista, ora o linea illeggibili...; vedi LetturaSchermo.problemi). Durante il pasto deve ripetersi in
  due fotografie di fila, al controllo periodico si conferma con una seconda fotografia. Fotografia
  al massimo una al giorno per tipo di problema (idem per lo stato sconosciuto
  visto ai controlli periodici).
"""
import html
import io
import logging
import os
import time as orologio
from datetime import date, datetime, time, timedelta

from . import (crea_lettore, impostazione, modalita, cartella_dati, percorso_chiave,
               MANUALE, AUTOMATICO, NOMI_MODALITA)
from .base import (ATTESA_ORARIO, ATTESA_INIZIO, SCONOSCIUTA, COMPONENTI, PREPARAZIONE, STABILIZZAZIONE, MISCELAZIONE,
                   NOMI_FASI)
from .pasto import (TracciaPasto, PASTO_INIZIATO, PASTO_CONCLUSO, LINEA_INIZIATA, LINEA_CONCLUSA,
                    LINEA_NON_LETTA, SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA,
                    SILOS_FINITO, SIERO_FINITO, FARINA_INSUFFICIENTE, MISCELAZIONE_INIZIATA)

log = logging.getLogger("impianto")
TENTATIVI_PRIMA_DI_AVVISARE = 3
MINUTI_PASTO_NON_PARTITO = 20
MINUTI_CONTROLLO_ORARI = 10
SECONDI_FOTO_CARICO = 20           # durante il carico dei componenti, per cogliere l'inizio della miscelazione
SECONDI_MISCELAZIONE_RISERVA = 360  # se la durata della ricetta non si legge
SECONDI_SCARTO_OROLOGIO = 120
ORA_RIEPILOGO = time(6, 50)         # riepilogo "Impianto OK" e confronto dei capi per box, una volta al giorno
NOMI_COMPONENTI = {"acqua": "acqua", "siero": "siero", "farina": "farina"}


def _q(v):
    return "–" if v is None else f"{v:.2f}".replace(".", ",") + " q"


def _silos(n):
    """Coclea n → silos che la alimenta (coclea 1 = silos A, 2 = B, ...)."""
    return f"silos {chr(64 + n)}" if 1 <= n <= 26 else f"coclea {n}"


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
        self.pasto_mancato_avvisato = None
        self.inizio_pasto = None
        self.inizio_linee = {}
        self.linee_pasto = []
        self.problemi_prec = set()       # problemi di lettura della fotografia precedente
        self.segnalati_oggi = {}         # problema / stato sconosciuto -> giorno in cui è stato segnalato
        self.schermata_errata = None     # stato della schermata non riconosciuta, finché non torna giusta
        self.aggancio = False            # True mentre si aggancia un pasto già in corso (niente doppioni)
        self.riempimento = None          # (istante, linea, pasto): avviso "tra 1 minuto riempimento tubi"

    # ── riepilogo del mattino ──────────────────────────────────────────────
    @staticmethod
    def _riepilogo_del():
        """Giorno dell'ultimo riepilogo (salvato: un riavvio del servizio non lo rimanda)."""
        v = impostazione("impianto_riepilogo_del")
        try:
            return date.fromisoformat(v) if v else None
        except ValueError:
            return None

    def _riepilogo_da_fare(self, adesso):
        return adesso.time() >= ORA_RIEPILOGO and self._riepilogo_del() != adesso.date()

    def _riepilogo(self, adesso, c, l):
        from app import db
        from app.services.allevamento_scorte import set_setting
        set_setting("impianto_riepilogo_del", adesso.date().isoformat())
        db.session.commit()
        self._manda(f"🟢 Impianto OK – pasti {c.orari.replace(',', ' · ')} – prossimo alle {_hm(l.prossimo_pasto)}"
                    f" – orologio dell'impianto {self._scarto_testo(c.scarto_orologio_s)}", self._chat_pasti())
        try:
            from app.services.allevamento_confronto_box import confronta, testo_telegram
            testo = testo_telegram(confronta(self.lettore))
            if testo:
                self._manda(testo, self._chat_pasti())
        except Exception as e:
            log.warning("confronto capi per box non riuscito: %s", e)

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
            self._richiesta_aggiornamento(adesso)
            if self.traccia.in_corso or self._pasto_vicino(adesso):
                self._fotografa(adesso)
                self._avviso_riempimento(datetime.now())
                attesa = max(15, int(impostazione("impianto_foto_s") or 60))
                if self.traccia.fase in (PREPARAZIONE, STABILIZZAZIONE):
                    attesa = min(attesa, SECONDI_FOTO_CARICO)
                if self.riempimento:
                    attesa = max(1, min(attesa, int((self.riempimento[0] - datetime.now()).total_seconds()) + 1))
                return attesa
            intervallo = timedelta(minutes=5 if self.guasti or self.schermata_errata
                                   else int(impostazione("impianto_controllo_min") or 60))
            if self._riepilogo_da_fare(adesso):
                # alle 6:50 un controllo completo subito, per il riepilogo (al massimo ogni 5 minuti
                # se il PC non risponde o la schermata non è quella giusta)
                intervallo = min(intervallo, timedelta(minutes=5))
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
        elif not self.schermata_errata:
            # anche la schermata: se EM2000 è su un'altra pagina, controllo completo subito (che avvisa)
            try:
                _, lettura = self.lettore.fotografa()
                if lettura.fase == SCONOSCIUTA:
                    self._controllo(adesso)
            except Exception as e:
                log.info("fotografia del controllo leggero non riuscita: %s", e)
        self._controlla_parametri(adesso)

    def _sincronizza_orari(self, adesso, orari):
        """Con il collegamento attivo gli orari dei pasti del gestionale sono quelli impostati sul PC
        (Impostazioni allevamento li mostra in sola lettura). Il gestionale ha 3 pasti: con un numero
        diverso sul PC non si cambia niente e lo si dice una volta al giorno."""
        from app import db
        from app.services.allevamento_scorte import set_setting, orario_pasto_str
        if not orari:
            return
        if len(orari) != 3:
            if self._da_segnalare(adesso, f"orari:{len(orari)}"):
                self._manda(f"⚠️ Sul PC di alimentazione ci sono {len(orari)} pasti ({', '.join(_hm(o) for o in orari)}): "
                            f"il gestionale ne gestisce 3, gli orari del gestionale non sono stati aggiornati.", self._chat_pasti())
            return
        cambiati = False
        for n, o in enumerate(sorted(orari), start=1):
            if orario_pasto_str(n) != _hm(o):
                set_setting(f"allevamento_orario_pasto_{n}", _hm(o))
                cambiati = True
        if cambiati:
            db.session.commit()
            log.info("orari dei pasti del gestionale aggiornati da quelli del PC: %s", ", ".join(_hm(o) for o in orari))

    def _controlla_parametri(self, adesso):
        """Brix del siero e % del siero nelle ricette: messaggio se cambiati dall'ultima volta."""
        import json
        from app import db
        from app.models import Setting
        try:
            nuovi = self.lettore.parametri()
        except Exception as e:
            log.info("lettura delle impostazioni dell'impianto non riuscita: %s", e)
            return
        if not nuovi:
            return
        from app.services.allevamento_scorte import set_setting
        set_setting("impianto_parametri_letto", adesso.isoformat(timespec="minutes"))   # per le schede di Alimentazione
        db.session.commit()
        s = db.session.get(Setting, "impianto_parametri")
        vecchi = json.loads(s.value) if s and s.value else None
        if vecchi == nuovi:
            return
        if s:
            s.value = json.dumps(nuovi)
        else:
            db.session.add(Setting(key="impianto_parametri", value=json.dumps(nuovi)))
        db.session.commit()
        if vecchi is None:
            return          # prima lettura: si memorizza e basta
        pct = lambda v: "–" if v is None else f"{v:.1f}".replace(".", ",") + "%"
        cambi = []
        if vecchi.get("brix") != nuovi.get("brix"):
            cambi.append(f"Brix del siero {pct(vecchi.get('brix'))} → <b>{pct(nuovi.get('brix'))}</b>")
        vs, ns = vecchi.get("siero") or {}, nuovi.get("siero") or {}
        for ricetta in sorted(set(vs) | set(ns)):
            if vs.get(ricetta) != ns.get(ricetta):
                cambi.append(f"siero nella «{html.escape(ricetta)}» {pct(vs.get(ricetta))} → <b>{pct(ns.get(ricetta))}</b>")
        if "rapporto" in vecchi:        # (letture salvate prima della 2.2 non hanno il rapporto)
            vr, nr = vecchi.get("rapporto") or {}, nuovi.get("rapporto") or {}
            rapp = lambda v: "–" if v is None else f"10:{v:g}"
            for ricetta in sorted(set(vr) | set(nr)):
                if vr.get(ricetta) != nr.get(ricetta):
                    cambi.append(f"rapporto di diluizione della «{html.escape(ricetta)}» {rapp(vr.get(ricetta))} → "
                                 f"<b>{rapp(nr.get(ricetta))}</b>")
        if cambi:
            testo = "🧪 <b>Impostazioni dell'impianto cambiate</b>: " + "; ".join(cambi) + "."
            self._salva_evento("parametri_cambiati", adesso, testo)
            self._manda(testo, self._chat_pasti())

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
                            f"{html.escape(esito.errore or '')}", self._chat_pasti())
            return
        if self.avvisato_guasto:
            self._manda("✅ Impianto di nuovo raggiungibile.", self._chat_pasti())
        self.guasti, self.avvisato_guasto = 0, False

        atteso, atteso_reale = self.prossimo_pc, self._prossimo_reale(adesso)
        self.orari = esito.orari
        self._sincronizza_orari(adesso, esito.orari)
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
                self._manda(f"🕐 L'orologio dell'impianto si è spostato: ora è {self._scarto_testo(c.scarto_orologio_s)}.", self._chat_pasti())
        if l.fase not in (ATTESA_ORARIO, SCONOSCIUTA) and not self.traccia.in_corso:
            # pasto trovato già in corso. Se è ancora sulla linea 1 all'inizio (es. orario spostato a ridosso
            # e visto dal controllo dei 10 minuti) è appena partito: lo si tratta come un inizio vero.
            # Altrimenti (servizio riavviato a pasto avanzato) lo si segue da qui, ma l'inizio vero non si
            # conosce: niente "iniziato", durata né orario effettivo.
            appena_partito = l.linea in (1, None) and l.fase in (ATTESA_INIZIO, PREPARAZIONE, STABILIZZAZIONE)
            self.aggancio = not appena_partito
            try:
                for evento in self.traccia.aggiorna(adesso, l):
                    self._evento(evento, None)
            finally:
                self.aggancio = False
            if not appena_partito:
                self.inizio_pasto, self.inizio_linee = None, {}
        if l.fase == SCONOSCIUTA:
            self.schermata_errata = l.stato or "?"
            if self._da_segnalare(adesso, f"stato:{self.schermata_errata}"):   # stessa chiave del reset
                self._anomalia(STATO_SCONOSCIUTO, adesso, self._testo_sconosciuto(l.stato), esito.immagine_png)
        elif self.schermata_errata:
            self._schermata_tornata(esito.immagine_png)
        if l.problemi():
            try:            # conferma con una seconda fotografia (una sola può essere a metà aggiornamento)
                img2, l2 = self.lettore.fotografa()
                self._problemi(adesso, set(l.problemi()) & set(l2.problemi()), img2)
            except Exception as ex:
                log.info("seconda fotografia non riuscita: %s", ex)
        self._controlla_parametri(adesso)
        if l.fase != SCONOSCIUTA:
            self._ricetta_in_uso(l, adesso)
        if self._riepilogo_da_fare(adesso) and l.fase != SCONOSCIUTA and l.prossimo_pasto and l.ora_pc:
            self._riepilogo(adesso, c, l)

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
                self._manda(f"⚠️ Durante il pasto l'impianto non risponde da 5 tentativi ({html.escape(str(e))}).", self._chat_pasti())
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
        if lettura.fase != SCONOSCIUTA and self.schermata_errata:
            self._schermata_tornata(self._png(img))
        problemi = set(lettura.problemi())
        self._problemi(adesso, problemi & self.problemi_prec, img)
        self.problemi_prec = problemi
        for evento in self.traccia.aggiorna(adesso, lettura):
            self._evento(evento, img)

    def _schermata_tornata(self, png):
        self.segnalati_oggi.pop(f"stato:{self.schermata_errata}", None)   # se ricapita, si riavvisa
        self.schermata_errata = None
        self._manda("✅ EM2000 di nuovo sulla schermata «Situazione impianto»: i pasti vengono seguiti.",
                    self._chat_pasti(), png)

    @staticmethod
    def _testo_sconosciuto(stato):
        if stato == "MENU PRINCIPALE":
            return ("⚠️ <b>EM2000 è sul Menu principale</b>: per seguire i pasti va lasciato sulla schermata "
                    "«6) Situazione impianto».")
        if stato == "SITUAZIONE IMPIANTO SPOSTATA":
            return ("⚠️ <b>La schermata «Situazione impianto» è spostata</b>: il contenuto della finestra è scorso "
                    "fuori posizione e non si legge. Riportalo a posto, per esempio riaprendo «6) Situazione impianto» dal menu.")
        if stato == "PAGINA ?":
            return ("⚠️ <b>EM2000 è su un'altra pagina</b> (non ancora insegnata al lettore): per seguire i pasti va "
                    "lasciato sulla schermata «6) Situazione impianto».")
        if stato and stato.startswith("PAGINA "):
            return (f"⚠️ <b>EM2000 è sulla pagina «{html.escape(stato[7:].capitalize())}»</b>: per seguire i pasti "
                    f"va lasciato sulla schermata «6) Situazione impianto».")
        if stato and stato.startswith("fotografia non leggibile"):
            return f"⚠️ L'impianto risponde ma la {html.escape(stato)}."
        return f"❓ Stato dell'impianto mai visto: «{html.escape(stato or '?')}»."

    # ── messaggi di dettaglio del pasto ────────────────────────────────────
    def _messaggi_completi(self):
        return impostazione("impianto_messaggi") != "essenziali"

    def _ricetta_in_uso(self, lettura, adesso):
        """Memorizza la ricetta in uso (nome e rapporto impostato) per Alimentazione e Analisi."""
        import json
        from app import db
        from app.services.allevamento_scorte import set_setting
        try:
            r = self.lettore.ricetta_in_uso(lettura) if lettura is not None and lettura.righe else None
        except Exception as ex:
            log.info("ricetta in uso non letta: %s", ex)
            return None
        if r:
            set_setting("impianto_ricetta", json.dumps({"nome": r["nome"], "rapporto": r["rapporto"],
                                                        "letto_il": adesso.isoformat(timespec="minutes")}))
            db.session.commit()
        return r

    def _miscelazione(self, e, chat):
        """Componenti caricati: messaggio e sveglia un minuto prima del riempimento dei tubi."""
        self._salva_evento(e.tipo, e.istante, None, e.pasto, e.linea)
        ricetta = self._ricetta_in_uso(e.lettura, e.istante)
        if self.aggancio or not self._messaggi_completi():
            return
        r = e.dati["reale"]
        valori = " · ".join(f"{NOMI_COMPONENTI[k]} {_q(r.get(k))}" for k in COMPONENTI)
        self._manda(f"🥣 <b>Linea {e.linea}</b>: componenti caricati ({valori}), inizia la miscelazione.", chat)
        durata = ricetta["durata_s"] if ricetta else None
        self.riempimento = (e.istante + timedelta(seconds=(durata or SECONDI_MISCELAZIONE_RISERVA) - 60), e.linea, e.pasto)

    def _avviso_riempimento(self, adesso):
        if not self.riempimento or adesso < self.riempimento[0]:
            return
        _, linea, pasto = self.riempimento
        self.riempimento = None
        if self.traccia.in_corso and self.traccia.linea == linea and self.traccia.fase == MISCELAZIONE:
            self._manda(f"⏱️ <b>Linea {linea}</b>: tra 1 minuto riempimento dei tubi.", self._chat_pasti())

    # ── aggiornamento chiesto dal gestionale o dal bot ──────────────────────
    def _richiesta_aggiornamento(self, adesso):
        from app import db
        from app.models import Setting
        s = db.session.get(Setting, "impianto_richiesta_aggiornamento")
        if not s:
            return
        chi = s.value or ""
        db.session.delete(s)
        db.session.commit()
        self._controllo(adesso)
        self._controlla_parametri(adesso)
        self._manda(self._testo_stato(adesso, chi), self._chat_pasti())

    def _testo_stato(self, adesso, chi=""):
        import json
        from app import db
        from app.models import ImpiantoControllo, Setting
        c = ImpiantoControllo.query.order_by(ImpiantoControllo.istante.desc()).first()
        richiesta = f" (richiesto da {html.escape(chi)})" if chi else ""
        if not c or not c.raggiungibile:
            return f"🔄 Aggiornamento dal PC{richiesta}: impianto <b>non raggiungibile</b>."
        p = db.session.get(Setting, "impianto_parametri")
        par = json.loads(p.value) if p and p.value else {}
        pct = lambda v: "–" if v is None else f"{v:.1f}".replace(".", ",") + "%"
        righe = [f"🔄 <b>Aggiornato dal PC alle {adesso:%H:%M}</b>{richiesta}",
                 f"Schermata: {'⚠️ ' + html.escape(c.stato or '?') if c.fase == SCONOSCIUTA else 'Situazione impianto, ' + NOMI_FASI.get(c.fase, c.fase)}",
                 f"Pasti: {(c.orari or '?').replace(',', ' · ')} – prossimo alle {_hm(c.prossimo_pasto)}"]
        if par:
            righe.append(f"Brix del siero {pct(par.get('brix'))}" + "".join(
                f" · siero nella «{html.escape(k)}» {pct(v)}" for k, v in (par.get("siero") or {}).items()))
        return "\n".join(righe)

    # ── letture incomplete ─────────────────────────────────────────────────
    def _da_segnalare(self, adesso, chiave):
        if self.segnalati_oggi.get(chiave) == adesso.date():
            return False
        self.segnalati_oggi[chiave] = adesso.date()
        return True

    def _problemi(self, adesso, problemi, img):
        nuovi = sorted(p for p in problemi if self._da_segnalare(adesso, p))
        if nuovi:
            self._anomalia("lettura_incompleta", adesso,
                           "🔍 <b>Lettura incompleta</b> dello schermo dell'impianto: " +
                           "; ".join(html.escape(p) for p in nuovi[:5]) +
                           (f" e altri {len(nuovi) - 5}" if len(nuovi) > 5 else "") + ". Schermata da insegnare al lettore.",
                           self._png(img) if not isinstance(img, (bytes, type(None))) else img)

    # ── cisterna del siero e silos ─────────────────────────────────────────
    @staticmethod
    def _chiave_vuoto(chiave):
        return "impianto_vuoto_siero" if chiave[0] == "siero" else f"impianto_vuoto_silos_{chiave[1]}"

    @staticmethod
    def _nome_esaurito(chiave):
        return "Cisterna del siero" if chiave[0] == "siero" else f"Silos {chr(64 + chiave[1])} (coclea {chiave[1]})"

    @staticmethod
    def _materiale(c):
        """'7,69 q di acqua' / '0,40 q di farina (silos C)' per una riga di sostituzione"""
        if c["comp"] == "farina":
            return f"{_q(c['reale'])} di farina" + (f" ({_silos(c['coclea'])})" if c["coclea"] else "")
        return f"{_q(c['reale'])} di {c['comp']}"

    # quota della dose sotto la quale una cisterna/silos già segnato vuoto è "ancora vuoto" (la pompa o la
    # coclea partono e tirano qualche kg prima di fermarsi), e sopra la quale un componente non ancora segnato
    # vuoto si considera "finito ora" (ha dato una parte vera della dose)
    QUOTA_FINITO_ORA, QUOTA_DOPO_RICARICA = 0.10, 0.50

    def _gia_segnalato(self, e, nome):
        """Lo stesso avviso per lo stesso pasto e linea c'è già (es. servizio riavviato a pasto in corso)."""
        from app.models import ImpiantoEvento
        oggi = datetime.combine(e.istante.date(), datetime.min.time())
        return ImpiantoEvento.query.filter(
            ImpiantoEvento.tipo == e.tipo, ImpiantoEvento.orario_pasto == e.pasto, ImpiantoEvento.linea == e.linea,
            ImpiantoEvento.istante >= oggi, ImpiantoEvento.messaggio.like(f"%{nome}%")).first() is not None

    def _esaurito(self, e, img, chat):
        import json
        from app import db
        from app.models import Setting
        d = e.dati
        if self._gia_segnalato(e, self._nome_esaurito(("siero",) if e.tipo == SIERO_FINITO else ("silos", d["coclea"]))):
            return
        siero = e.tipo == SIERO_FINITO
        chiave = ("siero",) if siero else ("silos", d["coclea"])
        nome, icona = self._nome_esaurito(chiave), "🥛" if siero else "🌾"
        finito, vuoto = ("finita", "vuota") if siero else ("finito", "vuoto")
        con = " e ".join(self._materiale(c) for c in d["con"])
        dove = f"linea {e.linea} del pasto delle {_hm(e.pasto)}"
        nome_imp = self._chiave_vuoto(chiave)
        s = db.session.get(Setting, nome_imp)
        quota = (d["reale"] or 0) / d["teorico"] if d.get("teorico") else 0
        gia_vuoto = s is not None
        if quota >= self.QUOTA_FINITO_ORA and (not gia_vuoto or quota >= self.QUOTA_DOPO_RICARICA):
            dal = d["dal"]
            testo = (f"{icona} <b>{nome}: {finito} ora</b>, durante il dosaggio della {dove} (alle {dal:%H:%M}): "
                     f"caricati {_q(d['reale'])} su {_q(d['teorico'])}, completato con {con}.")
            valore = json.dumps({"dal": dal.isoformat(timespec="minutes"), "pasto": _hm(e.pasto), "linea": e.linea})
            if s:
                s.value = valore
            else:
                db.session.add(Setting(key=nome_imp, value=valore))
            db.session.commit()
            self.segnalati_oggi[f"vuoto:{chiave}"] = e.istante.date()   # oggi non serve anche "ancora vuoto"
            self._anomalia(e.tipo, e.istante, testo, self._png(img), e.pasto, e.linea, canale=chat)
            return
        # già vuoto (o mai visto finire): conferma una volta al giorno
        if not s:
            db.session.add(Setting(key=nome_imp, value=json.dumps({"dal": None})))
            db.session.commit()
        if not self._da_segnalare(e.istante, f"vuoto:{chiave}"):
            self._salva_evento(e.tipo, e.istante, f"{nome}: ancora {vuoto} ({dove})", e.pasto, e.linea)
            return
        prima = json.loads(s.value) if s and s.value else {}
        quando = datetime.fromisoformat(prima["dal"]) if prima.get("dal") else None
        da = (f"{finito} il {quando:%d/%m} alle {quando:%H:%M}" + (f", pasto delle {prima['pasto']}" if prima.get("pasto") else "")
              if quando else "non so da quando")
        if not siero and not d["reale"]:
            # coclea a 0: EM2000 ricorda la sostituzione e non riprova il silos finché non finiscono gli altri
            testo = (f"{icona} <b>{nome}: saltato da EM2000</b> ({da}) – la {dove} è stata fatta con {con}. "
                     f"Il PC non riprova il silos finché non finiscono gli altri: se l'hai già ricaricato non serve fare niente.")
        else:
            tirati = f" (ha tirato solo {_q(d['reale'])})" if d["reale"] else ""
            testo = f"{icona} <b>{nome}: ancora {vuoto}</b>{tirati} – {da}. La {dove} è stata fatta con {con}."
        self._anomalia(e.tipo, e.istante, testo, self._png(img), e.pasto, e.linea, canale=chat)

    def _ricaricato(self, chiave, e, chat):
        from app import db
        from app.models import Setting
        s = db.session.get(Setting, self._chiave_vuoto(chiave))
        if not s:
            return
        db.session.delete(s)
        db.session.commit()
        testo = (f"{'🥛' if chiave[0] == 'siero' else '🌾'} <b>{self._nome_esaurito(chiave)}: di nuovo in uso</b>, "
                 f"dose piena sulla linea {e.linea} del pasto delle {_hm(e.pasto)}.")
        self._salva_evento("ricaricato", e.istante, testo, e.pasto, e.linea)
        self._manda(testo, chat)

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

    def _anomalia(self, tipo, istante, messaggio, png, orario=None, linea=None, canale=None):
        self._salva_evento(tipo, istante, messaggio, orario, linea, png, anomalia=True)
        self._manda(messaggio, canale or self._chat_pasti(), png)

    def _evento(self, e, img):
        from app import db
        from .registrazione import salva_lettura_linea, registra
        chat = self._chat_pasti()
        if e.tipo == PASTO_INIZIATO:
            self.inizio_pasto, self.inizio_linee, self.linee_pasto = e.istante, {}, []
            self._salva_evento(e.tipo, e.istante, "agganciato già in corso" if self.aggancio else None, e.pasto)
            if not self.aggancio:        # agganciato dopo un riavvio: non è l'inizio vero, niente messaggio
                self._manda(f"🐷 Pasto delle {_hm(e.pasto)} iniziato.", chat)
        elif e.tipo == MISCELAZIONE_INIZIATA:
            self._miscelazione(e, chat)
        elif e.tipo == LINEA_INIZIATA:
            self.inizio_linee[e.linea] = e.istante
            self._salva_evento(e.tipo, e.istante, None, e.pasto, e.linea)
        elif e.tipo == LINEA_CONCLUSA and e.pasto is None:
            self._anomalia(LINEA_NON_LETTA, e.istante,
                           f"⚠️ Linea {e.linea}: valori letti ma orario del pasto non leggibile sullo schermo, "
                           f"lettura non salvata: {e.dati['reale']}", self._png(img), None, e.linea)
        elif e.tipo == LINEA_CONCLUSA:
            from .registrazione import normalizza_siero
            e.dati["reale"] = normalizza_siero(e.dati["reale"])
            lettura = salva_lettura_linea(e.istante.date(), e, self.orari, inizio=self.inizio_linee.get(e.linea))
            registrata = None
            if modalita() == AUTOMATICO and lettura.confermato:
                registrata = registra(lettura)
            db.session.commit()
            r = e.dati["reale"]
            self.linee_pasto.append(r)       # valori, non la riga del database: il riepilogo arriva in un giro successivo
            valori = " · ".join(f"{NOMI_COMPONENTI[k]} {_q(r[k])}" for k in COMPONENTI)
            silos = e.dati.get("silos") or {}
            if len(silos) > 1:     # farina da più silos: dettaglio per silos
                valori += " (" + " + ".join(f"{_silos(n)} {_q(q)}" for n, q in sorted(silos.items())) + ")"
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
            for chiave in e.dati.get("piene") or []:
                self._ricaricato(tuple(chiave), e, chat)
        elif e.tipo == PASTO_CONCLUSO:
            tot = {k: sum(l.get(k) or 0 for l in self.linee_pasto) for k in COMPONENTI}
            durata = round((e.istante - self.inizio_pasto).total_seconds() / 60) if self.inizio_pasto else None
            self._salva_evento(e.tipo, e.istante, None, e.pasto)
            self._manda(f"🏁 Pasto delle {_hm(e.pasto)} concluso" + (f" in {durata} min" if durata else "") +
                        (f": {len(self.linee_pasto)} linee – " + " · ".join(f"{k} {_q(v)}" for k, v in tot.items())
                         if self.linee_pasto else ": nessuna linea letta, valori da inserire a mano."), chat)
        elif e.tipo == SIERO_INSUFFICIENTE:
            self._anomalia(e.tipo, e.istante,
                           f"🥛 <b>Dosaggio di siero inferiore al previsto</b> sulla linea {e.linea}: {_q(e.dati['reale'])} "
                           f"invece di {_q(e.dati['teorico'])}, senza sostituzione (la cisterna non risulta finita): "
                           f"controllare la pompa del siero.", self._png(img), e.pasto, e.linea, canale=chat)
        elif e.tipo in (SILOS_FINITO, SIERO_FINITO):
            self._esaurito(e, img, chat)
        elif e.tipo == FARINA_INSUFFICIENTE:
            self._anomalia(e.tipo, e.istante,
                           f"🌾 <b>Dosaggio di farina inferiore al previsto</b> sulla linea {e.linea}: {_q(e.dati['reale'])} "
                           f"invece di {_q(e.dati['teorico'])}, senza sostituzione (il silos non risulta finito): "
                           f"controllare la coclea.", self._png(img), e.pasto, e.linea, canale=chat)
        elif e.tipo == FASE_BLOCCATA:
            self._anomalia(e.tipo, e.istante,
                           f"⚠️ <b>Fase bloccata</b>: «{e.dati['fase']}» da {e.dati['minuti']} min sulla linea {e.linea}.",
                           self._png(img), e.pasto, e.linea)
        elif e.tipo == STATO_SCONOSCIUTO:
            self.schermata_errata = e.dati.get("stato") or "?"
            self.segnalati_oggi[f"stato:{self.schermata_errata}"] = e.istante.date()
            self._anomalia(e.tipo, e.istante, self._testo_sconosciuto(e.dati.get("stato")), self._png(img), e.pasto, e.linea)
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
