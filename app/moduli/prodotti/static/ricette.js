/* Editor delle ricette (finestra prodotti/_modale_ricetta.html).
 *
 *  EditorRicetta.nuova(prodottoId)   ricetta nuova (prodotto già scelto se indicato)
 *  EditorRicetta.modifica(id)        carica una ricetta esistente
 *
 * Le materie prime si cercano scrivendo (elenco <datalist> con i nomi). Se il nome scritto non
 * esiste, accanto alla riga compare "＋" per crearla subito: si apre la finestra materia prima con
 * il nome già compilato e, salvata, la riga la usa. L'elenco ingredienti di legge si ricalcola sul
 * server (stessa logica delle etichette: services/ingredienti.py) mezzo secondo dopo ogni modifica.
 */
'use strict';

const EditorRicetta = {
    id: null,

    el: function (id) { return document.getElementById(id); },

    materiaPerNome: function (nome) {
        const n = (nome || '').trim().toLowerCase();
        return (window.PROD_MATERIE || []).find(function (m) { return m.nome.toLowerCase() === n; });
    },

    materiaPerId: function (id) {
        return (window.PROD_MATERIE || []).find(function (m) { return m.id === id; });
    },

    aggiornaElencoMaterie: function () {
        this.el('ricMaterie').innerHTML = (window.PROD_MATERIE || [])
            .map(function (m) { return '<option value="' + prodEsc(m.nome) + '">'; }).join('');
    },

    apri: function (dati, usata) {
        this.id = dati.id || null;
        this.aggiornaElencoMaterie();
        this.el('ricProdotto').value = dati.prodotto_id || '';
        this.el('ricProdotto').disabled = !!dati.id;          // una ricetta non cambia prodotto
        this.el('ricNome').value = dati.nome || '';
        this.el('ricResaPezzi').value = dati.resa_pezzi || '';
        this.el('ricResaKg').value = dati.resa_kg || '';
        this.el('ricProcedimento').value = dati.procedimento || '';
        this.el('ricHaccp').value = dati.note_haccp || '';
        this.el('ricPredefinita').checked = !!dati.predefinita || !dati.id;
        this.el('ricettaUsata').classList.toggle('d-none', !usata);
        const titolo = dati.id ? ('Ricetta v' + dati.versione + (usata ? ' (usata in un lotto)' : '')) : 'Nuova ricetta';
        document.querySelector('#modaleRicetta .modal-title').textContent = titolo;
        this.disegnaContenitori(dati.contenitori || []);
        this.el('ricRighe').innerHTML = '';
        (dati.righe || []).forEach(function (r) { EditorRicetta.aggiungiRiga(r); });
        this.aggiungiRiga();                                   // sempre una riga vuota in fondo
        this.ricalcola();
        bootstrap.Modal.getOrCreateInstance(this.el('modaleRicetta')).show();
    },

    nuova: function (prodottoId) {
        this.apri({ prodotto_id: prodottoId }, false);
    },

    modifica: async function (id) {
        try {
            const r = await fetch(window.PROD_URL.ricettaDati + id, { credentials: 'same-origin' });
            const j = await r.json();
            if (!j.ok) throw new Error(j.error);
            this.apri(j.ricetta, j.ricetta.usata);
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },

    /* Contenitori: una riga per ogni contenitore attivo (spunta + pesi facoltativi). */
    disegnaContenitori: function (scelti) {
        const perId = {};
        scelti.forEach(function (c) { perId[c.contenitore_id] = c; });
        const num = function (v) { return v != null && v !== '' ? String(v).replace('.', ',') : ''; };
        this.el('ricContenitori').innerHTML = (window.PROD_CONTENITORI_RICETTA || []).map(function (c) {
            const s = perId[c.id];
            return '<div class="prod-contenitore-riga d-flex align-items-center gap-2 mb-1" data-id="' + c.id + '">' +
                '<div class="form-check flex-grow-1 mb-0"><input class="form-check-input ric-cont" type="checkbox" id="ric_cont_' + c.id + '"' + (s ? ' checked' : '') + '>' +
                '<label class="form-check-label" for="ric_cont_' + c.id + '">' + prodEsc(c.nome) + '</label></div>' +
                '<input class="form-control form-control-sm ric-cont-peso" style="width:6.5rem" inputmode="decimal" title="Peso netto in etichetta, se diverso" placeholder="' +
                prodEsc(c.peso_netto ? String(c.peso_netto).replace('.', ',') + ' ' + c.unita : 'peso') + '" value="' + num(s && s.peso_netto) + '">' +
                '<input class="form-control form-control-sm ric-cont-sgocc" style="width:6.5rem" inputmode="decimal" title="Peso sgocciolato (sottoli, sottaceti)" placeholder="sgocciolato" value="' + num(s && s.peso_sgocciolato) + '">' +
                '</div>';
        }).join('') || '<span class="small text-muted">Nessun contenitore: crearli nella pagina Contenitori.</span>';
        this.el('ricContenitori').querySelectorAll('.prod-contenitore-riga').forEach(function (riga) {
            const aggiorna = function () {
                const on = riga.querySelector('.ric-cont').checked;
                riga.querySelectorAll('input.form-control').forEach(function (i) { i.disabled = !on; });
            };
            riga.querySelector('.ric-cont').addEventListener('change', aggiorna);
            aggiorna();
        });
    },

    contenitori: function () {
        const out = [];
        this.el('ricContenitori').querySelectorAll('.prod-contenitore-riga').forEach(function (riga) {
            if (!riga.querySelector('.ric-cont').checked) return;
            out.push({ contenitore_id: parseInt(riga.dataset.id, 10),
                       peso_netto: riga.querySelector('.ric-cont-peso').value.replace(',', '.'),
                       peso_sgocciolato: riga.querySelector('.ric-cont-sgocc').value.replace(',', '.') });
        });
        return out;
    },

    aggiungiRiga: function (r) {
        r = r || {};
        const riga = document.createElement('div');
        riga.className = 'prod-riga';
        const opzioni = (window.PROD_UNITA || ['g']).map(function (u) {
            return '<option' + (u === (r.unita || 'g') ? ' selected' : '') + '>' + u + '</option>';
        }).join('');
        riga.innerHTML =
            '<div class="position-relative">' +
            '  <input class="form-control ric-materia" list="ricMaterie" placeholder="Materia prima…" autocomplete="off">' +
            '  <div class="prod-perc ric-perc"></div>' +
            '</div>' +
            '<input class="form-control ric-quantita" inputmode="decimal" placeholder="q.tà">' +
            '<select class="form-select ric-unita">' + opzioni + '</select>' +
            '<button type="button" class="btn btn-outline-secondary btn-sm ric-azione" tabindex="-1" title="Togli la riga"><i class="bi bi-x"></i></button>';
        const m = r.materia_prima_id ? this.materiaPerId(r.materia_prima_id) : null;
        riga.querySelector('.ric-materia').value = m ? m.nome : (r.nome || '');
        riga.querySelector('.ric-quantita').value = r.quantita != null ? String(r.quantita).replace('.', ',') : '';
        riga.querySelector('.ric-materia').addEventListener('input', function () { EditorRicetta.rigaCambiata(riga); });
        riga.querySelector('.ric-quantita').addEventListener('input', function () { EditorRicetta.rigaCambiata(riga); });
        riga.querySelector('.ric-unita').addEventListener('change', function () { EditorRicetta.ricalcola(); });
        riga.querySelector('.ric-azione').addEventListener('click', function () { EditorRicetta.azioneRiga(riga); });
        // Invio sulla quantità = riga successiva (comodo da tastiera)
        riga.querySelector('.ric-quantita').addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); EditorRicetta.focusSuccessiva(riga); }
        });
        this.el('ricRighe').appendChild(riga);
        this.statoRiga(riga);
        return riga;
    },

    focusUltima: function () {
        const righe = this.el('ricRighe').querySelectorAll('.prod-riga');
        righe[righe.length - 1].querySelector('.ric-materia').focus();
    },

    focusSuccessiva: function (riga) {
        const prossima = riga.nextElementSibling || this.aggiungiRiga();
        prossima.querySelector('.ric-materia').focus();
    },

    /* La riga ha un nome che non corrisponde a nessuna materia: il pulsante diventa "＋ crea". */
    statoRiga: function (riga) {
        const nome = riga.querySelector('.ric-materia').value.trim();
        const m = this.materiaPerNome(nome);
        riga.dataset.materiaId = m ? m.id : '';
        // con la materia scelta si propone la sua unità (solo se la quantità è ancora vuota)
        if (m && !riga.querySelector('.ric-quantita').value) riga.querySelector('.ric-unita').value = m.unita || 'g';
        const nuova = nome && !m;
        const bottone = riga.querySelector('.ric-azione');
        bottone.innerHTML = nuova ? '<i class="bi bi-plus-lg"></i>' : '<i class="bi bi-x"></i>';
        bottone.title = nuova ? 'Crea la materia prima «' + nome + '»' : 'Togli la riga';
        bottone.classList.toggle('btn-warning', nuova);
        bottone.classList.toggle('btn-outline-secondary', !nuova);
        riga.querySelector('.ric-materia').classList.toggle('is-invalid', nuova);
    },

    rigaCambiata: function (riga) {
        this.statoRiga(riga);
        // scrivendo nell'ultima riga ne compare una nuova vuota
        if (!riga.nextElementSibling && riga.querySelector('.ric-materia').value.trim()) this.aggiungiRiga();
        this.ricalcola();
    },

    azioneRiga: function (riga) {
        const nome = riga.querySelector('.ric-materia').value.trim();
        if (nome && !this.materiaPerNome(nome)) {
            this.nuovaMateria(nome, riga);
        } else if (this.el('ricRighe').children.length > 1) {
            riga.remove();
            this.ricalcola();
        }
    },

    /* Crea una materia prima senza lasciare l'editor: la finestra materia si apre sopra. */
    nuovaMateria: function (nome, riga) {
        ModaleMateria.apri({ nome: nome || '', nome_etichetta: (nome || '').toLowerCase() }, function (materia) {
            window.PROD_MATERIE.push(materia);
            EditorRicetta.aggiornaElencoMaterie();
            const r = riga || EditorRicetta.aggiungiRiga();
            r.querySelector('.ric-materia').value = materia.nome;
            EditorRicetta.rigaCambiata(r);
            r.querySelector('.ric-quantita').focus();
        });
    },

    righe: function () {
        const out = [];
        this.el('ricRighe').querySelectorAll('.prod-riga').forEach(function (r) {
            const id = parseInt(r.dataset.materiaId || '0', 10);
            const q = r.querySelector('.ric-quantita').value.replace(',', '.');
            if (id || q) out.push({ materia_prima_id: id || null, quantita: q, unita: r.querySelector('.ric-unita').value });
        });
        return out;
    },

    ricalcola: function () {
        clearTimeout(this._timer);
        this._timer = setTimeout(function () { EditorRicetta.anteprima(); }, 450);
    },

    anteprima: async function () {
        const righe = this.righe().filter(function (r) { return r.materia_prima_id; });
        const box = this.el('ricAnteprima');
        if (!righe.length) {
            box.innerHTML = '<span class="text-muted">Aggiungere gli ingredienti…</span>';
            this.el('ricAllergeni').innerHTML = '';
            this.el('ricTotale').textContent = '0';
            return;
        }
        try {
            const j = await prodPost(window.PROD_URL.ricettaAnteprima, { righe: righe });
            box.innerHTML = j.html;
            this.el('ricAllergeni').innerHTML = j.allergeni_testo
                ? '<i class="bi bi-exclamation-triangle text-warning"></i> Allergeni: <b>' + prodEsc(j.allergeni_testo) + '</b>'
                : '<span class="text-muted">Nessun allergene tra gli ingredienti.</span>';
            // percentuale accanto a ogni riga
            this.el('ricRighe').querySelectorAll('.prod-riga').forEach(function (r) {
                const m = EditorRicetta.materiaPerId(parseInt(r.dataset.materiaId || '0', 10));
                const p = m ? j.percentuali[m.nome_etichetta] : null;
                r.querySelector('.ric-perc').textContent = p != null ? p.toLocaleString('it-IT') + ' %' : '';
            });
            let totale = 0;
            righe.forEach(function (r) {
                const f = { g: 1, ml: 1, kg: 1000, l: 1000 }[r.unita];
                if (f) totale += (parseFloat(r.quantita) || 0) * f;
            });
            this.el('ricTotale').textContent = totale >= 1000
                ? (totale / 1000).toLocaleString('it-IT', { maximumFractionDigits: 2 }) + ' kg'
                : totale.toLocaleString('it-IT') + ' g';
        } catch (e) { box.textContent = e.message; }
    },

    salva: async function (bottone) {
        const nonCreate = [];
        this.el('ricRighe').querySelectorAll('.prod-riga').forEach(function (r) {
            const nome = r.querySelector('.ric-materia').value.trim();
            if (nome && !r.dataset.materiaId) nonCreate.push(nome);
        });
        if (nonCreate.length) {
            prodAvviso('Prima creare le materie prime evidenziate (pulsante giallo «＋»): ' + nonCreate.join(', '), 'warning');
            return;
        }
        const dati = {
            id: this.id, prodotto_id: this.el('ricProdotto').value, nome: this.el('ricNome').value,
            resa_pezzi: this.el('ricResaPezzi').value, resa_kg: this.el('ricResaKg').value,
            procedimento: this.el('ricProcedimento').value, note_haccp: this.el('ricHaccp').value,
            predefinita: this.el('ricPredefinita').checked, righe: this.righe(), contenitori: this.contenitori(),
        };
        try {
            const j = await prodInCorso(bottone, prodPost(window.PROD_URL.ricettaSalva, dati));
            bootstrap.Modal.getInstance(this.el('modaleRicetta')).hide();
            prodAvviso(j.messaggio || ('Ricetta salvata (v' + j.ricetta.versione + ').'), j.messaggio ? 'info' : 'success');
            setTimeout(function () { location.reload(); }, j.messaggio ? 1800 : 600);
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },
};

/* Con due finestre aperte (ricetta + materia sopra), Bootstrap toglie lo scorrimento della pagina
   alla chiusura della seconda: lo si ripristina se la ricetta è ancora aperta. */
document.addEventListener('hidden.bs.modal', function () {
    if (document.querySelector('.modal.show')) document.body.classList.add('modal-open');
});
