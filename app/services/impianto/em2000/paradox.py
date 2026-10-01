"""Lettore minimale di tabelle Paradox (.DB) di EM2000, in sola lettura e senza librerie esterne.

Formato: header (dimensione record, dimensione header, dimensione blocco, numero campi, tipi e
dimensioni dei campi, nomi) seguito da blocchi di dati. Ogni blocco ha 6 byte di intestazione
(blocco successivo, precedente, offset dell'ultimo record) e poi i record. I numeri sono
big-endian con il bit più alto invertito per i positivi (tutti i bit invertiti per i negativi);
tutti zero = vuoto.
"""
import struct
from datetime import date, datetime, timedelta

TIPI = {1: "alfa", 2: "data", 3: "short", 4: "long", 5: "valuta", 6: "numero", 9: "logico",
        0x0C: "memo", 0x14: "ora", 0x15: "timestamp", 0x16: "autoinc"}


def _intero(b):
    if not any(b):
        return None
    v = int.from_bytes(b, "big")
    bit = 1 << (len(b) * 8 - 1)
    return v - bit if v & bit else -(v ^ ((1 << (len(b) * 8)) - 1))


def _double(b):
    if not any(b):
        return None
    b = bytearray(b)
    if b[0] & 0x80:
        b[0] &= 0x7F
    else:
        b = bytearray(x ^ 0xFF for x in b)
    return struct.unpack(">d", bytes(b))[0]


def timestamp(ms):
    """Timestamp Paradox (millisecondi dal 01/01/0001, con un giorno di scarto) → datetime."""
    return datetime(1, 1, 1) + timedelta(milliseconds=ms) - timedelta(days=1) if ms else None


def leggi(dati, codifica="cp1252"):
    """Righe della tabella (lista di dict) dai byte di un file .DB."""
    rec_size, head_size = struct.unpack_from("<HH", dati, 0)
    blocco = dati[5] * 1024
    n_rec = struct.unpack_from("<I", dati, 6)[0]
    n_campi = struct.unpack_from("<H", dati, 0x21)[0]
    versione = dati[0x39]
    off = 0x78 if versione >= 5 else 0x58
    campi = [(dati[off + 2 * i], dati[off + 2 * i + 1]) for i in range(n_campi)]
    p = off + 2 * n_campi + 4 + 4 * n_campi + (261 if versione >= 0x0C else 79)
    nomi = []
    for _ in range(n_campi):
        fine = dati.index(b"\0", p)
        nomi.append(dati[p:fine].decode(codifica, "replace"))
        p = fine + 1
    righe, pos = [], head_size
    while pos + 6 <= len(dati) and len(righe) < n_rec:
        ultimo = struct.unpack_from("<h", dati, pos + 4)[0]
        if ultimo >= 0:
            for k in range(ultimo // rec_size + 1):
                r = dati[pos + 6 + k * rec_size: pos + 6 + (k + 1) * rec_size]
                riga, q = {}, 0
                for nome, (tipo, dim) in zip(nomi, campi):
                    b = r[q:q + dim]
                    q += dim
                    t = TIPI.get(tipo)
                    if t == "alfa":
                        v = b.split(b"\0")[0].decode(codifica, "replace").strip()
                    elif t in ("short", "long", "autoinc"):
                        v = _intero(b)
                    elif t in ("numero", "valuta", "timestamp"):
                        v = _double(b)
                    elif t == "data":
                        n = _intero(b)
                        v = date(1, 1, 1) + timedelta(days=n - 1) if n else None
                    elif t == "logico":
                        v = None if b[0] == 0 else bool(b[0] & 0x7F)
                    else:
                        v = b.hex()
                    riga[nome] = v
                righe.append(riga)
        pos += blocco
    return righe[:n_rec]
