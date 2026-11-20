#!/usr/bin/env python3
"""
Stato della VPS per la pagina Impostazioni del gestionale (riquadro «Server»).

Gira SULLA VPS (non nel container), da cron ogni 15 minuti, come utente del gruppo docker:

    */15 * * * * /usr/bin/python3 /home/andrea/cabianca-gestionale/scripts/stato_server.py

Scrive data/stato_server.json (ultima lettura) e data/stato_server_storia.json (un punto al giorno, per
calcolare quanto cresce il disco). Solo letture: non cancella e non pulisce niente.

Dal container il gestionale vede già disco, memoria e le sue cartelle; questo script aggiunge quello che da
lì non si vede: Docker (immagini, cache di build), memoria di ogni container, gli altri servizi (ordini,
Postiz) e i log di sistema. Solo libreria standard di Python.
"""
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import date, datetime

CASA = os.path.expanduser("~")
GESTIONALE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATI = os.environ.get("STATO_SERVER_DATI") or os.path.join(GESTIONALE, "data")   # cartella diversa solo per provarlo
ALTRI_SERVIZI = {"ordini": os.path.join(CASA, "cabianca-ordini"), "social": os.path.join(CASA, "cabianca-social")}
GIORNI_STORIA = 120

_UNITA = {"b": 1, "kb": 1e3, "mb": 1e6, "gb": 1e9, "tb": 1e12,
          "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def byte_da_testo(testo):
    """'12.22GB' → 12220000000, '93.92MiB' → 98480...; '777.8MB (6%)' → solo il numero. 0 se non si legge."""
    m = re.match(r"\s*([\d.]+)\s*([a-zA-Z]+)", testo or "")
    if not m:
        return 0
    return int(float(m.group(1)) * _UNITA.get(m.group(2).lower(), 0))


def _comando(*args, timeout=60):
    try:
        esito = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return esito.stdout if esito.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def dimensione(percorso):
    """Byte occupati da una cartella (du), 0 se non c'è."""
    if not os.path.exists(percorso):
        return 0
    try:   # du esce con errore se qualche file non si può leggere, ma il totale lo stampa lo stesso
        uscita = subprocess.run(["du", "-sb", percorso], capture_output=True, text=True, timeout=300).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    return int(uscita.split()[0]) if uscita.strip() else 0


def disco():
    st = os.statvfs("/")
    totale, libero = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    return {"totale": totale, "libero": libero, "usato": totale - st.f_bfree * st.f_frsize}


def memoria():
    info = {}
    with open("/proc/meminfo") as f:
        for riga in f:
            k, v = riga.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
    return {"totale": info.get("MemTotal", 0), "disponibile": info.get("MemAvailable", 0),
            "swap_totale": info.get("SwapTotal", 0), "swap_usata": info.get("SwapTotal", 0) - info.get("SwapFree", 0)}


def docker_spazio():
    """Immagini, container, volumi e cache di build: dimensione e parte recuperabile."""
    nomi = {"Images": "immagini", "Containers": "container", "Local Volumes": "volumi", "Build Cache": "cache_build"}
    out = {}
    for riga in _comando("docker", "system", "df", "--format", "{{json .}}").splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        if d.get("Type") in nomi:
            out[nomi[d["Type"]]] = {"usato": byte_da_testo(d.get("Size")), "recuperabile": byte_da_testo(d.get("Reclaimable"))}
    return out


def container():
    out = []
    for riga in _comando("docker", "stats", "--no-stream", "--format", "{{json .}}").splitlines():
        try:
            d = json.loads(riga)
        except ValueError:
            continue
        out.append({"nome": d.get("Name", "?"), "memoria": byte_da_testo((d.get("MemUsage") or "").split("/")[0]),
                    "cpu": float((d.get("CPUPerc") or "0").rstrip("%") or 0)})
    return sorted(out, key=lambda c: -c["memoria"])


def log_sistema():
    """Spazio dei log di systemd ('... take up 94.8M in the file system.')."""
    m = re.search(r"take up ([\d.]+\s*[KMGT]?)", _comando("journalctl", "--disk-usage"))
    if not m:
        return 0
    v = m.group(1).replace(" ", "")
    return byte_da_testo(v + "iB") if v[-1] in "KMGT" else byte_da_testo(v + "B")


def raccogli():
    with open("/proc/loadavg") as f:
        carico = [float(x) for x in f.read().split()[:3]]
    with open("/proc/uptime") as f:
        acceso_da = int(float(f.read().split()[0]))
    servizi = {nome: dimensione(p) for nome, p in ALTRI_SERVIZI.items()}
    return {"aggiornato": datetime.now().isoformat(timespec="seconds"), "disco": disco(), "memoria": memoria(),
            "carico": carico, "cpu": os.cpu_count(), "acceso_da_s": acceso_da, "docker": docker_spazio(),
            "container": container(), "servizi": servizi, "log_sistema": log_sistema()}


def _scrivi(nome, dati):
    """Scrittura atomica (il gestionale non legge mai un file a metà)."""
    fd, tmp = tempfile.mkstemp(dir=DATI, prefix="." + nome)
    with os.fdopen(fd, "w") as f:
        json.dump(dati, f, indent=1)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(DATI, nome))


def aggiorna_storia(stato):
    percorso = os.path.join(DATI, "stato_server_storia.json")
    try:
        with open(percorso) as f:
            storia = json.load(f)
    except (OSError, ValueError):
        storia = []
    oggi = date.today().isoformat()
    storia = [p for p in storia if p.get("data") != oggi]
    storia.append({"data": oggi, "disco_usato": stato["disco"]["usato"],
                   "cache_build": stato["docker"].get("cache_build", {}).get("usato", 0)})
    _scrivi("stato_server_storia.json", sorted(storia, key=lambda p: p["data"])[-GIORNI_STORIA:])


if __name__ == "__main__":
    inizio = time.time()
    stato = raccogli()
    stato["durata_s"] = round(time.time() - inizio, 1)
    _scrivi("stato_server.json", stato)
    aggiorna_storia(stato)
