"""Modelli SQLAlchemy del modulo Prodotti, sul database data/prodotti.db (bind "prodotti").

ATTENZIONE: le tabelle le crea e le modifica SOLO schema.py (migrazioni numerate), mai db.create_all().
Questi modelli devono rispecchiare quelle tabelle: aggiungendo una colonna, prima la migrazione in
schema.py, poi la colonna qui.

Collegamenti al gestionale (gestionale.db, altro file): solo per id (fornitore_id → Contact) con una
copia del nome; utenti salvati come nome utente (creato_da, modificato_da).
"""
import json
from datetime import datetime

from app import db

BIND = "prodotti"


def adesso():
    return datetime.now().isoformat(timespec="seconds")


class _ListaJSON:
    """Mixin: proprietà `allergeni_lista` sopra la colonna testo `allergeni` (JSON)."""

    @property
    def allergeni_lista(self):
        try:
            return json.loads(self.allergeni or "[]")
        except ValueError:
            return []

    @allergeni_lista.setter
    def allergeni_lista(self, valori):
        from app.moduli.prodotti.services.allergeni import pulisci
        self.allergeni = json.dumps(pulisci(valori))


class Impostazione(db.Model):
    __bind_key__ = BIND
    __tablename__ = "impostazioni"
    chiave = db.Column(db.Text, primary_key=True)
    valore = db.Column(db.Text)

    @staticmethod
    def leggi(chiave, predefinito=None):
        r = db.session.get(Impostazione, chiave)
        return r.valore if r and r.valore is not None else predefinito

    @staticmethod
    def scrivi(chiave, valore):
        r = db.session.get(Impostazione, chiave)
        if r:
            r.valore = valore
        else:
            db.session.add(Impostazione(chiave=chiave, valore=valore))


class MateriaPrima(_ListaJSON, db.Model):
    __bind_key__ = BIND
    __tablename__ = "materie_prime"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, nullable=False, unique=True)
    nome_etichetta = db.Column(db.Text, nullable=False)
    allergeni = db.Column(db.Text, nullable=False, default="[]")
    composta = db.Column(db.Text)
    unita = db.Column(db.Text, nullable=False, default="g")
    fornitore_id = db.Column(db.Integer)
    fornitore_nome = db.Column(db.Text)
    produzione_propria = db.Column(db.Boolean, nullable=False, default=False)
    note = db.Column(db.Text)
    attiva = db.Column(db.Boolean, nullable=False, default=True)
    creato_il = db.Column(db.Text, nullable=False, default=adesso)

    def come_riga_ricetta(self, quantita=None, unita=None):
        """Dizionario per services/ingredienti.py."""
        return {"nome_etichetta": self.nome_etichetta, "quantita": quantita, "unita": unita or self.unita,
                "allergeni": self.allergeni_lista, "composta": self.composta}


class FormatoEtichetta(db.Model):
    __bind_key__ = BIND
    __tablename__ = "formati_etichetta"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, nullable=False, unique=True)
    uso = db.Column(db.Text)
    codice_foglio = db.Column(db.Text)
    larghezza_mm = db.Column(db.Float, nullable=False)
    altezza_mm = db.Column(db.Float, nullable=False)
    colonne = db.Column(db.Integer, nullable=False)
    righe = db.Column(db.Integer, nullable=False)
    margine_sup_mm = db.Column(db.Float, nullable=False, default=0)
    margine_sx_mm = db.Column(db.Float, nullable=False, default=0)
    passo_orizz_mm = db.Column(db.Float)
    passo_vert_mm = db.Column(db.Float)
    offset_x_mm = db.Column(db.Float, nullable=False, default=0)
    offset_y_mm = db.Column(db.Float, nullable=False, default=0)
    layout = db.Column(db.Text, nullable=False, default="orizzontale")
    attivo = db.Column(db.Boolean, nullable=False, default=True)

    @property
    def per_foglio(self):
        return self.colonne * self.righe

    @property
    def descrizione(self):
        return f"{self.nome} – {self.larghezza_mm:g}×{self.altezza_mm:g} mm, {self.per_foglio} per foglio"


