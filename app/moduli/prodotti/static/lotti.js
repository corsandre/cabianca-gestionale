/* Finestra "Nuovo lotto" (prodotti/_modale_lotto.html), in 3 passi.
 *
 *  FinestraLotto.apri(prodottoId)  nuovo lotto (se il prodotto è indicato si parte dal passo 2)
 *  FinestraLotto.modifica(lotto)   correzione di un lotto esistente (dati da routes/lotti.lotto_json)
 *
 * Il passo 2 chiede al server (/prodotti/lotti/prepara) ricetta, codice, scadenza e ingredienti con le
 * quantità scalate e la provenienza ripresa dall'ultimo lotto. Cambiando data, pezzi o ricetta si
 * ricalcola; il codice e la scadenza si ricalcolano solo finché non li si modifica a mano.
 * Fornitore: si scrive o si sceglie dall'elenco; un nome nuovo diventa un fornitore in Anagrafica.
 */
'use strict';

const FinestraLotto = {
    attuale: 1,
    lottoId: null,
    prodotto: null,
    codiceManuale: false,
    scadenzaManuale: false,
    testoManuale: false,

    el: function (id) { return document.getElementById(id); },

    apri: function (prodottoId) {
        this.lottoId = null;
        this.prodotto = null;
        this.codiceManuale = this.scadenzaManuale = this.testoManuale = false;
        document.querySelector('#modaleLotto .modal-title').textContent = 'Nuovo lotto';
        this.el('lotSalva').innerHTML = '<i class="bi bi-check-lg"></i> Crea lotto';
        this.el('lotData').value = new Date().toISOString().slice(0, 10);
        this.el('lotPezzi').value = '';
        this.el('lotNote').value = '';
        this.el('lotCerca').value = '';
        this.disegnaProdotti();
        bootstrap.Modal.getOrCreateInstance(this.el('modaleLotto')).show();
        if (prodottoId) {
            this.scegliProdotto(parseInt(prodottoId, 10));
        } else {
            this.passo(1);
            setTimeout(function () { FinestraLotto.el('lotCerca').focus(); }, 350);
        }
    },

    /* Correzione: stessi passi, dati del lotto già compilati; nessun ricalcolo automatico. */
    modifica: function (l) {
        this.apri();
        this.lottoId = l.id;
        this.codiceManuale = this.scadenzaManuale = this.testoManuale = true;
        document.querySelector('#modaleLotto .modal-title').textContent = 'Correggi il lotto ' + l.codice;
        this.el('lotSalva').innerHTML = '<i class="bi bi-check-lg"></i> Salva correzioni';
        this.prodotto = (window.PROD_PRODOTTI_LOTTO || []).find(function (p) { return p.id === l.prodotto_id; })
            || { id: l.prodotto_id, nome: '' };
        this.el('lotNomeProdotto').textContent = this.prodotto.nome;
        this.el('lotData').value = l.data;
        this.el('lotPezzi').value = l.pezzi || '';
        this.el('lotCodice').value = l.codice;
        this.el('lotScadenza').value = l.scadenza;
        this.el('lotNote').value = l.note;
        this.el('lotTesto').value = l.ingredienti_testo;
        this.el('lotRighe').innerHTML = '';
        l.righe.forEach(function (r) { FinestraLotto.aggiungiRiga(r); });
        // ricette del prodotto per la tendina, senza toccare le righe
        this.prepara(false).then(function () { FinestraLotto.el('lotRicetta').value = l.ricetta_id || ''; });
        this.passo(2);
    },

    passo: function (n) {
        if (n < 1) n = 1;
        this.attuale = n;
        document.querySelectorAll('#modaleLotto [data-pannello]').forEach(function (p) {
            p.classList.toggle('d-none', parseInt(p.dataset.pannello, 10) !== n);
        });
        document.querySelectorAll('#modaleLotto .prod-passi [data-passo]').forEach(function (p) {
            const k = parseInt(p.dataset.passo, 10);
            p.classList.toggle('attivo', k === n);
            p.classList.toggle('fatto', k < n);
        });
        this.el('lotIndietro').classList.toggle('invisible', n === 1);
        this.el('lotAvanti').classList.toggle('d-none', n === 1 || n === 3);
        this.el('lotSalva').classList.toggle('d-none', n !== 3);
        if (n === 3) this.preparaConferma();
    },

    avanti: function () {
        if (this.attuale === 2) {
            if (!this.el('lotCodice').value.trim()) { prodAvviso('Manca il codice lotto.', 'warning'); return; }
            if (!this.righe().length) { prodAvviso('Aggiungere almeno un ingrediente.', 'warning'); return; }
        }
        this.passo(this.attuale + 1);
    },

    /* ---------------- passo 1 ---------------- */
    disegnaProdotti: function () {
        const q = this.el('lotCerca').value.trim().toLowerCase();
        const lista = (window.PROD_PRODOTTI_LOTTO || []).filter(function (p) {
            return !q || (p.nome + ' ' + p.sigla + ' ' + p.categoria).toLowerCase().indexOf(q) >= 0;
        }).sort(function (a, b) { return (b.recente - a.recente) || a.nome.localeCompare(b.nome); });
        this.el('lotProdotti').innerHTML = lista.map(function (p) {
            return '<div class="col-sm-6 col-lg-4"><button type="button" class="btn btn-outline-secondary w-100 text-start py-2"' +
                ' onclick="FinestraLotto.scegliProdotto(' + p.id + ')">' +
                (p.recente ? '<i class="bi bi-clock-history text-cb-prod me-1" title="fatto di recente"></i>' : '') +
                '<b>' + prodEsc(p.nome) + '</b> <span class="prod-sigla">' + prodEsc(p.sigla) + '</span>' +
                (p.ha_ricetta ? '' : '<div class="small text-muted">senza ricetta</div>') + '</button></div>';
        }).join('') || '<p class="text-muted">Nessun prodotto trovato: crearlo con «Nuovo prodotto».</p>';
    },

    scegliProdotto: function (id) {
        this.prodotto = (window.PROD_PRODOTTI_LOTTO || []).find(function (p) { return p.id === id; }) || { id: id, nome: '' };
        this.el('lotNomeProdotto').textContent = this.prodotto.nome;
        this.el('lotRicetta').innerHTML = '';
        this.prepara('tutto');
        this.passo(2);
    },

    nuovoProdotto: function () {
        ModaleProdotto.apri(null, function (p) {
            window.PROD_PRODOTTI_LOTTO.push({ id: p.id, nome: p.nome_completo, sigla: p.sigla, categoria: p.categoria || '',
                                             ha_ricetta: false, recente: true });
            FinestraLotto.scegliProdotto(p.id);
        });
    },

    /* ---------------- passo 2 ---------------- */
    /* Chiede al server i dati calcolati. modo:
     *   'tutto'  prodotto o ricetta scelti: ricostruisce le righe degli ingredienti
     *   'data'   cambiata la data: solo codice e scadenza
     *   'pezzi'  cambiati i pezzi: solo le quantità (fornitori e lotti già scritti restano)
     *   false    solo la tendina delle ricette (correzione di un lotto) */
    prepara: async function (modo) {
        const par = new URLSearchParams({ prodotto_id: this.prodotto.id, data: this.el('lotData').value,
                                          pezzi: this.el('lotPezzi').value });
        if (this.el('lotRicetta').value) par.set('ricetta_id', this.el('lotRicetta').value);
        try {
            const r = await fetch(window.PROD_URL.lottoPrepara + '?' + par, { credentials: 'same-origin' });
            const j = await r.json();
            if (!j.ok) throw new Error(j.error);
            this.el('lotRicetta').innerHTML = '<option value="">— nessuna —</option>' + j.ricette.map(function (x) {
                return '<option value="' + x.id + '">' + prodEsc(x.etichetta) + (x.resa_pezzi ? ' (resa ' + x.resa_pezzi + ' pz)' : '') + '</option>';
            }).join('');
            this.el('lotRicetta').value = j.ricetta_id || '';
            this.el('lotSenzaRicetta').classList.toggle('d-none', !!j.ricette.length);
            if (!modo) return;
            if (!this.codiceManuale) this.el('lotCodice').value = j.codice;
            if (!this.scadenzaManuale) this.el('lotScadenza').value = j.scadenza;
            if (modo === 'data') return;
            if (modo === 'pezzi') {
                const perMateria = {};
                j.righe.forEach(function (x) { perMateria[x.materia_prima_id] = x.quantita; });
                this.el('lotRighe').querySelectorAll('tr').forEach(function (tr) {
                    const q = perMateria[tr.dataset.materiaId];
                    if (q != null) tr.querySelector('.l-q').value = String(q).replace('.', ',');
                });
                return;
            }
            if (!this.el('lotPezzi').value && j.pezzi) this.el('lotPezzi').value = j.pezzi;
            this.el('lotRighe').innerHTML = '';
            j.righe.forEach(function (x) { FinestraLotto.aggiungiRiga(x); });
            if (!j.righe.length) this.aggiungiRiga({});
            if (!this.testoManuale) this.el('lotTesto').value = j.ingredienti_testo;
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },

    aggiungiRiga: function (r) {
        const tr = document.createElement('tr');
        tr.dataset.materiaId = r.materia_prima_id || '';
        tr.innerHTML =
            '<td><input class="form-control form-control-sm l-nome" list="lotMaterie" placeholder="Ingrediente"></td>' +
            '<td><div class="input-group input-group-sm"><input class="form-control l-q" inputmode="decimal">' +
            '<span class="input-group-text l-unita"></span></div></td>' +
            '<td class="text-center"><input type="checkbox" class="form-check-input l-propria" title="Produzione propria"></td>' +
            '<td><input class="form-control form-control-sm l-forn" list="lotFornitori" placeholder="Fornitore"></td>' +
            '<td><div class="position-relative"><input class="form-control form-control-sm l-lotto" placeholder="Lotto">' +
            (r.precompilato ? '<i class="bi bi-magic text-cb-prod prod-magia" title="Ripreso dall\'ultimo lotto"></i>' : '') + '</div></td>' +
            '<td><input class="form-control form-control-sm l-doc" placeholder="DDT n°…"></td>' +
            '<td><button type="button" class="btn btn-sm btn-outline-secondary" title="Togli"><i class="bi bi-x"></i></button></td>';
        tr.querySelector('.l-nome').value = r.nome || '';
        tr.querySelector('.l-q').value = r.quantita != null ? String(r.quantita).replace('.', ',') : '';
        tr.querySelector('.l-unita').textContent = r.unita || 'g';
        tr.querySelector('.l-propria').checked = !!r.produzione_propria;
        tr.querySelector('.l-forn').value = r.fornitore_nome || '';
        tr.querySelector('.l-lotto').value = r.lotto_fornitore || '';
        tr.querySelector('.l-doc').value = r.rif_documento || '';
        const propria = tr.querySelector('.l-propria');
        const aggiorna = function () {
            ['.l-forn', '.l-lotto', '.l-doc'].forEach(function (c) { tr.querySelector(c).disabled = propria.checked; });
        };
        propria.addEventListener('change', aggiorna);
        aggiorna();
        tr.querySelector('.l-nome').addEventListener('change', function () {
            const n = this.value.trim().toLowerCase();
            const m = (window.PROD_MATERIE_LOTTO || []).find(function (x) { return x.nome.toLowerCase() === n; });
            tr.dataset.materiaId = m ? m.id : '';
            FinestraLotto.testoDaAggiornare();
        });
        tr.querySelector('.l-q').addEventListener('input', function () { FinestraLotto.testoDaAggiornare(); });
        tr.querySelector('button').addEventListener('click', function () { tr.remove(); FinestraLotto.testoDaAggiornare(); });
        this.el('lotRighe').appendChild(tr);
    },

    testoDaAggiornare: function () {
        if (this.testoManuale) return;
        clearTimeout(this._t);
        this._t = setTimeout(function () { FinestraLotto.ripristinaTesto(true); }, 500);
    },

    righe: function () {
        const forn = window.PROD_FORNITORI || [], fid = window.PROD_FORNITORI_ID || [];
        const out = [];
        this.el('lotRighe').querySelectorAll('tr').forEach(function (tr) {
            const nome = tr.querySelector('.l-nome').value.trim();
            if (!nome) return;
            const fnome = tr.querySelector('.l-forn').value.trim();
            const i = forn.findIndex(function (f) { return f.toLowerCase() === fnome.toLowerCase(); });
            out.push({
                materia_prima_id: tr.dataset.materiaId || null, nome: nome,
                quantita: tr.querySelector('.l-q').value.replace(',', '.'), unita: tr.querySelector('.l-unita').textContent,
                produzione_propria: tr.querySelector('.l-propria').checked,
                fornitore_id: i >= 0 ? fid[i] : null, fornitore_nome: fnome,
                lotto_fornitore: tr.querySelector('.l-lotto').value.trim(), rif_documento: tr.querySelector('.l-doc').value.trim(),
            });
        });
        return out;
    },

    /* ---------------- passo 3 ---------------- */
    ripristinaTesto: async function (silenzioso) {
        try {
            const j = await prodPost(window.PROD_URL.lottoTesto, { righe: this.righe() });
            this.el('lotTesto').value = j.testo;
            this.testoManuale = false;
            this.anteprimaTesto();
            if (!silenzioso) prodAvviso('Elenco ricalcolato dagli ingredienti del lotto.', 'info');
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },

    anteprimaTesto: async function () {
        try {
            const j = await prodPost(window.PROD_URL.lottoAnteprimaTesto, { testo: this.el('lotTesto').value });
            this.el('lotAnteprima').innerHTML = j.html || '<span class="text-muted">vuoto</span>';
        } catch (e) { /* anteprima non essenziale */ }
    },

    preparaConferma: function () {
        if (!this.el('lotTesto').value.trim()) this.ripristinaTesto(true); else this.anteprimaTesto();
        const righe = this.righe();
        const senzaLotto = righe.filter(function (r) { return !r.produzione_propria && !r.lotto_fornitore; })
            .map(function (r) { return r.nome; });
        const ric = this.el('lotRicetta');
        const voci = [
            ['Prodotto', prodEsc(this.prodotto.nome)],
            ['Codice lotto', '<span class="prod-codice-lotto">' + prodEsc(this.el('lotCodice').value.toUpperCase()) + '</span>'],
            ['Produzione', prodEsc(this.el('lotData').value.split('-').reverse().join('/'))],
            ['Scadenza', prodEsc((this.el('lotScadenza').value || '—').split('-').reverse().join('/'))],
            ['Pezzi', prodEsc(this.el('lotPezzi').value || '—')],
            ['Ricetta', prodEsc(ric.value ? ric.options[ric.selectedIndex].text : 'nessuna')],
            ['Ingredienti', righe.length + (senzaLotto.length
                ? ' <span class="text-warning"><i class="bi bi-exclamation-triangle"></i> senza lotto fornitore: ' + prodEsc(senzaLotto.join(', ')) + '</span>'
                : ' <span class="text-success"><i class="bi bi-check"></i> tutti tracciati</span>')],
        ];
        this.el('lotRiepilogo').innerHTML = voci.map(function (v) {
            return '<dt class="col-4">' + v[0] + '</dt><dd class="col-8">' + v[1] + '</dd>';
        }).join('');
    },

    salva: async function (bottone) {
        const dati = {
            id: this.lottoId, prodotto_id: this.prodotto.id, ricetta_id: this.el('lotRicetta').value,
            data: this.el('lotData').value, pezzi: this.el('lotPezzi').value,
            codice: this.el('lotCodice').value, scadenza: this.el('lotScadenza').value,
            ingredienti_testo: this.el('lotTesto').value, note: this.el('lotNote').value, righe: this.righe(),
        };
        try {
            const j = await prodInCorso(bottone, prodPost(window.PROD_URL.lottoSalva, dati));
            prodAvviso('Lotto ' + j.codice + ' salvato.' + (j.avviso ? ' ' + j.avviso : ''), j.avviso ? 'warning' : 'success');
            setTimeout(function () { location.href = j.url; }, j.avviso ? 1800 : 500);
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },
};

document.addEventListener('DOMContentLoaded', function () {
    const el = document.getElementById('modaleLotto');
    if (!el) return;
    FinestraLotto.el('lotCerca').addEventListener('input', function () { FinestraLotto.disegnaProdotti(); });
    // cambiando data, pezzi o ricetta si ricalcola solo quello che ne dipende (solo per un lotto nuovo)
    const modi = { lotData: 'data', lotPezzi: 'pezzi', lotRicetta: 'tutto' };
    Object.keys(modi).forEach(function (id) {
        FinestraLotto.el(id).addEventListener('change', function () {
            if (!FinestraLotto.lottoId && FinestraLotto.prodotto) FinestraLotto.prepara(modi[id]);
        });
    });
    FinestraLotto.el('lotCodice').addEventListener('input', function () { FinestraLotto.codiceManuale = true; });
    FinestraLotto.el('lotScadenza').addEventListener('input', function () { FinestraLotto.scadenzaManuale = true; });
    FinestraLotto.el('lotTesto').addEventListener('input', function () {
        FinestraLotto.testoManuale = true;
        clearTimeout(FinestraLotto._a);
        FinestraLotto._a = setTimeout(function () { FinestraLotto.anteprimaTesto(); }, 400);
    });
});
