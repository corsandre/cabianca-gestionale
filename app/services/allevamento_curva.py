"""
Curva di accrescimento: gli scaglioni tra un punto e l'altro.

Solo calcolo, senza database né Flask (si prova da solo: tests/test_curva.py).
I punti arrivano dalla tabella `curva_accrescimento` del gestionale:
età (giorni), peso vivo (kg) e razione (kg di mangime al giorno per capo,
colonna «1» della curva di alimentazione del PC; la «2» è uguale).

Per ogni scaglione, cioè dal punto prima a questo:
- accrescimento giornaliero = kg di peso guadagnati / giorni;
- aumento della razione al giorno = differenza di razione / giorni;
- mangime dello scaglione = razione media dei due punti × giorni (la razione
  sale in modo regolare tra un punto e l'altro);
- indice sul peso vivo = mangime dello scaglione / kg guadagnati.
I cumulati partono dal primo punto della curva (l'ingresso, 26 kg).

Attenzione: l'indice del contratto di soccida si fa sul peso morto e su tutto il
mangime consegnato; questo è l'indice teorico della curva sul peso vivo.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Scaglione:
    eta_giorni: int
    peso_kg: float
    razione_kg: float | None
    # dal punto prima a questo (None sul primo punto)
    giorni: int | None = None
    accrescimento_g: float | None = None        # g di peso vivo al giorno
    aumento_razione_g: float | None = None      # g di razione in più ogni giorno
    mangime_kg: float | None = None             # kg di mangime per capo nello scaglione
    indice: float | None = None                 # mangime / kg guadagnati nello scaglione
    # dal primo punto della curva a questo
    mangime_cumulato_kg: float | None = None
    indice_cumulato: float | None = None


def scaglioni(punti):
    """punti: [(età, peso, razione)] (razione anche None). Ritorna [Scaglione] in ordine di età."""
    punti = sorted(punti, key=lambda p: p[0])
    out = []
    cumulato = 0.0
    con_razione = True       # il cumulato ha senso solo se tutti i punti fin qui hanno la razione
    for i, (eta, peso, razione) in enumerate(punti):
        if i == 0:
            out.append(Scaglione(eta, peso, razione, mangime_cumulato_kg=0.0 if razione is not None else None))
            con_razione = razione is not None
            continue
        e0, p0, r0 = punti[i - 1]
        giorni = eta - e0
        guadagno = peso - p0
        accr = guadagno / giorni * 1000 if giorni else None
        mangime = aumento = indice = None
        if razione is not None and r0 is not None and giorni:
            aumento = (razione - r0) / giorni * 1000
            mangime = (r0 + razione) / 2 * giorni
            indice = mangime / guadagno if guadagno > 0 else None
        con_razione = con_razione and mangime is not None
        if con_razione:
            cumulato += mangime
        guadagno_tot = peso - punti[0][1]
        out.append(Scaglione(
            eta, peso, razione, giorni=giorni, accrescimento_g=accr, aumento_razione_g=aumento,
            mangime_kg=mangime, indice=indice,
            mangime_cumulato_kg=cumulato if con_razione else None,
            indice_cumulato=cumulato / guadagno_tot if con_razione and guadagno_tot > 0 else None,
        ))
    return out


# ── Curva letta dal PC dell'impianto (EM2000) ───────────────────────────────
# Le righe arrivano già lette dalle tabelle Paradox (lettore EM2000, sola lettura):
# BOX.DB (NR, NRSUINI, NRCURVA), CurveNEW.DB (TIPO, NR, NOME, DESCR), curvepuntoNEW.db
# (TIPO, NR = numero del punto, HGEn / HGPn / HGn = età / peso / razione della curva n).
# TIPO 0 = curve di ingrasso. I campi a zero arrivano come 0 o None.

def curva_dal_pc(box, curve, punti, box_reali):
    """La curva di ingrasso usata dalla maggior parte dei box reali con capi, con i suoi punti in ordine di età.
    I punti si fermano quando l'età smette di crescere (punti non usati). None se nessun box ha una curva."""
    usate = Counter(int(b["NRCURVA"]) for b in box
                    if b.get("NR") in box_reali and (b.get("NRSUINI") or 0) > 0 and b.get("NRCURVA") is not None)
    if not usate:
        return None
    nr = usate.most_common(1)[0][0]
    testa = next((c for c in curve if (c.get("TIPO") or 0) == 0 and (c.get("NR") or 0) == nr), {})
    out, eta_prec = [], None
    for r in sorted((r for r in punti if (r.get("TIPO") or 0) == 0), key=lambda r: r.get("NR") or 0):
        eta, peso, razione = r.get(f"HGE{nr}"), r.get(f"HGP{nr}"), r.get(f"HG{nr}")
        eta = int(round(eta or 0))
        if eta_prec is not None and eta <= eta_prec:
            break
        if not peso:
            break
        out.append((eta, round(float(peso), 2), round(float(razione or 0), 3)))
        eta_prec = eta
    return {"nr": nr, "nome": (testa.get("NOME") or "").strip(), "descr": (testa.get("DESCR") or "").strip(),
            "box": usate[nr], "punti": out}


