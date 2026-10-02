"""Collegamento opzionale all'impianto di alimentazione (comune a tutti i tipi di impianto).

Modalità (impostazione `impianto_modalita`):
- manuale    → nessuna connessione all'impianto: il gestionale funziona come senza impianto
               collegato (i consumi si inseriscono a mano). È il default: un'azienda senza impianto
               collegabile non vede differenze.
- verifica   → connessione attiva (controllo periodico, letture durante i pasti, allarmi), ma i
               consumi letti sono solo PROPOSTE da approvare a mano prima di entrare nel gestionale.
- automatico → come verifica, ma i consumi letti entrano direttamente come dati reali.

Ogni marca di impianto ha il suo lettore (es. em2000/) che implementa LettoreImpianto: il resto del
gestionale parla solo con questa interfaccia.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import Optional

MANUALE, VERIFICA, AUTOMATICO = "manuale", "verifica", "automatico"
MODALITA = (MANUALE, VERIFICA, AUTOMATICO)
NOMI_MODALITA = {MANUALE: "Manuale", VERIFICA: "Automatico con verifica", AUTOMATICO: "Automatico"}

# fasi del ciclo di preparazione/distribuzione di una linea, comuni a tutti gli impianti
ATTESA_ORARIO = "attesa_orario"          # impianto fermo in attesa del prossimo pasto
ATTESA_INIZIO = "attesa_inizio"
PREPARAZIONE = "preparazione"            # dosaggio dei componenti della ricetta
STABILIZZAZIONE = "stabilizzazione"
MISCELAZIONE = "miscelazione"            # da qui i quantitativi della linea sono definitivi
RIEMPIMENTO = "riempimento"
DISTRIBUZIONE = "distribuzione"
LAVAGGIO = "lavaggio"
ATTESA_SVUOTAMENTO = "attesa_svuotamento"
SVUOTAMENTO = "svuotamento"
SCONOSCIUTA = "sconosciuta"              # stato mai visto: va segnalato con la fotografia
FASI_DOSAGGIO_CONCLUSO = {MISCELAZIONE, RIEMPIMENTO, DISTRIBUZIONE, LAVAGGIO, ATTESA_SVUOTAMENTO, SVUOTAMENTO}
NOMI_FASI = {
    ATTESA_ORARIO: "in attesa del prossimo pasto", ATTESA_INIZIO: "pasto in partenza",
    PREPARAZIONE: "preparazione della ricetta", STABILIZZAZIONE: "stabilizzazione", MISCELAZIONE: "miscelazione",
    RIEMPIMENTO: "riempimento del tubo", DISTRIBUZIONE: "distribuzione ai box", LAVAGGIO: "lavaggio",
    ATTESA_SVUOTAMENTO: "attesa svuotamento", SVUOTAMENTO: "svuotamento", SCONOSCIUTA: "stato sconosciuto",
}

COMPONENTI = ("acqua", "siero", "farina")


@dataclass
class LetturaSchermo:
    """Quello che si legge in un istante dallo schermo dell'impianto. Campi None = non leggibili."""
    ora_pc: Optional[time] = None            # orologio dell'impianto (può non coincidere con l'ora reale)
    pasto_attuale: Optional[time] = None     # orario del pasto in corso o dell'ultimo fatto
    prossimo_pasto: Optional[time] = None
    linea: Optional[int] = None              # linea in preparazione/distribuzione
    stato: Optional[str] = None              # frase di stato così come scritta dall'impianto
    fase: str = SCONOSCIUTA
    box_in_distribuzione: Optional[int] = None
    teorico: dict = field(default_factory=dict)   # componente -> quintali (+ "totale")
    reale: dict = field(default_factory=dict)
    tabella_coerente: bool = False           # reale: acqua + siero + farina = totale, tutto in quintali
    # righe della ricetta così come sono sullo schermo: {"comp": acqua/siero/farina, "coclea": n o None,
    # "sos": bool, "teorico", "reale"} (quintali). Una riga "sos" è entrata al posto della riga normale più
    # vicina sopra di lei, finita durante il dosaggio (es. siero → acqua + farina, coclea 1 → coclea 3).
    righe: list = field(default_factory=list)
    righe_sconosciute: list = field(default_factory=list)   # righe della ricetta con nome mai visto

    @property
    def sostituzioni(self):
        """[(riga sostituita, riga che la sostituisce)]"""
        out, normale = [], None
        for r in self.righe:
            if r["sos"]:
                if normale is not None:
                    out.append((normale, r))
            else:
                normale = r
        return out

    def problemi(self):
        """Cosa non si è riuscito a leggere in una schermata riconosciuta (stato noto): serve a
        segnalare con la fotografia schermate nuove o cambiate, da insegnare al lettore."""
        if self.fase == SCONOSCIUTA:
            return []          # schermata non riconosciuta: la segnala già "stato sconosciuto"
        p = []
        if self.ora_pc is None:
            p.append("ora del PC illeggibile")
        if self.prossimo_pasto is None:
            p.append("prossimo pasto illeggibile")
        if self.fase != ATTESA_ORARIO:
            if self.pasto_attuale is None:
                p.append("orario del pasto in corso illeggibile")
            if self.linea is None:
                p.append("linea illeggibile")
        for nome in self.righe_sconosciute:
            p.append(f"riga della ricetta mai vista: «{nome}»")
        if not self.righe:
            p.append("tabella della ricetta illeggibile")
        elif any(r["reale"] is None or r["teorico"] is None for r in self.righe):
            p.append("valori della ricetta illeggibili")
        if self.reale.get("totale") is None:
            p.append("totale della ricetta illeggibile")
        return list(dict.fromkeys(p))

    @property
    def farina_per_silos(self):
        """coclea (= silos) → quintali di farina caricati, sommando tutte le sue righe"""
        out = {}
        for r in self.righe:
            if r["comp"] == "farina" and r["reale"] is not None:
                out[r["coclea"]] = round(out.get(r["coclea"], 0) + r["reale"], 4)
        return out

    @property
    def in_attesa(self):
        return self.fase == ATTESA_ORARIO


@dataclass
class EsitoControllo:
    """Risultato del controllo periodico dell'impianto (heartbeat)."""
    raggiungibile: bool
    lettura: Optional[LetturaSchermo] = None
    orari: list = field(default_factory=list)    # orari dei pasti impostati sull'impianto (time)
    errore: Optional[str] = None
    immagine_png: Optional[bytes] = None


class LettoreImpianto:
    """Interfaccia che ogni tipo di impianto deve implementare."""

    def controllo(self) -> EsitoControllo:
        """Verifica che l'impianto risponda e legge stato, orari e una fotografia dello schermo."""
        raise NotImplementedError

    def fotografa(self):
        """(immagine PIL, LetturaSchermo) dello schermo in questo momento."""
        raise NotImplementedError

    def orari_pasti(self) -> list:
        raise NotImplementedError

    def parametri(self) -> dict:
        """Impostazioni dell'impianto da sorvegliare (es. Brix del siero e sua % nelle ricette).
        {"brix": float o None, "siero": {nome ricetta: %}}; {} se il tipo di impianto non lo prevede."""
        return {}

    def chiudi(self):
        pass
