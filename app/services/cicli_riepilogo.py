"""Cicli a confronto (3.6.0): una riga di numeri finali per ogni ciclo, del gestionale e dello storico.

- Cicli del gestionale: i numeri vengono dalla Soccida (stesso conto della scheda, scenario standard). Un ciclo
  chiuso con la fotografia del conto (SoccidaFotografia) usa quella: non cambia più se cambia un dato o una
  regola. Senza fotografia si ricalcola ogni volta, e per un ciclo in corso è una stima.
- Cicli storici (CicloStorico): copiati dall'Excel «Calcoli compenso Soccida v2» (cicli 1-6, prima del
  gestionale), solo i dati finali; Andrea li controlla e li segna «controllato».

Le giacenze iniziale e finale sono in tabella apposta: la finale di un ciclo deve essere l'iniziale del
successivo, e mangime consumato = bolle + giacenza iniziale − giacenza finale. Le righe che non tornano si
segnalano (avvisi).
"""
import json
from datetime import date, datetime

from app import db

# chiavi di una riga (anche quelle salvate nella fotografia)
CAMPI = ("capi_entrati", "capi_cabianca", "capi_usciti", "morti", "giacenza_iniziale_kg", "mangime_bolle_kg",
         "giacenza_finale_kg", "mangime_consumato_kg", "carne_kg", "indice", "premi_perc", "siero_eur", "resa_eur",
         "minimo_eur", "giorni_pagati", "anticipi_eur", "netto_eur", "pagato_eur", "a_premio", "margine_eur",
         "capi_macello", "definitivo")

# Cicli 1-6 dall'Excel (fogli «Ciclo N gg/mm/aaaa»): B4 posti, B8 ricevuti, I17 suini dell'agriturismo, G41 consegnati,
# B16 morti, O8/O7 giacenze, P57 bolle, E17 mangime consumato, I41 carne, B19 indice, B22 premi, Esselunga, E13 siero,
# J8 resa, E11 minimo, B12 giorni, I12 anticipi, H18 bonifico a saldo. Nel ciclo 4 la giacenza (500 kg, O7) è
# sommata alle bolle: è quella iniziale. Nei cicli 1-3 le giacenze non sono scritte.
# I numeri NON sono nel codice (il repository è pubblico): stanno in data/cicli_excel.json (cartella esclusa da git),
# copiato a mano sul server. Senza il file non si importa niente e si riprova alla visita successiva.
FILE_EXCEL = "cicli_excel.json"


def _cicli_excel():
    import os
    from flask import current_app
    percorso = os.path.join(os.path.dirname(current_app.config["SQLALCHEMY_DATABASE_URI"].replace("sqlite:///", "")),
                            FILE_EXCEL)
    if not os.path.exists(percorso):
        return None
    with open(percorso, encoding="utf-8") as f:
        righe = json.load(f)
    for r in righe:
        for k in ("data_inizio", "data_fine"):
            r[k] = date.fromisoformat(r[k]) if r.get(k) else None
    return righe


CHIAVE_IMPORTATI = "cicli_storico_importati"


def importa_excel_se_serve():
    """Carica una volta sola i cicli dell'Excel (se poi Andrea ne cancella uno, non torna)."""
    from app.models import CicloStorico, Setting
    if db.session.get(Setting, CHIAVE_IMPORTATI):
        return 0
    cicli = _cicli_excel()
    if not cicli:
        return 0
    for d in cicli:
        db.session.add(CicloStorico(note="Dall'Excel «Calcoli compenso Soccida v2 11-05-2026», da controllare.", **d))
    db.session.add(Setting(key=CHIAVE_IMPORTATI, value=datetime.now().isoformat(timespec="minutes")))
    db.session.commit()
    return len(cicli)


def _conto_storico(r):
    """Netto, pagato e premio di un ciclo storico, con le regole del contratto (soccida.py, regola 7)."""
    if r["resa_eur"] is None or r["minimo_eur"] is None:
        return
    siero = r["siero_eur"] or 0
    r["pagato_eur"] = max(r["resa_eur"], r["minimo_eur"] + siero)
    r["netto_eur"] = r["pagato_eur"] - siero
    r["margine_eur"] = r["resa_eur"] - siero - r["minimo_eur"]
    r["a_premio"] = r["margine_eur"] > 0


