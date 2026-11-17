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
# Arrivo di un box: la prima entrata negli Spostamenti con il peso (età = età della curva a quel peso);
# se non c'è, il primo censimento in cui il box ha capi e età. Gli spostamenti interni non spostano l'arrivo.

def peso_da_eta(punti, eta):
    """Peso (kg) all'età data, interpolato tra i punti [(età, peso, …)]; fermo oltre gli estremi."""
    pp = sorted((p[0], p[1]) for p in punti)
    if not pp:
        return None
    if eta <= pp[0][0]:
        return pp[0][1]
    for (e0, p0), (e1, p1) in zip(pp, pp[1:]):
        if e0 <= eta <= e1:
            return p0 + (p1 - p0) * (eta - e0) / (e1 - e0) if e1 != e0 else p0
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
class GruppoScarto:
    arrivo: object               # data dell'arrivo
    eta_arrivo: float
    da_entrata: bool             # arrivo dalle entrate (True) o dal primo censimento (False)
    box: tuple
    capi: int
    eta_censimento: float        # media pesata sui capi
    eta_teorica: float
    scarto_giorni: float         # + avanti sulla curva (più pesanti), − indietro
    scarto_kg: float


@dataclass(frozen=True)
class CensimentoScarto:
    data: object
    capi: int
    eta_censimento: float
    eta_teorica: float
    scarto_giorni: float
    scarto_kg: float
    gruppi: tuple


def scarti_censimenti(censimenti, entrate, punti):
    """censimenti: [(data, {box: (capi, età)})]; entrate: [(data, box, peso medio kg)]; punti: la curva.
    Ritorna [CensimentoScarto] in ordine di data, con i gruppi di box arrivati insieme (stessa data ed età)."""
    arrivi = {}
    for d, box, peso in sorted(entrate, key=lambda x: x[0]):
        if box is not None and peso and box not in arrivi:
            arrivi[box] = (d, eta_da_peso(punti, peso), True)
    out = []
    for d, conteggi in sorted(censimenti, key=lambda x: x[0]):
        gruppi = {}
        for box, (capi, eta) in sorted(conteggi.items()):
            if not capi or eta is None:
                continue
            if box not in arrivi:
                arrivi[box] = (d, float(eta), False)
            d0, e0, da_entrata = arrivi[box]
            if d < d0:
                continue        # censimento prima dell'entrata registrata
            teorica = e0 + (d - d0).days
            g = gruppi.setdefault((d0, round(e0, 1), da_entrata), [])
            g.append((box, capi, eta, teorica, peso_da_eta(punti, eta) - peso_da_eta(punti, teorica)))
        if not gruppi:
            continue

        def media(righe, i):
            return sum(r[1] * r[i] for r in righe) / sum(r[1] for r in righe)

        tutti = [r for g in gruppi.values() for r in g]
        out.append(CensimentoScarto(
            data=d, capi=sum(r[1] for r in tutti), eta_censimento=media(tutti, 2), eta_teorica=media(tutti, 3),
            scarto_giorni=media(tutti, 2) - media(tutti, 3), scarto_kg=media(tutti, 4),
            gruppi=tuple(GruppoScarto(
                arrivo=k[0], eta_arrivo=k[1], da_entrata=k[2], box=tuple(r[0] for r in g), capi=sum(r[1] for r in g),
                eta_censimento=media(g, 2), eta_teorica=media(g, 3), scarto_giorni=media(g, 2) - media(g, 3),
                scarto_kg=media(g, 4)) for k, g in sorted(gruppi.items(), key=lambda kv: (kv[0][0], kv[0][1]))),
        ))
    return out