def differenze(salvati, dal_pc):
    """Confronto punto per punto: [(età, (peso, razione) salvati o None, (peso, razione) del PC o None)],
    solo dove qualcosa cambia. salvati e dal_pc: [(età, peso, razione)]."""
    a = {e: (p, r) for e, p, r in salvati}
    b = {e: (p, r) for e, p, r in dal_pc}
    out = []
    for e in sorted(set(a) | set(b)):
        x, y = a.get(e), b.get(e)
        if x is None or y is None or abs(x[0] - y[0]) > 1e-6 or abs((x[1] or 0) - (y[1] or 0)) > 1e-6 or (x[1] is None) != (y[1] is None):
            out.append((e, x, y))
    return out


# ── Curva teorica dall'arrivo e scarti dei censimenti ───────────────────────
# Regola (Andrea, 17/11/2026): al censimento si scrive il peso, l'età si ricava dalla curva ed è la posizione
# dei suini sulla curva. Qui la si confronta con la «curva teorica»: età all'arrivo + giorni passati.
# Arrivo di un box, in quest'ordine:
#   1. entrata negli Spostamenti con il peso → età della curva a quel peso;
#   2. spostamento interno registrato verso il box, da box che hanno già un arrivo → età teorica di quei capi
#      quel giorno (media pesata se vengono da più box);
#   3. altrimenti il primo censimento in cui il box ha capi e età (box riempiti senza movimenti registrati).
# Nello stesso giorno contano prima le entrate, poi gli spostamenti, poi il censimento (che li contiene).
# Una volta fissato, l'arrivo di un box non cambia per il resto del ciclo.

ENTRATA, SPOSTAMENTO, CENSIMENTO = "entrata", "spostamento", "censimento"


def peso_da_eta(punti, eta):
    """Peso (kg) all'età data, interpolato tra i punti [(età, peso, …)]; fermo oltre gli estremi."""
    return _interpola(punti, eta, 1)


def razione_da_eta(punti, eta):
    """Razione (kg/capo/giorno) all'età data; costante oltre gli estremi (come sul PC). None se manca."""
    return _interpola(punti, eta, 2)


def _interpola(punti, eta, k):
    pp = sorted((p[0], p[k] if len(p) > k else None) for p in punti)
    if not pp or any(v is None for _, v in pp):
        return None
    if eta <= pp[0][0]:
        return pp[0][1]
    for (e0, v0), (e1, v1) in zip(pp, pp[1:]):
        if e0 <= eta <= e1:
            return v0 + (v1 - v0) * (eta - e0) / (e1 - e0) if e1 != e0 else v0
    return pp[-1][1]


def eta_da_peso(punti, peso):
    """Età (giorni, con decimali) al peso dato, sull'asse del peso della curva; ferma oltre gli estremi."""
    pp = sorted((p[0], p[1]) for p in punti)
    if not pp:
        return None
    if peso <= pp[0][1]:
        return float(pp[0][0])
    for (e0, p0), (e1, p1) in zip(pp, pp[1:]):
        if p0 <= peso <= p1:
            return e0 + (e1 - e0) * (peso - p0) / (p1 - p0) if p1 != p0 else float(e0)
    return float(pp[-1][0])


@dataclass(frozen=True)
class Arrivo:
    data: object
    eta: float
    tipo: str                    # ENTRATA, SPOSTAMENTO o CENSIMENTO

    @property
    def chiave(self):
        return f"{self.data.isoformat()}|{self.eta:.1f}|{self.tipo}"

    def eta_al(self, giorno):
        return self.eta + (giorno - self.data).days


