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


def peso_testo(peso, unita="g"):
    """'150 g', '750 ml'; '' se il peso non c'è (peso variabile)."""
    return f"{peso:g} {unita or 'g'}".replace(".", ",") if peso else ""      # in etichetta: virgola decimale


def peso_kg(peso, unita="g"):
    """Peso in kg (ml e l come g e kg: per scalare le dosi basta)."""
    if not peso:
        return 0.0
    return peso if unita in ("kg", "l") else peso / 1000.0


contenitori_formati = db.Table(
    "contenitori_formati",
    db.Column("contenitore_id", db.Integer, db.ForeignKey("contenitori.id"), primary_key=True),
    db.Column("formato_id", db.Integer, db.ForeignKey("formati_etichetta.id"), primary_key=True),
    bind_key=BIND,
)


class Contenitore(db.Model):
    """Vasetto, bottiglia, busta…: peso standard e fogli di etichetta adatti (schema.py, migrazione 6)."""
    __bind_key__ = BIND
    __tablename__ = "contenitori"
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.Text, nullable=False, unique=True)
    peso_netto = db.Column(db.Float)
    unita = db.Column(db.Text, nullable=False, default="g")
    formato_predefinito_id = db.Column(db.Integer, db.ForeignKey("formati_etichetta.id"))
    ordine = db.Column(db.Integer, nullable=False, default=0)
    attivo = db.Column(db.Boolean, nullable=False, default=True)
    note = db.Column(db.Text)

    formato_predefinito = db.relationship("FormatoEtichetta")
    formati = db.relationship("FormatoEtichetta", secondary=contenitori_formati, order_by="FormatoEtichetta.id")

    @property
    def peso_testo(self):
        return peso_testo(self.peso_netto, self.unita) or "peso variabile"


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

    # peso_netto, unita, formato_etichetta_id: colonne della 1.x, non più usate (dalla 2.0.0 il peso è del
    # contenitore e il formato si sceglie per la confezione del lotto)

    @property
    def nome_completo(self):
        return self.nome

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
    contenitori = db.relationship("RicettaContenitore", cascade="all, delete-orphan",
                                  order_by="RicettaContenitore.id")

    @property
    def etichetta(self):
        return f"v{self.versione}" + (f" – {self.nome}" if self.nome else "")

    @property
    def contenitori_testo(self):
        return ", ".join(rc.contenitore.nome for rc in self.contenitori)

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


class RicettaContenitore(db.Model):
    """Contenitore in cui si può confezionare la ricetta, con i pesi propri se diversi dallo standard."""
    __bind_key__ = BIND
    __tablename__ = "ricette_contenitori"
    id = db.Column(db.Integer, primary_key=True)
    ricetta_id = db.Column(db.Integer, db.ForeignKey("ricette.id"), nullable=False)
    contenitore_id = db.Column(db.Integer, db.ForeignKey("contenitori.id"), nullable=False)
    peso_netto = db.Column(db.Float)
    peso_sgocciolato = db.Column(db.Float)

    contenitore = db.relationship("Contenitore")

    @property
    def peso_effettivo(self):
        return self.peso_netto if self.peso_netto else self.contenitore.peso_netto


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
    cancellazione_autorizzata = db.Column(db.Integer, nullable=False, default=0)   # solo routes/lotti.elimina_lotto

    prodotto = db.relationship("Prodotto")
    ricetta = db.relationship("Ricetta")
    ingredienti = db.relationship("LottoIngrediente", order_by="LottoIngrediente.ordine",
                                  back_populates="lotto")
    stampe = db.relationship("StampaEtichetta", order_by="StampaEtichetta.id.desc()")
    confezioni = db.relationship("LottoConfezione", order_by="LottoConfezione.ordine", back_populates="lotto")

    STATI = {"attivo": "Attivo", "esaurito": "Esaurito", "ritirato": "Ritirato (richiamo)", "annullato": "Annullato"}

    @property
    def confezioni_testo(self):
        """'40 × 150 g, 12 × 300 g' (o i pezzi, per un lotto senza confezioni)."""
        parti = [c.testo for c in self.confezioni if c.pezzi]
        if parti:
            return ", ".join(parti)
        return f"{self.pezzi_prodotti} pz" if self.pezzi_prodotti else ""

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


class LottoConfezione(db.Model):
    """Quanti pezzi di un contenitore ha dato il lotto, con la copia di nome e pesi (vanno in etichetta)."""
    __bind_key__ = BIND
    __tablename__ = "lotti_confezioni"
    id = db.Column(db.Integer, primary_key=True)
    lotto_id = db.Column(db.Integer, db.ForeignKey("lotti.id"), nullable=False)
    contenitore_id = db.Column(db.Integer, db.ForeignKey("contenitori.id"))
    nome = db.Column(db.Text, nullable=False)
    peso_netto = db.Column(db.Float)
    peso_sgocciolato = db.Column(db.Float)
    unita = db.Column(db.Text, nullable=False, default="g")
    pezzi = db.Column(db.Integer, nullable=False, default=0)
    ordine = db.Column(db.Integer, nullable=False, default=0)
    modificato_da = db.Column(db.Text)

    lotto = db.relationship("Lotto", back_populates="confezioni")
    contenitore = db.relationship("Contenitore")

    @property
    def peso_testo(self):
        return peso_testo(self.peso_netto, self.unita)

    @property
    def testo(self):
        """'40 × 150 g' oppure '6 × Salume (peso variabile)'."""
        return f"{self.pezzi} × {self.peso_testo or self.nome}"

    @property
    def kg(self):
        return (self.pezzi or 0) * peso_kg(self.peso_netto, self.unita)


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
    confezione_id = db.Column(db.Integer)          # lotti_confezioni.id (la confezione può essere poi corretta)

    formato = db.relationship("FormatoEtichetta")

    @property
    def confezione_testo(self):
        try:
            return json.loads(self.dati).get("confezione") or ""
        except ValueError:
            return ""


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
