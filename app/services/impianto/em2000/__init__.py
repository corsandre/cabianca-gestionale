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

from ..base import LettoreImpianto, EsitoControllo
from . import paradox, schermo

EM2000 = "/root/.wine/drive_d/em2000"
ORARI_DB = f"{EM2000}/pc/db/new/ORARI.DB"
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
        img = schermo.decodifica_xwd(gzip.decompress(self._esegui(CMD_FOTOGRAFIA)))
        return img, schermo.leggi(img, self._camp)

    def orari_pasti(self):
        """Orari dei pasti impostati su EM2000 (le righe vuote valgono 00:00 e vengono ignorate)."""
        orari = []
        for r in paradox.leggi(self._leggi_file(ORARI_DB)):
            h, m = r.get("TIMORA") or 0, r.get("TIMMIN") or 0
            if h or m:
                orari.append(time(h, m))
        return sorted(set(orari))

    def controllo(self):
        try:
            img, lettura = self.fotografa()
            png = io.BytesIO()
            img.save(png, "PNG")
            return EsitoControllo(raggiungibile=True, lettura=lettura, orari=self.orari_pasti(),
                                  immagine_png=png.getvalue())
        except Exception as e:   # PC spento, rete assente, EM2000 chiuso...
            self.chiudi()
            return EsitoControllo(raggiungibile=False, errore=f"{type(e).__name__}: {e}")