def arrivi(censimenti, entrate, interni, punti):
    """{box: Arrivo}. censimenti: [(data, {box: (capi, età, …)})]; entrate: [(data, box, peso medio kg)];
    interni: [(data, box di origine, box di destinazione, capi)]."""
    eventi = ([(d, 0, ("e", box, peso)) for d, box, peso in entrate]
              + [(d, 1, ("i", o, b, n)) for d, o, b, n in interni]
              + [(d, 2, ("c", cont)) for d, cont in censimenti])
    out, in_attesa, giorno_attesa = {}, {}, None

    def chiudi_spostamenti():
        for box, (somma, capi, d) in in_attesa.items():
            if box not in out and capi > 0:
                out[box] = Arrivo(d, somma / capi, SPOSTAMENTO)
        in_attesa.clear()

    for d, ordine, ev in sorted(eventi, key=lambda x: (x[0], x[1])):
        if in_attesa and (d != giorno_attesa or ordine != 1):
            chiudi_spostamenti()
        if ev[0] == "e":
            _, box, peso = ev
            if box is not None and peso and box not in out:
                out[box] = Arrivo(d, eta_da_peso(punti, peso), ENTRATA)
        elif ev[0] == "i":
            _, o, b, n = ev
            if b is not None and b not in out and o in out and n:
                somma, capi, _ = in_attesa.get(b, (0.0, 0, d))
                in_attesa[b] = (somma + n * out[o].eta_al(d), capi + n, d)
                giorno_attesa = d
        else:
            for box, valori in sorted(ev[1].items()):
                capi, eta = valori[0], valori[1]
                if capi and eta is not None and box not in out:
                    out[box] = Arrivo(d, float(eta), CENSIMENTO)
    chiudi_spostamenti()
    return out


@dataclass(frozen=True)
class Gruppo:
    """Box arrivati insieme (stesso Arrivo), a un censimento o oggi."""
    arrivo: Arrivo
    box: tuple
    capi: int
    eta_teorica: float           # età all'arrivo + giorni passati
    peso_teorico: float          # peso della curva all'età teorica
    eta: float                   # età del censimento (oggi: proiettata dall'ultimo censimento)
    peso: float                  # peso del censimento (scritto, o della curva se manca); oggi: stimato
    scarto_giorni: float         # + avanti sulla curva (più pesanti), − indietro
    scarto_kg: float
    razione_teorica: float | None = None       # solo oggi: razione con l'età teorica
    razione_aggiornata: float | None = None    # solo oggi: razione con l'età del censimento
    mangime_in_piu_kg: float | None = None     # solo oggi: in più con l'età aggiornata, da oggi all'ultimo carico


@dataclass(frozen=True)
class Riga:
    data: object
    oggi: bool
    capi: int
    eta_teorica: float
    peso_teorico: float
    eta: float
    peso: float
    scarto_giorni: float
    scarto_kg: float
    gruppi: tuple
    razione_teorica: float | None = None
    razione_aggiornata: float | None = None
    mangime_in_piu_kg: float | None = None


def _media(righe, k):
    capi = sum(r["capi"] for r in righe)
    return sum(r["capi"] * r[k] for r in righe) / capi


def _somma(righe, k):
    valori = [r[k] for r in righe]
    return None if any(v is None for v in valori) else sum(valori)


def riga(giorno, conteggi, arr, punti, oggi=False, fine=None):
    """Una riga della tabella: conteggi {box: (capi, età, peso o None)} a quel giorno, raggruppati per arrivo.
    Con oggi=True anche la razione con l'età teorica e con quella aggiornata e, con `fine` (ultimo carico
    previsto), il mangime in più fino a quel giorno se si aggiorna l'età sul PC."""
    per_gruppo = {}
    for box, valori in sorted(conteggi.items()):
        capi, eta = valori[0], valori[1]
        peso = valori[2] if len(valori) > 2 else None
        a = arr.get(box)
        if not capi or eta is None or a is None or giorno < a.data:
            continue
        teo = a.eta_al(giorno)
        r = {"box": box, "capi": capi, "eta": eta, "teo": teo,
             "peso": peso if peso is not None else peso_da_eta(punti, eta), "peso_teo": peso_da_eta(punti, teo),
             "raz_teo": None, "raz_agg": None, "mangime": None}
        if oggi:
            r["raz_teo"], r["raz_agg"] = razione_da_eta(punti, teo), razione_da_eta(punti, eta)
            if fine is not None and fine > giorno and r["raz_teo"] is not None:
                giorni = (fine - giorno).days
                r["mangime"] = capi * sum(razione_da_eta(punti, eta + t) - razione_da_eta(punti, teo + t)
                                          for t in range(giorni))
        per_gruppo.setdefault(a, []).append(r)
    if not per_gruppo:
        return None

    def costruisci(cls, righe, **extra):
        return cls(capi=sum(r["capi"] for r in righe), eta_teorica=_media(righe, "teo"),
                   peso_teorico=_media(righe, "peso_teo"), eta=_media(righe, "eta"), peso=_media(righe, "peso"),
                   scarto_giorni=_media(righe, "eta") - _media(righe, "teo"),
                   scarto_kg=_media(righe, "peso") - _media(righe, "peso_teo"),
                   razione_teorica=_media(righe, "raz_teo") if oggi and _somma(righe, "raz_teo") is not None else None,
                   razione_aggiornata=_media(righe, "raz_agg") if oggi and _somma(righe, "raz_agg") is not None else None,
                   mangime_in_piu_kg=_somma(righe, "mangime") if oggi else None, **extra)

    gruppi = tuple(costruisci(Gruppo, g, arrivo=a, box=tuple(r["box"] for r in g))
                   for a, g in sorted(per_gruppo.items(), key=lambda kv: (kv[0].data, kv[0].eta)))
    return costruisci(Riga, [r for g in per_gruppo.values() for r in g], data=giorno, oggi=oggi, gruppi=gruppi)