def riga_storico(s):
    r = {"tipo": "storico", "id": s.id, "nome": s.nome, "inizio": s.data_inizio, "fine": s.data_fine,
         "posti": s.posti, "stato": "controllato" if s.controllato else "da controllare", "note": s.note}
    for k in CAMPI:
        r[k] = getattr(s, k, None)
    r["capi_macello"], r["definitivo"] = 0, True
    r["giorni_pagati"] = s.giorni_pagati
    r["premi_perc"] = (s.premi_perc or 0) + (s.premio_extra_perc or 0)
    r["saldo_eur"] = s.saldo_eur
    _conto_storico(r)
    return r


def _entrati(ciclo):
    from app.models import Censimento
    from app.services import soccida_dati as D
    n = sum(s.quantita for s in D.entrate(ciclo))
    if n:
        return n
    primo = Censimento.query.filter_by(ciclo_id=ciclo.id).order_by(Censimento.data, Censimento.id).first()
    return sum(b.quantita for b in primo.conteggi) if primo else None


def dati_correnti(ciclo):
    """Numeri del ciclo ricalcolati adesso dalla Soccida. definitivo: ciclo chiuso, giacenza finale e premi
    comunicati, tutti i carichi riscontrati, nessun capo in stalla."""
    from app.models import EventoMortalita
    from app.services import soccida as S, soccida_dati as D
    from app.services.allevamento_conteggio import oggi_del_ciclo
    r = {k: None for k in CAMPI}
    r["capi_entrati"] = _entrati(ciclo)
    r["morti"] = db.session.query(db.func.sum(EventoMortalita.quantita)).filter_by(ciclo_id=ciclo.id).scalar() or 0
    r["definitivo"] = False
    par = D.parametri(ciclo, crea=False) if not ciclo.in_avvio else None
    if par is None:
        return r
    oggi = oggi_del_ciclo(ciclo)
    try:
        sit, _ = D.situazione(ciclo, par, oggi)
        contratto = D.contratto(ciclo, par)
        st = S.stima(sit, D.scenario(par, sit.carichi), contratto)
    except ValueError:
        return r
    c = st.conto
    r.update(
        capi_cabianca=par.suini_cabianca or 0,
        capi_usciti=sum(k.capi_riscontrati if k.riscontrato else k.capi for k in sit.carichi),
        giacenza_iniziale_kg=par.giacenza_iniziale_kg, mangime_bolle_kg=sit.mangime_bolle_kg,
        giacenza_finale_kg=par.giacenza_finale_kg if par.giacenza_finale_kg is not None else sit.giacenza_oggi_kg,
        mangime_consumato_kg=c.mangime_kg, carne_kg=c.carne_kg, indice=c.indice, premi_perc=c.premi_perc,
        siero_eur=c.siero_eur, resa_eur=c.resa_eur, minimo_eur=c.minimo_eur, giorni_pagati=round(c.giorni),
        anticipi_eur=c.anticipi_eur, netto_eur=c.netto_eur, pagato_eur=c.pagato_eur, a_premio=c.a_premio,
        margine_eur=c.margine_eur, capi_macello=st.capi_macello,
    )
    r["giacenza_finale_stimata"] = par.giacenza_finale_kg is None
    r["definitivo"] = bool(ciclo.chiuso and par.giacenza_finale_kg is not None and par.premi_noti
                           and sit.capi_presenti == 0 and all(k.riscontrato or k.scarto for k in sit.carichi))
    return r


def ultima_fotografia(ciclo):
    from app.models import SoccidaFotografia
    return SoccidaFotografia.query.filter_by(ciclo_id=ciclo.id).order_by(SoccidaFotografia.creata_il.desc()).first()