class Prodotto(db.Model):
    __bind_key__ = BIND
    __tablename__ = "prodotti"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, nullable=False)
    sottotitolo = db.Column(db.Text)
    sigla = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.Text)
    peso_netto = db.Column(db.Float)
    unita = db.Column(db.Text, nullable=False, default="g")
    formato_etichetta_id = db.Column(db.Integer, db.ForeignKey("formati_etichetta.id"))
    tipo_scadenza = db.Column(db.Text, nullable=False, default="tmc")
    durata_giorni = db.Column(db.Integer)
    conservazione = db.Column(db.Text)
    modalita_uso = db.Column(db.Text)
    tracce = db.Column(db.Text)
    prodotto_da = db.Column(db.Text)
    lavorato_da = db.Column(db.Text)
    dichiarazioni_extra = db.Column(db.Text)
    nutrizionale = db.Column(db.Text)
    ricetta_default_id = db.Column(db.Integer)
    attivo = db.Column(db.Boolean, nullable=False, default=True)
    da_verificare = db.Column(db.Boolean, nullable=False, default=False)
    note = db.Column(db.Text)
    creato_il = db.Column(db.Text, nullable=False, default=adesso)
    modificato_il = db.Column(db.Text)

    formato = db.relationship("FormatoEtichetta")
    ricette = db.relationship("Ricetta", back_populates="prodotto", order_by="Ricetta.versione.desc()")

    TIPI_SCADENZA = {"tmc": "Da consumarsi preferibilmente entro il", "scadenza": "Da consumarsi entro il"}

    @property
    def peso_testo(self):
        """'500 g', '750 ml', '' se non indicato."""
        if not self.peso_netto:
            return ""
        return f"{self.peso_netto:g} {self.unita}"

    @property
    def nome_completo(self):
        return f"{self.nome} {self.peso_testo}".strip()

    @property
    def ricetta_predefinita(self):
        if self.ricetta_default_id:
            for r in self.ricette:
                if r.id == self.ricetta_default_id:
                    return r
        attive = [r for r in self.ricette if r.attiva]
        return attive[0] if attive else None


class Ricetta(db.Model):
    __bind_key__ = BIND
    __tablename__ = "ricette"
    id = db.Column(db.Integer, primary_key=True)
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"), nullable=False)
    versione = db.Column(db.Integer, nullable=False)
    nome = db.Column(db.Text)
    resa_pezzi = db.Column(db.Integer)
    resa_kg = db.Column(db.Float)
    procedimento = db.Column(db.Text)
    note_haccp = db.Column(db.Text)
    attiva = db.Column(db.Boolean, nullable=False, default=True)
    creato_da = db.Column(db.Text)
    creato_il = db.Column(db.Text, nullable=False, default=adesso)

    prodotto = db.relationship("Prodotto", back_populates="ricette")
    righe = db.relationship("RicettaRiga", order_by="RicettaRiga.ordine", cascade="all, delete-orphan")

    @property
    def etichetta(self):
        return f"v{self.versione}" + (f" – {self.nome}" if self.nome else "")

    @property
    def usata(self):
        """True se un lotto la usa: da quel momento non si modifica più (trigger nel database)."""
        return db.session.query(Lotto.id).filter_by(ricetta_id=self.id).first() is not None

    def righe_per_ingredienti(self, fattore=1.0):
        return [r.materia_prima.come_riga_ricetta(r.quantita * fattore, r.unita) for r in self.righe]


class RicettaRiga(db.Model):
    __bind_key__ = BIND
    __tablename__ = "ricette_righe"
    id = db.Column(db.Integer, primary_key=True)
    ricetta_id = db.Column(db.Integer, db.ForeignKey("ricette.id"), nullable=False)
    materia_prima_id = db.Column(db.Integer, db.ForeignKey("materie_prime.id"), nullable=False)
    quantita = db.Column(db.Float, nullable=False)
    unita = db.Column(db.Text, nullable=False, default="g")
    ordine = db.Column(db.Integer, nullable=False, default=0)
    nota = db.Column(db.Text)

    materia_prima = db.relationship("MateriaPrima")