def scarti_censimenti(censimenti, entrate, punti, interni=(), oggi=None, stima_oggi=None, fine=None):
    """Tabella dei censimenti contro la curva teorica. Ritorna (righe dei censimenti in ordine di data,
    riga di oggi o None, arrivi per box). stima_oggi: {box: (capi, età, peso)} dall'ultimo censimento +
    aggiornamenti (conteggio live, età proiettata)."""
    arr = arrivi(censimenti, entrate, interni, punti)
    righe = [r for r in (riga(d, cont, arr, punti) for d, cont in sorted(censimenti, key=lambda x: x[0])) if r]
    r_oggi = riga(oggi, stima_oggi, arr, punti, oggi=True, fine=fine) if oggi and stima_oggi else None
    return righe, r_oggi, arr


def etichetta(a):
    """Come si chiama un gruppo nella pagina."""
    g = f"{a.data.day:02d}/{a.data.month:02d}"
    eta = f"{a.eta:.0f} gg"
    if a.tipo == ENTRATA:
        return f"Arrivo {g}, {eta}"
    if a.tipo == SPOSTAMENTO:
        return f"Spostati il {g} da altri box, {eta}"
    return f"Dal censimento del {g}, {eta}"


def serie_grafico(inizio, fine, righe, r_oggi, arr, punti, uscite=()):
    """Dati del grafico «peso medio: curva teorica e censimenti», per tutti e per ogni gruppo.
    uscite: [(data, peso vivo medio, {box: capi})] dei camion di fine ciclo. Le x sono giorni dall'inizio."""
    attuali = r_oggi or (righe[-1] if righe else None)
    if attuali is None:
        return None
    capi_gruppo = {g.arrivo: g.capi for g in attuali.gruppi}
    ultimo = max(fine, attuali.data)
    x = lambda d: (d - inizio).days

    def teorica(gruppi):
        out = []
        d = min(a.data for a in gruppi)
        while d <= ultimo:
            vivi = [a for a in gruppi if a.data <= d]
            capi = sum(capi_gruppo[a] for a in vivi)
            if capi:
                out.append([x(d), round(sum(capi_gruppo[a] * peso_da_eta(punti, a.eta_al(d)) for a in vivi) / capi, 2)])
            d = d.fromordinal(d.toordinal() + 1)
        return out

    def camion(gruppi):
        pts = []
        for d, peso, box in uscite:
            capi = sum(n for b, n in box.items() if arr.get(b) in gruppi)
            if peso and capi:
                pts.append([x(d), round(peso, 1), capi])
        return pts

    serie = {"tutti": {"nome": "Tutti", "teorica": teorica(list(capi_gruppo)),
                       "censimenti": [[x(r.data), round(r.peso, 1), r.capi] for r in righe],
                       "oggi": [x(r_oggi.data), round(r_oggi.peso, 1), r_oggi.capi] if r_oggi else None,
                       "camion": camion(set(capi_gruppo))}}
    for a in capi_gruppo:
        cens = [[x(r.data), round(g.peso, 1), g.capi] for r in righe for g in r.gruppi if g.arrivo == a]
        go = next((g for g in r_oggi.gruppi if g.arrivo == a), None) if r_oggi else None
        serie[a.chiave] = {"nome": etichetta(a), "teorica": teorica([a]), "censimenti": cens,
                           "oggi": [x(r_oggi.data), round(go.peso, 1), go.capi] if go else None, "camion": camion({a})}
    return {"inizio": inizio.isoformat(), "oggi": x(attuali.data), "serie": serie,
            "ordine": ["tutti"] + [a.chiave for a in sorted(capi_gruppo, key=lambda a: (a.data, a.eta))]}
