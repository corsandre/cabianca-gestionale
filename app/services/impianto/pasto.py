"""Segue un pasto lettura per lettura dello schermo ed emette eventi (indipendente dal tipo di impianto).

Regole
- Il pasto inizia alla prima lettura fuori da "attesa orario" e finisce quando l'impianto torna in
  attesa. Le linee si susseguono: una linea finisce quando lo schermo passa alla linea successiva
  (o il pasto finisce).
- Valori di una linea: si raccolgono solo dalle fasi in cui il dosaggio è concluso (dalla
  miscelazione in poi) e solo da letture coerenti (acqua + siero + farina = totale). Il valore
  finale è quello letto più volte; è "confermato" se compare in almeno MIN_CONFERME letture.
  Nessuna lettura valida = evento linea_non_letta (la linea resta da inserire o stimata).
- Siero insufficiente: siero reale sotto il teorico di oltre SOGLIA_SIERO_Q (cisterna finita).
- Stato sconosciuto: una frase di stato mai vista per 2 letture di fila (va mandata la fotografia).
- Fase bloccata: la stessa fase dura più del suo limite (LIMITI_FASE_MIN).
"""
import collections
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Optional

from .base import (ATTESA_ORARIO, ATTESA_INIZIO, PREPARAZIONE, STABILIZZAZIONE, MISCELAZIONE,
                   RIEMPIMENTO, DISTRIBUZIONE, LAVAGGIO, ATTESA_SVUOTAMENTO, SVUOTAMENTO,
                   SCONOSCIUTA, FASI_DOSAGGIO_CONCLUSO, LetturaSchermo)

MIN_CONFERME = 2
SOGLIA_SIERO_Q = 0.05
LIMITI_FASE_MIN = {ATTESA_INIZIO: 10, PREPARAZIONE: 20, STABILIZZAZIONE: 10, MISCELAZIONE: 12,
                   RIEMPIMENTO: 10, DISTRIBUZIONE: 25, LAVAGGIO: 20, ATTESA_SVUOTAMENTO: 10, SVUOTAMENTO: 10}
# fasi che aprono una linea nuova. Non "attesa inizio ciclo": lì lo schermo mostra ancora la linea
# del pasto precedente.
FASI_INIZIO_LINEA = {PREPARAZIONE, STABILIZZAZIONE}

PASTO_INIZIATO, PASTO_CONCLUSO = "pasto_iniziato", "pasto_concluso"
LINEA_INIZIATA, LINEA_CONCLUSA, LINEA_NON_LETTA = "linea_iniziata", "linea_conclusa", "linea_non_letta"
SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA = "siero_insufficiente", "stato_sconosciuto", "fase_bloccata"
ANOMALIE = {LINEA_NON_LETTA, SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA}


@dataclass
class Evento:
    tipo: str
    istante: datetime
    pasto: Optional[time] = None
    linea: Optional[int] = None
    dati: dict = field(default_factory=dict)
    lettura: Optional[LetturaSchermo] = None

    @property
    def anomalia(self):
        return self.tipo in ANOMALIE


class TracciaPasto:

    def __init__(self):
        self._azzera()

    def _azzera(self):
        self.in_corso = False
        self.pasto = None
        self.linea = None
        self.valori = []            # [(reale, teorico)] letture valide della linea corrente
        self.fase = None
        self.fase_dal = None
        self.fase_segnalata = False
        self.sconosciute = 0

    def _chiudi_linea(self, istante, lettura):
        eventi = []
        if self.linea is None:
            return eventi
        if not self.valori:
            eventi.append(Evento(LINEA_NON_LETTA, istante, self.pasto, self.linea, lettura=lettura))
        else:
            conteggio = collections.Counter(tuple(sorted(r.items())) for r, _ in self.valori)
            reale_t, conferme = conteggio.most_common(1)[0]
            reale = dict(reale_t)
            teorico = next(t for r, t in self.valori if tuple(sorted(r.items())) == reale_t)
            eventi.append(Evento(LINEA_CONCLUSA, istante, self.pasto, self.linea, lettura=lettura, dati={
                "reale": reale, "teorico": teorico, "conferme": conferme,
                "confermato": conferme >= MIN_CONFERME}))
            if teorico.get("siero") is not None and reale["siero"] < teorico["siero"] - SOGLIA_SIERO_Q:
                eventi.append(Evento(SIERO_INSUFFICIENTE, istante, self.pasto, self.linea, lettura=lettura,
                                     dati={"reale": reale["siero"], "teorico": teorico["siero"]}))
        self.linea, self.valori = None, []
        return eventi

    def aggiorna(self, istante, lettura):
        """Elabora una lettura (istante = ora reale della fotografia) e restituisce gli eventi."""
        eventi = []
        # stato mai visto: segnalato alla seconda lettura di fila (una sola lettura può essere un
        # fotogramma a metà aggiornamento)
        if lettura.fase == SCONOSCIUTA:
            self.sconosciute += 1
            if self.sconosciute == 2:
                eventi.append(Evento(STATO_SCONOSCIUTO, istante, self.pasto, self.linea, lettura=lettura,
                                     dati={"stato": lettura.stato}))
            return eventi
        self.sconosciute = 0

        if not self.in_corso:
            if lettura.fase == ATTESA_ORARIO:
                return eventi
            self.in_corso, self.pasto = True, lettura.pasto_attuale
            eventi.append(Evento(PASTO_INIZIATO, istante, self.pasto, lettura=lettura))
        elif lettura.fase == ATTESA_ORARIO:
            eventi += self._chiudi_linea(istante, lettura)
            eventi.append(Evento(PASTO_CONCLUSO, istante, self.pasto, lettura=lettura))
            self._azzera()
            return eventi

        if self.pasto is None and lettura.pasto_attuale is not None:
            self.pasto = lettura.pasto_attuale      # orario non leggibile alla prima lettura: preso appena possibile
        if (lettura.linea is not None and lettura.linea != self.linea and lettura.fase != ATTESA_INIZIO
                and (self.linea is None or lettura.fase in FASI_INIZIO_LINEA)):
            eventi += self._chiudi_linea(istante, lettura)
            self.linea = lettura.linea
            eventi.append(Evento(LINEA_INIZIATA, istante, self.pasto, self.linea, lettura=lettura))

        if lettura.fase in FASI_DOSAGGIO_CONCLUSO and lettura.linea == self.linea and lettura.tabella_coerente:
            self.valori.append((dict(lettura.reale), dict(lettura.teorico)))

        # fase bloccata
        if lettura.fase != self.fase:
            self.fase, self.fase_dal, self.fase_segnalata = lettura.fase, istante, False
        else:
            limite = LIMITI_FASE_MIN.get(self.fase)
            durata = (istante - self.fase_dal).total_seconds() / 60
            if limite and durata > limite and not self.fase_segnalata:
                self.fase_segnalata = True
                eventi.append(Evento(FASE_BLOCCATA, istante, self.pasto, self.linea, lettura=lettura,
                                     dati={"fase": self.fase, "minuti": round(durata)}))
        return eventi
