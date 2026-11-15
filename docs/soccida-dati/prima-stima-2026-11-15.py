import random, statistics as st
TAB = [(2.9,22.3),(3.0,20.9),(3.1,19.5),(3.2,18.1),(3.3,16.7),(3.4,15.46),(3.5,14.22),(3.6,12.98),(3.7,11.94),(3.8,11.12),(3.9,10.29),(4.0,9.46)]
def perc(ic):
    if ic <= 2.9: return 22.3 + (2.9 - ic) * 14.0
    if ic >= 4.0: return 9.46
    for (a, pa), (b, pb) in zip(TAB, TAB[1:]):
        if a <= ic <= b: return pa + (pb - pa) * (ic - a) / (b - a)
def conto(giorni_fine=226, capi=1740, peso_vivo=172.0, resa=0.83, mang_finora=669730, mang_giorno=4450, giorni_medi=28,
          siero_finora=15285.0, siero_t_residue=646, siero_eur_t=11.32, premi=8.0, giac_iniz_err=0, scarti_kg=24*69.6*(1-.1638)*.5):
    carne = capi * peso_vivo * resa + scarti_kg
    mangime = mang_finora + giac_iniz_err + mang_giorno * giorni_medi
    ic = mangime / carne
    resa_eur = perc(ic) * 1.45 * 1.2 / 100 * carne * (1 + premi / 100)
    siero = siero_finora + siero_t_residue * siero_eur_t
    minimo = 98000 / 365 * giorni_fine
    return dict(carne=carne, mangime=mangime, ic=ic, eurkg=perc(ic)*1.74/100, resa=resa_eur, siero=siero, minimo=minimo, margine=resa_eur - siero - minimo,
                pagato=max(resa_eur, minimo + siero), netto=max(resa_eur - siero, minimo))
b = conto()
for k, v in b.items(): print("%-8s %12.3f" % (k, v))
# indice di pareggio
lo, hi = 2.5, 4.0
for _ in range(60):
    m = (lo + hi) / 2
    r = perc(m) * 1.74 / 100 * b["carne"] * 1.08 - b["siero"] - b["minimo"]
    lo, hi = (m, hi) if r > 0 else (lo, m)
print("IC di pareggio %.3f" % lo, "mangime max kg %.0f" % (lo * b["carne"]), "margine kg mangime %.0f" % (lo * b["carne"] - b["mangime"]))
print("-- leve (variazione del margine)")
for nome, kw in [("resa +0,5 punti", dict(resa=.835)), ("resa 82%", dict(resa=.82)), ("peso vivo +2 kg", dict(peso_vivo=174)), ("mangime residuo +10 t", dict(mang_giorno=4450 + 10000/28)),
                 ("capi -20", dict(capi=1720)), ("premi 7%", dict(premi=7)), ("premi 9%", dict(premi=9)), ("giacenza iniziale 10 t invece di 3", dict(giac_iniz_err=7000)),
                 ("siero +100 t", dict(siero_t_residue=746)),
                 ("fine 7 giorni dopo", dict(giorni_fine=233, giorni_medi=35, peso_vivo=172 + 7*0.6, siero_t_residue=646 + 7*13.5, capi=1733)),
                 ("fine 7 giorni prima", dict(giorni_fine=219, giorni_medi=21, peso_vivo=172 - 7*0.65, siero_t_residue=646 - 7*13.5, capi=1747))]:
    x = conto(**kw); print("%-38s IC %.3f margine %+8.0f (%+.0f)" % (nome, x["ic"], x["margine"], x["margine"] - b["margine"]))
random.seed(1); N = 20000; ms = []; ics = []
for _ in range(N):
    dg = random.gauss(0, 5)
    x = conto(giorni_fine=226 + dg, giorni_medi=28 + dg, peso_vivo=random.gauss(172, 4) + dg * 0.6, resa=random.gauss(.83, .005), capi=random.gauss(1740 - dg, 15),
              mang_giorno=random.gauss(4450, 250), giac_iniz_err=random.gauss(0, 3000), siero_t_residue=max(0, random.gauss(646 + dg * 13.5, 100)),
              siero_eur_t=random.gauss(11.32, .3), premi=random.gauss(8, 1.2))
    ms.append(x["margine"]); ics.append(x["ic"])
ms.sort(); ics.sort()
print("probabilita premio %.0f%%" % (100 * sum(m > 0 for m in ms) / N), "margine P10 %.0f mediana %.0f P90 %.0f" % (ms[N//10], ms[N//2], ms[9*N//10]), "IC P10 %.3f P90 %.3f" % (ics[N//10], ics[9*N//10]))
