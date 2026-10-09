"""Confronto mese per mese tra cassa (Z-report) e banca.

Gli incassi POS e i bonifici con scontrino vengono ignorati in banca perché sono già nei corrispettivi
di cassa: qui si verifica che i conti tornino. Bancomat e carta battuti in cassa devono ritrovarsi
come accrediti POS sul conto (a meno di commissioni e di qualche giorno di ritardo a fine mese).
I bonifici a fronte di scontrino non hanno una voce propria nello Z-report (lo scontrino viene
battuto come contanti, carta o bancomat), quindi si mostrano per informazione.
"""

import collections
from datetime import date

from app.models import BankTransaction, CashRegisterDaily

CAUSALI_POS_BANCOMAT = ("090",)
CAUSALI_POS_CARTE = ("092",)
SOGLIA_DIFFERENZA = 0.10        # oltre il 10% di scarto sul POS il mese va guardato


def confronto(mesi: int = 12) -> list[dict]:
    oggi = date.today()
    elenco = []
    y, m = oggi.year, oggi.month
    for _ in range(mesi):
        elenco.append(f"{y}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    righe = {k: collections.Counter() for k in elenco}
    completo = {k: True for k in elenco}
    for g in CashRegisterDaily.query.filter(CashRegisterDaily.date >= date.fromisoformat(elenco[-1] + "-01")).all():
        k = g.date.strftime("%Y-%m")
        if k not in righe:
            continue
        righe[k]["cassa"] += g.total_amount or 0
        if g.contanti is None:
            completo[k] = False
            continue
        righe[k]["contanti"] += g.contanti
        righe[k]["bancomat"] += g.bancomat or 0
        righe[k]["carta"] += g.carta or 0
    for b in BankTransaction.query.filter(BankTransaction.direction == "C",
                                          BankTransaction.operation_date >= date.fromisoformat(elenco[-1] + "-01")).all():
        k = b.operation_date.strftime("%Y-%m")
        if k not in righe:
            continue
        if b.causale_abi in CAUSALI_POS_BANCOMAT:
            righe[k]["pos_bancomat"] += b.amount
        elif b.causale_abi in CAUSALI_POS_CARTE:
            righe[k]["pos_carte"] += b.amount
        elif b.status == "ignorato" and b.ignore_reason_id:
            righe[k]["bonifici_cassa"] += b.amount
    # il terminale POS accredita su questo conto dal primo accredito POS in poi: prima su un altro conto
    primo_pos = BankTransaction.query.filter(BankTransaction.causale_abi.in_(CAUSALI_POS_BANCOMAT + CAUSALI_POS_CARTE)) \
        .order_by(BankTransaction.operation_date).first()
    mese_primo_pos = primo_pos.operation_date.strftime("%Y-%m") if primo_pos else "9999-99"
    out = []
    for k in elenco:
        r = righe[k]
        if not r["cassa"] and not r["pos_bancomat"] and not r["pos_carte"]:
            continue
        pos_cassa = r["bancomat"] + r["carta"]
        pos_banca = r["pos_bancomat"] + r["pos_carte"]
        diff = pos_banca - pos_cassa
        if k < mese_primo_pos:
            completo[k] = False
        out.append(dict(mese=k, completo=completo[k], pos_altro_conto=k < mese_primo_pos, **{x: round(r[x], 2) for x in
                        ("cassa", "contanti", "bancomat", "carta", "pos_bancomat", "pos_carte", "bonifici_cassa")},
                        pos_cassa=round(pos_cassa, 2), pos_banca=round(pos_banca, 2), diff=round(diff, 2),
                        da_guardare=completo[k] and pos_cassa > 0 and abs(diff) > SOGLIA_DIFFERENZA * pos_cassa))
    return out
