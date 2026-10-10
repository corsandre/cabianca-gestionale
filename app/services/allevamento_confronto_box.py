"""Confronto dei capi per box tra gestionale e PC di alimentazione.

Il gestionale calcola i capi di ogni box dall'ultimo censimento, meno la mortalità e più/meno gli
spostamenti; il PC li ha nella tabella BOX.DB (aggiornata a mano dall'operatore). Se i due numeri
non coincidono, di solito manca la registrazione di uno spostamento o di un decesso da una delle due
parti: per ogni box diverso si mostrano i movimenti dall'ultimo censimento per capire quale.
Usato dal pulsante in Spostamenti e dal controllo delle 6:50 del servizio impianto.
"""

from datetime import datetime


def _movimenti(ciclo, box, dal):
    from app.models import EventoMortalita, Spostamento
    out = []
    for s in Spostamento.query.filter(Spostamento.ciclo_id == ciclo.id, Spostamento.data >= dal).filter(
            (Spostamento.box_origine == box) | (Spostamento.box_destinazione == box)).all():
        segno = +s.quantita if s.box_destinazione == box else -s.quantita
        if s.tipo == "interno":
            testo = f"{s.box_origine} → {s.box_destinazione}"
        else:
            testo = "entrata" if s.tipo == "entrata" else f"uscita ({s.categoria_uscita or 'uscita'})"
        out.append({"data": s.data, "segno": segno, "testo": testo, "nota": s.motivo or "",
                    "sul_pc": s.pc_alimentazione_data, "chi": s.registrato_da or ""})
    for m in EventoMortalita.query.filter(EventoMortalita.ciclo_id == ciclo.id, EventoMortalita.data >= dal,
                                          EventoMortalita.box_numero == box).all():
        out.append({"data": m.data, "segno": -m.quantita, "testo": "decesso", "nota": m.causa or "",
                    "sul_pc": m.pc_alimentazione_data, "chi": ""})
    return sorted(out, key=lambda x: x["data"])


def confronta(lettore=None) -> dict:
    """{"ok", "differenze": [...], "tot_gestionale", "tot_pc", "box", "letto_il", "errore", "censimento"}."""
    from app.models import Censimento, Ciclo
    from app.routes.allevamento import _live_count, CAP_PER_BOX
    ciclo = Ciclo.query.filter_by(attivo=True).first()
    esito = {"ok": False, "differenze": [], "tot_gestionale": 0, "tot_pc": 0, "box": 0,
             "letto_il": datetime.now(), "errore": None, "censimento": None}
    if ciclo is None:
        esito["errore"] = "Nessun ciclo attivo."
        return esito
    chiudi = False
    if lettore is None:
        from app.services.impianto import crea_lettore
        lettore = crea_lettore()
        chiudi = True
        if lettore is None:
            esito["errore"] = "Collegamento al PC di alimentazione non attivo (modalità manuale)."
            return esito
    try:
        pc = lettore.capi_per_box()
    except Exception as e:
        esito["errore"] = f"Lettura dal PC non riuscita: {e}"
        return esito
    finally:
        if chiudi:
            lettore.chiudi()
    gest = _live_count(ciclo)
    ultimo = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(Censimento.data.desc(), Censimento.id.desc()).first()
    esito["censimento"] = ultimo.data if ultimo else None
    esito["box"] = len(gest)
    esito["tot_gestionale"] = sum(gest.values())
    esito["tot_pc"] = sum(pc.get(b, 0) for b in gest)
    for b in sorted(gest):
        g, p = gest.get(b, 0), pc.get(b)
        if p is None or g != p:
            esito["differenze"].append({"box": b, "capannone": CAP_PER_BOX.get(b), "gestionale": g, "pc": p,
                                        "diff": (g - p) if p is not None else None,
                                        "movimenti": _movimenti(ciclo, b, ultimo.data) if ultimo else []})
    esito["ok"] = True
    return esito


def testo_telegram(esito) -> str | None:
    """Messaggio solo se ci sono differenze (o se la lettura non è riuscita)."""
    if not esito["ok"]:
        return f"⚠️ <b>Capi per box</b>: confronto con il PC non riuscito. {esito['errore'] or ''}"
    if not esito["differenze"]:
        return None
    righe = [f"📦 <b>Capi per box diversi tra gestionale e PC</b> ({len(esito['differenze'])} su {esito['box']}; "
             f"totale gestionale {esito['tot_gestionale']}, PC {esito['tot_pc']}):"]
    for d in esito["differenze"][:12]:
        ultimo = d["movimenti"][-1] if d["movimenti"] else None
        coda = f" · ultimo movimento {ultimo['data'].strftime('%d/%m')} {ultimo['testo']}" if ultimo else ""
        righe.append(f"  · box {d['box']} (cap. {d['capannone']}): gestionale {d['gestionale']}, PC "
                     f"{d['pc'] if d['pc'] is not None else '–'}{coda}")
    righe.append("Dettagli: Allevamento › Spostamenti › Confronta con il PC.")
    return "\n".join(righe)
