"""
Compenso di soccida: il conto del ciclo e le stime a ciclo aperto.

Questo modulo contiene SOLO calcolo: funzioni pure che ricevono numeri e
restituiscono numeri. Non legge il database, non conosce Flask e non importa
niente dal resto dell'applicazione, così si può provare da solo
(tests/test_soccida.py lo confronta con l'Excel dei cicli passati).
I dati glieli passa app/services/soccida_dati.py.

Il conto (contratto con Veronesi)
---------------------------------
1. Mangime consumato = bolle + giacenza iniziale − giacenza finale (il siero non conta).
2. Carne valida = peso morto dei grassi + peso morto degli scarti contato in quota
   (50%). Peso morto degli scarti = peso vivo × (1 − calo peso, 16,38%).
   Un carico di grassi senza riscontro vale peso vivo × resa media dei carichi
   riscontrati del ciclo (o la resa di partenza, 82%, se non ce ne sono).
3. Indice di conversione = mangime consumato / carne valida.
4. Valore €/kg = percentuale della tabella di rapporto, interpolata tra le due
   righe vicine, × prezzo di partenza × (1 + premio su tabella) / 100.
   Sotto la prima riga la tabella si prolunga con il passo delle prime due righe;
   sopra l'ultima resta ferma (lì vince comunque il minimo).
5. Resa = valore × carne valida × (1 + premi da prontuario + premio extra).
6. Minimo = minimo annuo / 365 × giorni dall'ultimo giorno pagato del ciclo
   precedente all'ultimo carico (ogni giorno dell'anno è pagato una volta sola).
7. Veronesi paga il più alto tra «resa» e «minimo + siero». Il siero lo paga
   l'allevatore: al netto resta il più alto tra «resa − siero» e «minimo».
   Si arriva a premio quando resa − siero > minimo.
8. Saldo = pagato − anticipi.

Le stime
--------
A ciclo aperto quello che manca si prevede da uno Scenario (date del primo e
dell'ultimo carico, peso di uscita, resa, morti attesi, premi). Tra il primo e
l'ultimo carico i capi escono in modo regolare, quindi ogni capo mangia in media
fino a metà finestra: «giorni pieni equivalenti» = media tra i giorni che mancano
al primo carico e quelli che mancano all'ultimo.
La probabilità di premio viene da una simulazione: il conto rifatto molte volte
spostando i dati incerti (vedi Incertezze).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, replace
from datetime import date

# Tabella di rapporto del contratto: (indice di conversione, percentuale).
TABELLA_RAPPORTO = (
    (2.9, 22.3), (3.0, 20.9), (3.1, 19.5), (3.2, 18.1), (3.3, 16.7), (3.4, 15.46),
    (3.5, 14.22), (3.6, 12.98), (3.7, 11.94), (3.8, 11.12), (3.9, 10.29), (4.0, 9.46),
)


@dataclass(frozen=True)
class Contratto:
    """I numeri del contratto. Nel gestionale stanno in Impostazioni › Soccida, uno per ciclo."""
    minimo_annuo: float = 98000.0
    giorni_anno: int = 365
    prezzo_partenza: float = 1.45          # €/kg
    premio_tabella_perc: float = 20.0      # maggiorazione del prezzo di partenza
    quota_scarti_perc: float = 50.0        # quanta carne degli scarti viene contata
    calo_scarti_perc: float = 16.38        # calo peso vivo → morto degli scarti
    resa_partenza_perc: float = 82.0       # resa dei grassi finché non c'è un riscontro
    tabella: tuple = TABELLA_RAPPORTO

    @property
    def prezzo_tabella(self):
        """Prezzo che moltiplica le percentuali della tabella (1,45 × 1,20 = 1,74)."""
        return self.prezzo_partenza * (1 + self.premio_tabella_perc / 100)

    @property
    def minimo_giornaliero(self):
        return self.minimo_annuo / self.giorni_anno


# ── Il conto ────────────────────────────────────────────────────────────────

def percentuale_tabella(indice, tabella=TABELLA_RAPPORTO):
    """Percentuale della tabella di rapporto per un indice di conversione (regola 4)."""
    righe = sorted(tabella)
    if len(righe) < 2:
        raise ValueError("La tabella di rapporto deve avere almeno due righe.")
    (i0, p0), (i1, p1) = righe[0], righe[1]
    if indice <= i0:                       # meglio della prima riga: stesso passo delle prime due
        return p0 + (i0 - indice) * (p0 - p1) / (i1 - i0)
    if indice >= righe[-1][0]:             # peggio dell'ultima riga: ferma
        return righe[-1][1]
    for (a, pa), (b, pb) in zip(righe, righe[1:]):
        if a <= indice <= b:
            return pa + (pb - pa) * (indice - a) / (b - a)
    return righe[-1][1]


def valore_kg(indice, contratto):
    """€ per kg di carne valida, prima dei premi."""
    return percentuale_tabella(indice, contratto.tabella) * contratto.prezzo_tabella / 100


def minimo_ciclo(giorni, contratto):
    return contratto.minimo_giornaliero * giorni


@dataclass(frozen=True)
class Carico:
    """Un camion in uscita verso il macello (uno Spostamento di tipo uscita)."""
    capi: int
    peso_vivo_kg: float | None = None       # medio a capo, dalla bolla
    scarto: bool = False                    # categoria «scarto/sottopeso»
    capi_riscontrati: int | None = None     # dal riscontro del macello
    peso_morto_kg: float | None = None      # medio a capo, dal riscontro

    @property
    def riscontrato(self):
        return self.capi_riscontrati is not None and self.peso_morto_kg is not None


def resa_media(carichi):
    """Resa (peso morto / peso vivo) dei carichi di grassi riscontrati, o None se non ce ne sono."""
    vivo = morto = 0.0
    for c in carichi:
        if not c.scarto and c.riscontrato and c.peso_vivo_kg:
            vivo += c.capi * c.peso_vivo_kg
            morto += c.capi_riscontrati * c.peso_morto_kg
    return morto / vivo if vivo else None


@dataclass(frozen=True)
class CarnePartita:
    """Carne valida dei carichi già partiti, divisa per quanto è certa."""
    kg_riscontrati: float      # grassi con riscontro del macello: dato reale
    kg_da_riscontrare: float   # grassi senza riscontro: peso vivo × resa
    kg_scarti: float           # scarti, già in quota
    capi_grassi: int
    capi_scarti: int
    resa_usata: float          # frazione usata per i carichi da riscontrare

    @property
    def kg(self):
        return self.kg_riscontrati + self.kg_da_riscontrare + self.kg_scarti


def carne_partita(carichi, contratto, resa_perc=None):
    """Carne valida dei carichi partiti (regola 2). resa_perc forza la resa dei carichi
    senza riscontro; altrimenti si usa la media dei riscontrati o la resa di partenza."""
    resa = resa_perc / 100 if resa_perc is not None else (resa_media(carichi) or contratto.resa_partenza_perc / 100)
    risc = attesa = scarti = 0.0
    capi_g = capi_s = 0
    for c in carichi:
        if c.scarto:
            capi_s += c.capi
            scarti += c.capi * (c.peso_vivo_kg or 0) * (1 - contratto.calo_scarti_perc / 100) * contratto.quota_scarti_perc / 100
        elif c.riscontrato:
            capi_g += c.capi_riscontrati
            risc += c.capi_riscontrati * c.peso_morto_kg
        else:
            capi_g += c.capi
            attesa += c.capi * (c.peso_vivo_kg or 0) * resa
    return CarnePartita(risc, attesa, scarti, capi_g, capi_s, resa)


@dataclass(frozen=True)
class Conto:
    """Il conto del ciclo, passo per passo (stessi passaggi dell'Excel)."""
    mangime_kg: float
    carne_kg: float
    indice: float
    percentuale: float        # dalla tabella
    valore_kg: float          # €/kg
    premi_perc: float         # prontuario + extra
    resa_eur: float
    siero_eur: float
    giorni: float
    minimo_eur: float
    anticipi_eur: float

    @property
    def resa_netta_eur(self):
        """Resa meno siero: quello che si confronta con il minimo."""
        return self.resa_eur - self.siero_eur

    @property
    def margine_eur(self):
        """Quanto la resa netta supera il minimo (negativo = vince il minimo)."""
        return self.resa_netta_eur - self.minimo_eur

    @property
    def a_premio(self):
        return self.margine_eur > 0

    @property
    def pagato_eur(self):
        """Quello che paga Veronesi: il più alto tra resa e minimo + siero."""
        return max(self.resa_eur, self.minimo_eur + self.siero_eur)

    @property
    def netto_eur(self):
        """Pagato meno il siero, che resta a carico dell'allevatore."""
        return self.pagato_eur - self.siero_eur

    @property
    def saldo_eur(self):
        return self.pagato_eur - self.anticipi_eur


def conto(*, mangime_kg, carne_kg, siero_eur, giorni, contratto, premi_perc=0.0, premio_extra_perc=0.0, anticipi_eur=0.0):
    """Il conto del ciclo da mangime consumato, carne valida, siero e giorni pagati."""
    if carne_kg <= 0:
        raise ValueError("Senza carne valida il conto non si può fare.")
    indice = mangime_kg / carne_kg
    perc = percentuale_tabella(indice, contratto.tabella)
    val = perc * contratto.prezzo_tabella / 100
    premi = premi_perc + premio_extra_perc
    return Conto(
        mangime_kg=mangime_kg, carne_kg=carne_kg, indice=indice, percentuale=perc, valore_kg=val,
        premi_perc=premi, resa_eur=val * carne_kg * (1 + premi / 100), siero_eur=siero_eur,
        giorni=giorni, minimo_eur=minimo_ciclo(giorni, contratto), anticipi_eur=anticipi_eur,
    )


def indice_pareggio(c, contratto):
    """Indice di conversione sotto il quale si va a premio, a parità di carne, siero e giorni.
    None se nemmeno il miglior indice provato (2,0) basta."""
    def margine(indice):
        return valore_kg(indice, contratto) * c.carne_kg * (1 + c.premi_perc / 100) - c.siero_eur - c.minimo_eur
    basso, alto = 2.0, max(r[0] for r in contratto.tabella)
    if margine(basso) <= 0:
        return None
    if margine(alto) > 0:
        return alto
    for _ in range(60):
        meta = (basso + alto) / 2
        if margine(meta) > 0:
            basso = meta
        else:
            alto = meta
    return basso


# ── Le stime a ciclo aperto ─────────────────────────────────────────────────

def peso_da_curva(curva, eta_giorni):
    """Peso vivo (kg) a una certa età dalla curva di accrescimento [(età, peso), …]:
    interpolato tra i punti, fermo oltre l'ultimo."""
    punti = sorted(curva)
    if not punti:
        return None
    if eta_giorni <= punti[0][0]:
        return punti[0][1]
    for (e0, p0), (e1, p1) in zip(punti, punti[1:]):
        if e0 <= eta_giorni <= e1:
            return p0 + (p1 - p0) * (eta_giorni - e0) / (e1 - e0)
    return punti[-1][1]


@dataclass(frozen=True)
class Situazione:
    """I dati del ciclo a oggi, come li raccoglie soccida_dati dal gestionale."""
    oggi: date
    ultimo_giorno_pagato_prec: date        # del ciclo precedente: da lì partono i giorni del minimo
    # mangime
    mangime_bolle_kg: float                # bolle del ciclo (Consegne)
    giacenza_iniziale_kg: float
    giacenza_oggi_kg: float                # silos oggi; a ciclo finito la giacenza finale comunicata
    consumo_mangime_giorno_kg: float       # media recente, con i capi presenti oggi
    # animali
    carichi: tuple = ()                    # Carico già partiti (grassi e scarti di Veronesi)
    capi_presenti: int = 0                 # in stalla oggi, senza i suini di Fattoria Ca' Bianca
    eta_media_giorni: float = 0.0          # età media oggi, sulla scala della curva
    curva: tuple = ()                      # curva di accrescimento [(età, peso)]
    # siero
    siero_fatturato_eur: float = 0.0       # fatture del ciclo, IVA compresa
    siero_da_fatturare_t: float = 0.0      # consegnato (bolle) e non ancora in fattura
    siero_prezzo_t: float = 0.0            # €/t dell'ultima fattura, gasolio e IVA compresi
    siero_giorno_t: float = 0.0            # media recente
    anticipi_eur: float = 0.0


@dataclass(frozen=True)
class Scenario:
    """Le previsioni: lo «scenario standard» di Impostazioni, o una prova fatta dalla scheda."""
    primo_carico: date
    ultimo_carico: date
    date_confermate: bool = False          # confermate da Veronesi: meno incertezza sulle date
    peso_extra_kg: float = 0.0             # kg di peso vivo in più (o in meno) rispetto alla curva
    resa_perc: float = 83.0                # resa al macello prevista per i capi ancora da riscontrare
    morti_giorno: float = 1.0
    premi_perc: float = 8.0                # premi da prontuario
    premio_extra_perc: float = 0.0
    capi_carico: int = 130                 # capi per camion (120–135)
    carichi_giorno: int = 2


@dataclass(frozen=True)
class Variazione:
    """Spostamenti rispetto allo scenario: usati dalla simulazione e dalle «leve»."""
    giorni: float = 0.0            # tutte e due le date dei carichi, in giorni
    primo_giorni: float = 0.0      # solo il primo carico
    ultimo_giorni: float = 0.0     # solo l'ultimo carico
    peso_kg: float = 0.0
    resa_punti: float = 0.0
    capi: float = 0.0
    consumo_giorno_kg: float = 0.0
    mangime_kg: float = 0.0        # mangime in più, una tantum (errore su giacenze, o consumo extra)
    siero_t: float = 0.0
    siero_prezzo_t: float = 0.0
    premi_punti: float = 0.0


@dataclass(frozen=True)
class Stima:
    """Il conto previsto a fine ciclo, con i pezzi separati per quanto sono certi."""
    conto: Conto
    giorni_equivalenti: float      # giorni pieni di consumo che restano
    capi_macello: float            # grassi ancora da caricare
    peso_uscita_kg: float | None
    carne: CarnePartita            # carichi già partiti
    carne_futura_kg: float
    mangime_finora_kg: float
    mangime_residuo_kg: float
    siero_da_fatturare_eur: float
    siero_futuro_eur: float
    carichi_previsti: int          # camion ancora da fare
    giorni_minimi_carico: int      # giorni che servono per farli
    finestra_giorni: int           # giorni tra primo e ultimo carico


def stima(sit, sce, contratto, var=Variazione()):
    """Proietta la situazione di oggi a fine ciclo secondo lo scenario e ne fa il conto."""
    al_primo = max(0.0, (sce.primo_carico - sit.oggi).days + var.giorni + var.primo_giorni)
    all_ultimo = max(al_primo, (sce.ultimo_carico - sit.oggi).days + var.giorni + var.ultimo_giorni)
    in_stalla = sit.capi_presenti > 0
    # giorni pieni equivalenti: tutti mangiano fino al primo carico, poi escono in modo regolare
    equivalenti = (al_primo + all_ultimo) / 2 if in_stalla else 0.0

    # animali
    capi = max(0.0, sit.capi_presenti - sce.morti_giorno * equivalenti + var.capi) if in_stalla else 0.0
    peso = None
    futura = 0.0
    resa = (sce.resa_perc + var.resa_punti) / 100
    if in_stalla:
        peso = (peso_da_curva(sit.curva, sit.eta_media_giorni + equivalenti) or 0.0) + sce.peso_extra_kg + var.peso_kg
        futura = capi * peso * resa
    partita = carne_partita(sit.carichi, contratto, resa_perc=None if resa_media(sit.carichi) else sce.resa_perc + var.resa_punti)

    # mangime
    finora = sit.mangime_bolle_kg + sit.giacenza_iniziale_kg - sit.giacenza_oggi_kg
    residuo = max(0.0, (sit.consumo_mangime_giorno_kg + var.consumo_giorno_kg) * equivalenti) if in_stalla else 0.0

    # siero
    prezzo = sit.siero_prezzo_t + var.siero_prezzo_t
    da_fatturare = sit.siero_da_fatturare_t * prezzo
    futuro = max(0.0, sit.siero_giorno_t * equivalenti + var.siero_t) * prezzo if in_stalla else 0.0

    giorni = (sce.ultimo_carico - sit.ultimo_giorno_pagato_prec).days + var.giorni + var.ultimo_giorni
    c = conto(
        mangime_kg=finora + residuo + var.mangime_kg, carne_kg=partita.kg + futura,
        siero_eur=sit.siero_fatturato_eur + da_fatturare + futuro, giorni=giorni, contratto=contratto,
        premi_perc=sce.premi_perc + var.premi_punti, premio_extra_perc=sce.premio_extra_perc,
        anticipi_eur=sit.anticipi_eur,
    )
    n_carichi = math.ceil(capi / sce.capi_carico) if capi > 0 and sce.capi_carico else 0
    return Stima(
        conto=c, giorni_equivalenti=equivalenti, capi_macello=capi, peso_uscita_kg=peso, carne=partita,
        carne_futura_kg=futura, mangime_finora_kg=finora, mangime_residuo_kg=residuo,
        siero_da_fatturare_eur=da_fatturare, siero_futuro_eur=futuro, carichi_previsti=n_carichi,
        giorni_minimi_carico=math.ceil(n_carichi / sce.carichi_giorno) if sce.carichi_giorno else 0,
        finestra_giorni=(sce.ultimo_carico - sce.primo_carico).days,
    )


@dataclass(frozen=True)
class Incertezze:
    """Di quanto si spostano i dati incerti nella simulazione (scarto tipo).
    Partono da quanto queste grandezze sono cambiate nei cicli passati (Excel 2022–2026).
    Ognuna pesa solo sulla parte del conto ancora stimata: quando un dato diventa
    reale smette di muoversi da solo."""
    giorni: float = 5.0                 # date dei carichi presunte
    giorni_confermate: float = 1.0      # date confermate da Veronesi
    peso_kg: float = 4.0                # peso vivo medio di uscita
    resa_punti: float = 0.5             # resa al macello (cicli passati: 82,6–83,7%)
    capi: float = 15.0                  # morti in più o in meno del previsto
    consumo_giorno_frazione: float = 0.056   # consumo giornaliero di mangime (±5,6%)
    giacenza_kg: float = 3000.0         # giacenza iniziale e silos di oggi
    siero_t: float = 100.0
    siero_prezzo_frazione: float = 0.027     # prezzo del siero non ancora fatturato
    premi_punti: float = 1.2            # premi da prontuario (cicli passati: 4,7–9,6%)


@dataclass(frozen=True)
class Simulazione:
    probabilita: float            # quota di scenari a premio
    sfavorevole_eur: float        # margine: 10° percentile
    atteso_eur: float             # mediana
    favorevole_eur: float         # 90° percentile
    margini: tuple = field(repr=False, default=())   # tutti i margini simulati, ordinati


def simula(sit, sce, contratto, n=4000, seme=7, inc=Incertezze(), premi_noti=False):
    """Rifà la stima n volte spostando i dati incerti. Il seme fisso dà lo stesso risultato
    a parità di dati: la probabilità cambia solo quando cambiano i dati.
    premi_noti: i premi da prontuario sono già quelli comunicati da Veronesi."""
    r = random.Random(seme)
    in_stalla = sit.capi_presenti > 0
    sd_giorni = (inc.giorni_confermate if sce.date_confermate else inc.giorni) if in_stalla else 0.0
    margini = []
    for _ in range(n):
        v = Variazione(
            giorni=r.gauss(0, sd_giorni),
            peso_kg=r.gauss(0, inc.peso_kg),
            resa_punti=r.gauss(0, inc.resa_punti),
            capi=r.gauss(0, inc.capi),
            consumo_giorno_kg=r.gauss(0, inc.consumo_giorno_frazione * sit.consumo_mangime_giorno_kg),
            mangime_kg=r.gauss(0, inc.giacenza_kg) if in_stalla else 0.0,
            siero_t=r.gauss(0, inc.siero_t),
            siero_prezzo_t=r.gauss(0, inc.siero_prezzo_frazione * sit.siero_prezzo_t),
            premi_punti=0.0 if premi_noti else r.gauss(0, inc.premi_punti),
        )
        margini.append(stima(sit, sce, contratto, v).conto.margine_eur)
    margini.sort()
    return Simulazione(
        probabilita=sum(1 for m in margini if m > 0) / n,
        sfavorevole_eur=margini[int(n * 0.1)], atteso_eur=margini[int(n * 0.5)], favorevole_eur=margini[int(n * 0.9)],
        margini=tuple(margini),
    )


# Le «leve» della scheda: una variazione alla volta, in peggio e in meglio.
LEVE = (
    ("Ultimo carico, 7 giorni", "7 giorni dopo", Variazione(ultimo_giorni=7), "7 giorni prima", Variazione(ultimo_giorni=-7)),
    ("Primo carico, 7 giorni", "7 giorni dopo", Variazione(primo_giorni=7), "7 giorni prima", Variazione(primo_giorni=-7)),
    ("Peso vivo medio, 2 kg", "2 kg in meno", Variazione(peso_kg=-2), "2 kg in più", Variazione(peso_kg=2)),
    ("Capi a macello, 20", "20 in meno", Variazione(capi=-20), "20 in più", Variazione(capi=20)),
    ("Mangime residuo, 10 t", "10 t in più", Variazione(mangime_kg=10000), "10 t in meno", Variazione(mangime_kg=-10000)),
    ("Resa al macello, 0,5 punti", "0,5 in meno", Variazione(resa_punti=-0.5), "0,5 in più", Variazione(resa_punti=0.5)),
    ("Siero residuo, 100 t", "100 t in più", Variazione(siero_t=100), "100 t in meno", Variazione(siero_t=-100)),
    ("Premi da prontuario, 1 punto", "1 in meno", Variazione(premi_punti=-1), "1 in più", Variazione(premi_punti=1)),
)


def leve(sit, sce, contratto):
    """Effetto sul margine di ogni leva: [(nome, etichetta peggio, € , etichetta meglio, €)],
    dalla più pesante. Con il primo carico già passato la leva delle date del primo sparisce."""
    base = stima(sit, sce, contratto).conto.margine_eur
    out = []
    for nome, et_a, var_a, et_b, var_b in LEVE:
        a = stima(sit, sce, contratto, var_a).conto.margine_eur - base
        b = stima(sit, sce, contratto, var_b).conto.margine_eur - base
        if abs(a) < 0.5 and abs(b) < 0.5:
            continue
        out.append((nome, et_a, a, et_b, b))
    out.sort(key=lambda x: -max(abs(x[2]), abs(x[4])))
    return out


def con_scenario(sce, **modifiche):
    """Copia dello scenario con alcuni valori cambiati (per le prove della scheda)."""
    return replace(sce, **modifiche)