def fotografa(ciclo, operatore, liquidato_eur=None, nota=None):
    """Salva la fotografia del conto del ciclo (i numeri di adesso)."""
    from app.models import SoccidaFotografia
    d = dati_correnti(ciclo)
    if d.get("resa_eur") is None:
        raise ValueError("La Soccida di questo ciclo non ha ancora un conto da salvare.")
    f = SoccidaFotografia(ciclo_id=ciclo.id, creata_il=datetime.now().replace(microsecond=0), operatore=operatore,
                          liquidato_eur=liquidato_eur, nota=nota, dati=json.dumps(d, default=str))
    db.session.add(f)
    return f


def dati_fotografia(f):
    return json.loads(f.dati) if f else None


def riga_ciclo(ciclo):
    f = ultima_fotografia(ciclo)
    if f:
        r = dati_fotografia(f)
        stato = f"conto salvato il {f.creata_il:%d/%m/%Y}"
        r["liquidato_eur"] = f.liquidato_eur
    else:
        r = dati_correnti(ciclo)
        stato = ("in corso, stima" if not ciclo.chiuso else ("definitivo, da salvare" if r.get("definitivo")
                                                               else "chiuso, conto non ancora definitivo"))
        r["liquidato_eur"] = None
    if ciclo.in_avvio:
        stato = "in avvio"
    r.update(tipo="gestionale", id=ciclo.id, nome=ciclo.nome, inizio=ciclo.data_inizio, fine=ciclo.data_fine,
             stato=stato, note=ciclo.note)
    return r


def tabella():
    """Righe di tutti i cicli, dal più vecchio, con gli avvisi sulle giacenze e sul mangime consumato."""
    from app.models import Ciclo, CicloStorico
    righe = [riga_storico(s) for s in CicloStorico.query.all()] + [riga_ciclo(c) for c in Ciclo.query.all()]
    righe.sort(key=lambda r: r["inizio"])
    prec = None
    for r in righe:
        r["avvisi"] = []
        r["giacenza_iniziale_diversa"] = False
        r["consumato_diverso"] = False
        entrati, cab, morti = r.get("capi_entrati"), r.get("capi_cabianca") or 0, r.get("morti")
        r["mortalita_perc"] = morti / (entrati - cab) * 100 if entrati and morti is not None and entrati > cab else None
        # a ciclo non finito i capi al macello sono quelli previsti dalla Soccida (finora ne sono usciti meno)
        usciti = r.get("capi_usciti")
        if not r.get("definitivo") and r.get("capi_macello"):      # capi_macello: grassi ancora da caricare
            usciti = (usciti or 0) + r["capi_macello"]
        r["mangime_capo_kg"] = r["mangime_consumato_kg"] / usciti if r.get("mangime_consumato_kg") and usciti else None
        r["peso_morto_medio_kg"] = r["carne_kg"] / usciti if r.get("carne_kg") and usciti else None
        r["giorni"] = ((r["fine"] or date.today()) - r["inizio"]).days
        if prec is not None:
            fin, ini = prec.get("giacenza_finale_kg"), r.get("giacenza_iniziale_kg")
            if fin is None or ini is None:
                if fin is not None or ini is not None:
                    r["giacenza_iniziale_diversa"] = True
                    r["avvisi"].append("Manca la giacenza " + ("iniziale" if ini is None else f"finale di «{prec['nome']}»")
                                       + ": non si può controllare che una sia uguale all'altra.")
            elif abs(fin - ini) > 1:
                r["giacenza_iniziale_diversa"] = True
                r["avvisi"].append(f"Giacenza iniziale {ini:,.0f} kg diversa dalla finale di «{prec['nome']}» "
                                   f"({fin:,.0f} kg).".replace(",", "."))
        b, ini, fin, cons = (r.get("mangime_bolle_kg"), r.get("giacenza_iniziale_kg") or 0,
                             r.get("giacenza_finale_kg") or 0, r.get("mangime_consumato_kg"))
        # a conto non definitivo il consumato è una previsione fino a fine ciclo: il controllo non ha senso
        if r.get("definitivo") and b is not None and cons is not None and abs(b + ini - fin - cons) > 1:
            r["consumato_diverso"] = True
            r["avvisi"].append(f"Bolle + giacenza iniziale − finale = {b + ini - fin:,.0f} kg, ma il mangime consumato "
                               f"è {cons:,.0f} kg.".replace(",", "."))
        prec = r
    return righe
