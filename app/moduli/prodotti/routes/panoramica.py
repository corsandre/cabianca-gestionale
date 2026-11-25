"""Pagina iniziale del modulo: pulsante "Nuovo lotto", ultimi lotti, prodotti recenti, avvisi."""
from flask import render_template

from app import db
from app.moduli.prodotti.models import Lotto, Prodotto, Ricetta
from app.moduli.prodotti.routes import bp


@bp.route("/")
def index():
    ultimi_lotti = Lotto.query.order_by(Lotto.data_produzione.desc(), Lotto.id.desc()).limit(10).all()
    # prodotti fatti di recente (per riprenderli con un tocco), poi gli altri
    recenti_id = [r[0] for r in db.session.query(Lotto.prodotto_id)
                  .group_by(Lotto.prodotto_id).order_by(db.func.max(Lotto.data_produzione).desc()).limit(8)]
    recenti = [db.session.get(Prodotto, i) for i in recenti_id]
    da_verificare = Prodotto.query.filter_by(da_verificare=True, attivo=True).count()
    senza_ricetta = (Prodotto.query.filter_by(attivo=True)
                     .filter(~Prodotto.id.in_(db.session.query(Ricetta.prodotto_id))).count())
    return render_template("prodotti/index.html", ultimi_lotti=ultimi_lotti, recenti=[p for p in recenti if p],
                           da_verificare=da_verificare, senza_ricetta=senza_ricetta,
                           n_prodotti=Prodotto.query.filter_by(attivo=True).count(), n_lotti=Lotto.query.count())
