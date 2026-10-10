"""Lettore per l'impianto di alimentazione EM2000 (Gui2000 sotto Wine su Linux).

Tutto in SOLA LETTURA: sul PC dell'impianto non si scrive nessun file e non si avvia niente che
possa interferire con l'alimentazione.
- Schermo: `xwd` fotografa lo schermo e lo manda compresso sull'uscita del comando (nessun file sul
  PC), lo si decodifica e legge qui (schermo.py).
- Orari dei pasti: tabella Paradox ORARI.DB letta via SFTP.
Connessione SSH con paramiko; la chiave dell'host viene memorizzata al primo collegamento
(file known_hosts nella cartella dati del gestionale) e poi verificata.
"""
import gzip
import io
import os
from datetime import time

from ..base import LettoreImpianto, EsitoControllo, LetturaSchermo, SCONOSCIUTA
from . import paradox, schermo

EM2000 = "/root/.wine/drive_d/em2000"
ORARI_DB = f"{EM2000}/pc/db/new/ORARI.DB"
COMPO_DB = f"{EM2000}/pc/db/new/COMPO.DB"                 # componenti: SIERO.PERSECCO = Brix impostato
RICETTECOMPO_DB = f"{EM2000}/pc/db/new/RICETTECOMPO.DB"   # % di ogni componente in ogni ricetta
RICETTE_DB = f"{EM2000}/pc/db/new/Ricette.DB"             # nomi delle ricette
BOX_DB = f"{EM2000}/pc/db/new/BOX.DB"                     # box: NRSUINI = capi presenti
CMD_FOTOGRAFIA = "XAUTHORITY=/root/.Xauthority nice -n 19 xwd -root -display :0 -silent | nice -n 19 gzip -1"


