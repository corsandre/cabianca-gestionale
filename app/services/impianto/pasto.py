"""Segue un pasto lettura per lettura dello schermo ed emette eventi (indipendente dal tipo di impianto).

Regole
- Il pasto inizia alla prima lettura fuori da "attesa orario" e finisce quando l'impianto torna in
  attesa. Le linee si susseguono: una linea finisce quando lo schermo passa alla linea successiva
  (o il pasto finisce).
- Valori di una linea: si raccolgono solo dalle fasi in cui il dosaggio è concluso (dalla
  miscelazione in poi) e solo da letture coerenti (acqua + siero + farina = totale). Il valore
  finale è quello letto più volte; è "confermato" se compare in almeno MIN_CONFERME letture.
  Nessuna lettura valida = evento linea_non_letta (la linea resta da inserire o stimata).
- Sostituzioni (su EM2000 le righe "SOS"): un componente finito durante il dosaggio viene completato
  da altro. Siero finito → acqua (la parte acqua del siero) + farina (la sua sostanza secca); silos
  finito → un'altra coclea. Evento siero_finito / silos_finito una volta per pasto per cisterna o
  silos, appena il dosaggio è concluso (valori definitivi), con l'istante in cui la sostituzione è
  comparsa e finito_ora = il componente ha dato qualcosa prima di finire (altrimenti era già vuoto
  dall'inizio). La farina della linea resta la somma di tutte le coclee.
- A fine linea, "piene": siero e coclee che hanno dato la dose piena (servono a capire che una
  cisterna o un silos vuoti sono stati ricaricati).
- Siero o farina insufficiente: a fine linea reale sotto il teorico di oltre SOGLIA_Q senza una
  sostituzione che lo spieghi.
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
SOGLIA_SIERO_Q = SOGLIA_Q = 0.05
LIMITI_FASE_MIN = {ATTESA_INIZIO: 10, PREPARAZIONE: 20, STABILIZZAZIONE: 10, MISCELAZIONE: 12,
                   RIEMPIMENTO: 10, DISTRIBUZIONE: 25, LAVAGGIO: 20, ATTESA_SVUOTAMENTO: 10, SVUOTAMENTO: 10}
# fasi che aprono una linea nuova. Non "attesa inizio ciclo": lì lo schermo mostra ancora la linea
# del pasto precedente.
FASI_INIZIO_LINEA = {PREPARAZIONE, STABILIZZAZIONE}

PASTO_INIZIATO, PASTO_CONCLUSO = "pasto_iniziato", "pasto_concluso"
LINEA_INIZIATA, LINEA_CONCLUSA, LINEA_NON_LETTA = "linea_iniziata", "linea_conclusa", "linea_non_letta"
SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA = "siero_insufficiente", "stato_sconosciuto", "fase_bloccata"
SILOS_FINITO, SIERO_FINITO, FARINA_INSUFFICIENTE = "silos_finito", "siero_finito", "farina_insufficiente"
ANOMALIE = {LINEA_NON_LETTA, SIERO_INSUFFICIENTE, STATO_SCONOSCIUTO, FASE_BLOCCATA, SILOS_FINITO, SIERO_FINITO,
            FARINA_INSUFFICIENTE}


def _chiave(riga):
    """Cisterna del siero o silos a cui si riferisce una riga sostituita."""
    return ("siero",) if riga["comp"] == "siero" else ("silos", riga["coclea"])


def esaurimenti(lettura):
    """{chiave: dati} dei componenti sostituiti in questa lettura (vedi docstring del modulo)."""
    out = {}
    for sostituita, sos in lettura.sostituzioni:
        if sostituita["comp"] not in ("siero", "farina"):
            continue
        d = out.setdefault(_chiave(sostituita), {
            "coclea": sostituita["coclea"], "reale": sostituita["reale"], "teorico": sostituita["teorico"],
            "finito_ora": bool(sostituita["reale"]), "con": []})
        d["con"].append({"comp": sos["comp"], "coclea": sos["coclea"], "reale": sos["reale"]})
    return out


def piene(lettura):
    """Siero e coclee che in questa lettura hanno dato la dose piena (riga normale, reale ≈ teorico)."""
    return sorted({_chiave(r) for r in lettura.righe if not r["sos"] and r["comp"] in ("siero", "farina")
                   and r["teorico"] and r["reale"] is not None and r["reale"] >= r["teorico"] - SOGLIA_Q})


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
        self.valori = []            # [(reale, teorico, lettura)] letture valide della linea corrente
        self.esauriti_segnalati = set()   # cisterna/silos già segnalati in questo pasto
        self.sos_visti = {}         # chiave -> istante in cui la sostituzione è comparsa (linea corrente)
        self.ultima = None          # ultima lettura della linea corrente
        self.fase = None
        self.fase_dal = None
        self.fase_segnalata = False
        self.sconosciute = 0

    def _esaurimenti(self, istante, lettura):
        """Eventi siero/silos finito per le sostituzioni viste in questa linea e non ancora segnalate."""
        eventi = []
        for chiave, d in esaurimenti(lettura).items():
            if chiave in self.esauriti_segnalati:
                continue
            self.esauriti_segnalati.add(chiave)
            d["dal"] = self.sos_visti.get(chiave, istante)
            eventi.append(Evento(SIERO_FINITO if chiave[0] == "siero" else SILOS_FINITO, istante, self.pasto,
                                 self.linea, lettura=lettura, dati=d))
        return eventi

    def _chiudi_linea(self, istante, lettura):
        eventi = []
        if self.linea is None:
            return eventi
        if self.ultima is not None:     # sostituzioni mai viste a dosaggio concluso (es. linea non letta)
            eventi += self._esaurimenti(istante, self.ultima)
        if not self.valori:
            eventi.append(Evento(LINEA_NON_LETTA, istante, self.pasto, self.linea, lettura=lettura))
        else:
            conteggio = collections.Counter(tuple(sorted(r.items())) for r, _, _ in self.valori)
            reale_t, conferme = conteggio.most_common(1)[0]
            reale = dict(reale_t)
            teorico, scelta = next((t, x) for r, t, x in self.valori if tuple(sorted(r.items())) == reale_t)
            sostituiti = {s["comp"] for s, _ in scelta.sostituzioni}
            eventi.append(Evento(LINEA_CONCLUSA, istante, self.pasto, self.linea, lettura=lettura, dati={
                "reale": reale, "teorico": teorico, "silos": scelta.farina_per_silos, "piene": piene(scelta),
                "conferme": conferme, "confermato": conferme >= MIN_CONFERME}))
            for comp, tipo in (("siero", SIERO_INSUFFICIENTE), ("farina", FARINA_INSUFFICIENTE)):
                if (comp not in sostituiti and teorico.get(comp) is not None
                        and reale[comp] < teorico[comp] - SOGLIA_Q):
                    eventi.append(Evento(tipo, istante, self.pasto, self.linea, lettura=lettura,
                                         dati={"reale": reale[comp], "teorico": teorico[comp]}))
        self.linea, self.valori, self.sos_visti, self.ultima = None, [], {}, None
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

        if lettura.linea == self.linea and self.linea is not None:
            self.ultima = lettura
            for chiave in esaurimenti(lettura):
                self.sos_visti.setdefault(chiave, istante)
            if lettura.fase in FASI_DOSAGGIO_CONCLUSO:
                if lettura.tabella_coerente:
                    self.valori.append((dict(lettura.reale), dict(lettura.teorico), lettura))
                eventi += self._esaurimenti(istante, lettura)

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