class Lotto(_ListaJSON, db.Model):
    __bind_key__ = BIND
    __tablename__ = "lotti"
    id = db.Column(db.Integer, primary_key=True)
    codice = db.Column(db.Text, nullable=False, unique=True)
    prodotto_id = db.Column(db.Integer, db.ForeignKey("prodotti.id"), nullable=False)
    ricetta_id = db.Column(db.Integer, db.ForeignKey("ricette.id"))
    data_produzione = db.Column(db.Text, nullable=False)
    data_scadenza = db.Column(db.Text)
    pezzi_prodotti = db.Column(db.Integer)
    quantita_kg = db.Column(db.Float)
    ingredienti_testo = db.Column(db.Text)
    allergeni = db.Column(db.Text, nullable=False, default="[]")
    dati_etichetta = db.Column(db.Text)
    note = db.Column(db.Text)
    stato = db.Column(db.Text, nullable=False, default="attivo")
    stato_motivo = db.Column(db.Text)
    creato_da = db.Column(db.Text)
    creato_il = db.Column(db.Text, nullable=False, default=adesso)
    modificato_da = db.Column(db.Text)
    modificato_il = db.Column(db.Text)

    prodotto = db.relationship("Prodotto")
    ricetta = db.relationship("Ricetta")
    ingredienti = db.relationship("LottoIngrediente", order_by="LottoIngrediente.ordine",
                                  back_populates="lotto")
    stampe = db.relationship("StampaEtichetta", order_by="StampaEtichetta.id.desc()")

    STATI = {"attivo": "Attivo", "esaurito": "Esaurito", "ritirato": "Ritirato (richiamo)", "annullato": "Annullato"}

    @property
    def etichetta_dati(self):
        try:
            return json.loads(self.dati_etichetta or "{}")
        except ValueError:
            return {}


class LottoIngrediente(db.Model):
    __bind_key__ = BIND
    __tablename__ = "lotti_ingredienti"
    id = db.Column(db.Integer, primary_key=True)
    lotto_id = db.Column(db.Integer, db.ForeignKey("lotti.id"), nullable=False)
    materia_prima_id = db.Column(db.Integer, db.ForeignKey("materie_prime.id"))
    nome = db.Column(db.Text, nullable=False)
    quantita = db.Column(db.Float)
    unita = db.Column(db.Text)
    fornitore_id = db.Column(db.Integer)
    fornitore_nome = db.Column(db.Text)
    lotto_fornitore = db.Column(db.Text)
    rif_documento = db.Column(db.Text)
    produzione_propria = db.Column(db.Boolean, nullable=False, default=False)
    ordine = db.Column(db.Integer, nullable=False, default=0)
    modificato_da = db.Column(db.Text)

    lotto = db.relationship("Lotto", back_populates="ingredienti")
    materia_prima = db.relationship("MateriaPrima")

    @property
    def provenienza(self):
        if self.produzione_propria:
            return "Produzione propria"
        parti = [p for p in (self.fornitore_nome, f"lotto {self.lotto_fornitore}" if self.lotto_fornitore else None,
                             self.rif_documento) if p]
        return " · ".join(parti)


class StampaEtichetta(db.Model):
    __bind_key__ = BIND
    __tablename__ = "stampe_etichette"
    id = db.Column(db.Integer, primary_key=True)
    lotto_id = db.Column(db.Integer, db.ForeignKey("lotti.id"), nullable=False)
    formato_id = db.Column(db.Integer, db.ForeignKey("formati_etichetta.id"))
    stile = db.Column(db.Text, nullable=False)
    n_etichette = db.Column(db.Integer, nullable=False)
    pdf_path = db.Column(db.Text, nullable=False)
    sha256 = db.Column(db.Text, nullable=False)
    dati = db.Column(db.Text, nullable=False)
    creato_da = db.Column(db.Text)
    creato_il = db.Column(db.Text, nullable=False, default=adesso)

    formato = db.relationship("FormatoEtichetta")


class Storico(db.Model):
    """Scritto solo dai trigger del database (schema.py): qui solo per leggerlo."""
    __bind_key__ = BIND
    __tablename__ = "storico"
    id = db.Column(db.Integer, primary_key=True)
    tabella = db.Column(db.Text, nullable=False)
    riga_id = db.Column(db.Integer, nullable=False)
    azione = db.Column(db.Text, nullable=False)
    prima = db.Column(db.Text, nullable=False)
    chi = db.Column(db.Text)
    quando = db.Column(db.Text, nullable=False)