class LettoreEM2000(LettoreImpianto):

    def __init__(self, host, porta=22, utente="root", chiave=None, password=None,
                 known_hosts=None, timeout=20):
        self.host, self.porta, self.utente = host, int(porta or 22), utente
        self.chiave, self.password = chiave, password
        self.known_hosts = known_hosts
        self.timeout = timeout
        self._client = None
        self._camp = schermo.Campionario()

    # ── connessione ────────────────────────────────────────────────────────
    def _ssh(self):
        import paramiko
        if self._client and self._client.get_transport() and self._client.get_transport().is_active():
            return self._client
        c = paramiko.SSHClient()
        if self.known_hosts and os.path.exists(self.known_hosts):
            c.load_host_keys(self.known_hosts)
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())   # memorizzata al primo collegamento
        c.connect(self.host, port=self.porta, username=self.utente,
                  key_filename=self.chiave or None, password=None if self.chiave else self.password,
                  look_for_keys=False, allow_agent=False, timeout=self.timeout,
                  banner_timeout=self.timeout, auth_timeout=self.timeout)
        if self.known_hosts:
            os.makedirs(os.path.dirname(self.known_hosts), exist_ok=True)
            c.save_host_keys(self.known_hosts)
        self._client = c
        return c

    def _esegui(self, comando):
        _, out, err = self._ssh().exec_command(comando, timeout=self.timeout * 3)
        dati = out.read()
        if out.channel.recv_exit_status() != 0:
            raise RuntimeError(f"comando fallito sul PC: {err.read().decode(errors='replace')[:200]}")
        return dati

    def _leggi_file(self, percorso):
        with self._ssh().open_sftp() as sftp, sftp.open(percorso, "rb") as f:
            return f.read()

    def chiudi(self):
        if self._client:
            self._client.close()
            self._client = None

    # ── letture ────────────────────────────────────────────────────────────
    def fotografa(self):
        dati = self._esegui(CMD_FOTOGRAFIA)        # errori qui: il PC non risponde
        try:
            img = schermo.decodifica_xwd(gzip.decompress(dati))
        except Exception as e:                     # il PC risponde, ma la fotografia non si legge
            return None, LetturaSchermo(fase=SCONOSCIUTA, stato=f"fotografia non leggibile ({e})")
        return img, schermo.leggi(img, self._camp)

    def orari_pasti(self):
        """Orari dei pasti impostati su EM2000 (le righe vuote valgono 00:00 e vengono ignorate)."""
        orari = []
        for r in paradox.leggi(self._leggi_file(ORARI_DB)):
            h, m = r.get("TIMORA") or 0, r.get("TIMMIN") or 0
            if h or m:
                orari.append(time(h, m))
        return sorted(set(orari))

    def parametri(self):
        """Brix del siero (COMPO.DB) e % del siero nelle ricette che lo usano (RICETTECOMPO.DB): sono
        i valori che l'operatore cambia sul PC a ogni carico di siero."""
        siero = next((c for c in paradox.leggi(self._leggi_file(COMPO_DB))
                      if (c.get("NOME") or "").strip().upper() == "SIERO"), None)
        if siero is None:
            return {}
        nomi = {r["NR"]: (r.get("NOME") or "").strip() or f"ricetta {r['NR']}"
                for r in paradox.leggi(self._leggi_file(RICETTE_DB)) if r.get("NR")}
        perc = {}
        for r in paradox.leggi(self._leggi_file(RICETTECOMPO_DB)):
            if r.get("NRRICETTA") and r.get("NRCOMPO") == siero["NR"] and r.get("PER"):
                perc[nomi.get(r["NRRICETTA"], f"ricetta {r['NRRICETTA']}")] = round(r["PER"], 2)
        brix = siero.get("PERSECCO")
        rapporto = {nome: r for nome, _, _, r in self._ricette().values() if r}
        return {"brix": round(brix, 2) if brix is not None else None, "siero": perc, "rapporto": rapporto}

    def capi_per_box(self):
        """Capi per box da BOX.DB (NR, NRSUINI). Ci sono anche righe vecchie con numeri oltre i box
        reali: le filtra chi confronta, che conosce i box dell'allevamento."""
        return {int(r["NR"]): int(r.get("NRSUINI") or 0)
                for r in paradox.leggi(self._leggi_file(BOX_DB)) if r.get("NR")}

    def _ricette(self):
        """{nr: (nome, componenti, secondi di miscelazione, rapporto)} dalle tabelle del PC. Il rapporto
        (RAPPBAGNATO, es. 32 = "10:32") è quanti kg di liquido ogni 10 kg di sostanza secca."""
        compo = {c["NR"]: (c.get("NOME") or "").strip().upper() for c in paradox.leggi(self._leggi_file(COMPO_DB))}
        per_ricetta = {}
        for r in paradox.leggi(self._leggi_file(RICETTECOMPO_DB)):
            if r.get("NRRICETTA") and r.get("PER"):
                per_ricetta.setdefault(r["NRRICETTA"], set()).add(compo.get(r["NRCOMPO"]))
        out = {}
        for r in paradox.leggi(self._leggi_file(RICETTE_DB)):
            if r.get("NR") and per_ricetta.get(r["NR"]):
                out[r["NR"]] = ((r.get("NOME") or "").strip() or f"ricetta {r['NR']}", per_ricetta[r["NR"]],
                                (r.get("TIMMIXMIN") or 0) * 60 + (r.get("TIMMIXSEC") or 0), r.get("RAPPBAGNATO"))
        return out

    def ricetta_in_uso(self, lettura):
        """Ricetta i cui componenti sono le righe normali della tabella (es. SIERO + COCLEA 1 = «ricetta 2
        siero»); più ricette con gli stessi componenti: quella con il numero più basso. None se non si sa.
        {"nome", "durata_s", "rapporto"}"""
        nomi_tabella = {"SIERO" if r["comp"] == "siero" else f"COCLEA {r['coclea']}"
                        for r in lettura.righe if not r["sos"] and r["comp"] in ("siero", "farina")}
        if not nomi_tabella:
            return None
        for nr, (nome, comp, durata, rapporto) in sorted(self._ricette().items()):
            if comp == nomi_tabella:
                return {"nome": nome, "durata_s": durata or None, "rapporto": rapporto}
        return None

    def durata_miscelazione(self, lettura):
        """Tempo di miscelazione (Ricette.DB, TIMMIXMIN/TIMMIXSEC) della ricetta in uso, None se non si sa."""
        r = self.ricetta_in_uso(lettura)
        return r["durata_s"] if r else None

    def controllo(self):
        try:
            img, lettura = self.fotografa()
            png = None
            if img is not None:
                b = io.BytesIO()
                img.save(b, "PNG")
                png = b.getvalue()
            return EsitoControllo(raggiungibile=True, lettura=lettura, orari=self.orari_pasti(), immagine_png=png)
        except Exception as e:   # PC spento, rete assente, EM2000 chiuso...
            self.chiudi()
            return EsitoControllo(raggiungibile=False, errore=f"{type(e).__name__}: {e}")
