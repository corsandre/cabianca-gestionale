/* Finestra "Nuovo lotto" (prodotti/_modale_lotto.html), in 3 passi.
 *
 *  FinestraLotto.apri(prodottoId)  nuovo lotto (se il prodotto è indicato si parte dal passo 2)
 *  FinestraLotto.modifica(lotto)   correzione di un lotto esistente (dati da routes/lotti.lotto_json)
 *
 * Il passo 2 chiede al server (/prodotti/lotti/prepara) ricetta, codice, scadenza, contenitori compatibili
 * con la ricetta e ingredienti con le quantità scalate e la provenienza ripresa dall'ultimo lotto.
 * Confezioni: righe contenitore + pezzi (un lotto può andare in più contenitori); le dosi si scalano sui kg
 * totali (o sui pezzi, se la ricetta non ha la resa in kg). Cambiando data, confezioni o ricetta si
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
    contenitori: [],

    el: function (id) { return document.getElementById(id); },

    apri: function (prodottoId) {
        this.lottoId = null;
        this.prodotto = null;
        this.codiceManuale = this.scadenzaManuale = this.testoManuale = false;
        document.querySelector('#modaleLotto .modal-title').textContent = 'Nuovo lotto';
        this.el('lotSalva').innerHTML = '<i class="bi bi-check-lg"></i> Crea lotto';
        this.el('lotData').value = new Date().toISOString().slice(0, 10);
        this.el('lotConfezioni').innerHTML = '';
        this.el('lotTotale').textContent = '';
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
        this.el('lotCodice').value = l.codice;
        this.el('lotScadenza').value = l.scadenza;
        this.el('lotNote').value = l.note;
        this.el('lotTesto').value = l.ingredienti_testo;
        this.el('lotRighe').innerHTML = '';
        l.righe.forEach(function (r) { FinestraLotto.aggiungiRiga(r); });
        // ricette e contenitori del prodotto per le tendine, senza toccare le righe
        this.el('lotRicetta').innerHTML = l.ricetta_id ? '<option value="' + l.ricetta_id + '"></option>' : '';
        this.el('lotRicetta').value = l.ricetta_id || '';
        this.prepara(false).then(function () {
            FinestraLotto.el('lotRicetta').value = l.ricetta_id || '';
            FinestraLotto.el('lotConfezioni').innerHTML = '';
            (l.confezioni || []).forEach(function (c) { FinestraLotto.aggiungiConfezione(c); });
            if (!(l.confezioni || []).length) FinestraLotto.aggiungiConfezione({ pezzi: l.pezzi });
            FinestraLotto.mostraTotale();
        });
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
            if (!this.confezioni().some(function (c) { return c.contenitore_id && parseInt(c.pezzi, 10) > 0; })) {
                prodAvviso('Indicare quanti pezzi e in quale contenitore (es. 40 vasetti da 150 g).', 'warning'); return;
            }
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
     *   'pezzi'  cambiate le confezioni: solo le quantità (fornitori e lotti già scritti restano)
     *   false    solo le tendine di ricette e contenitori (correzione di un lotto) */
    prepara: async function (modo) {
        const par = new URLSearchParams({ prodotto_id: this.prodotto.id, data: this.el('lotData').value });
        if (this.el('lotRicetta').value) par.set('ricetta_id', this.el('lotRicetta').value);
        // con 'tutto' (prodotto o ricetta nuovi) le confezioni le propone il server
        if (modo !== 'tutto') par.set('confezioni', JSON.stringify(this.confezioni()));
        try {
            const r = await fetch(window.PROD_URL.lottoPrepara + '?' + par, { credentials: 'same-origin' });
            const j = await r.json();
            if (!j.ok) throw new Error(j.error);
            this.el('lotRicetta').innerHTML = '<option value="">— nessuna —</option>' + j.ricette.map(function (x) {
                const resa = x.resa_kg ? ' (resa ' + String(x.resa_kg).replace('.', ',') + ' kg)' : (x.resa_pezzi ? ' (resa ' + x.resa_pezzi + ' pz)' : '');
                return '<option value="' + x.id + '">' + prodEsc(x.etichetta) + resa + '</option>';
            }).join('');
            this.el('lotRicetta').value = j.ricetta_id || '';
            this.el('lotSenzaRicetta').classList.toggle('d-none', !!j.ricette.length);
            this.contenitori = j.contenitori || [];
            this.aggiornaTendineConfezioni();
            this.fattore = j.fattore;
            this.mostraTotale();
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
            this.el('lotConfezioni').innerHTML = '';
            (j.confezioni || []).forEach(function (c) { FinestraLotto.aggiungiConfezione(c); });
            if (!(j.confezioni || []).length) this.aggiungiConfezione({});
            this.mostraTotale();
            this.el('lotRighe').innerHTML = '';
            j.righe.forEach(function (x) { FinestraLotto.aggiungiRiga(x); });
            if (!j.righe.length) this.aggiungiRiga({});
            if (!this.testoManuale) this.el('lotTesto').value = j.ingredienti_testo;
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },

    /* ---------------- confezioni ---------------- */
    opzioniContenitori: function (scelto, nomeVecchio) {
        let html = '<option value="">— contenitore —</option>';
        let trovato = false;
        this.contenitori.forEach(function (c) {
            if (String(c.id) === String(scelto)) trovato = true;
            html += '<option value="' + c.id + '"' + (String(c.id) === String(scelto) ? ' selected' : '') + '>' +
                prodEsc(c.nome) + (c.peso_testo && c.nome.indexOf(c.peso_testo) < 0 ? ' · ' + prodEsc(c.peso_testo) : '') + '</option>';
        });
        // confezione salvata con un contenitore che la ricetta non propone più (o dei lotti della 1.x)
        if (scelto && !trovato) html += '<option value="' + scelto + '" selected>' + prodEsc(nomeVecchio || 'contenitore ' + scelto) + '</option>';
        if (!scelto && nomeVecchio) html += '<option value="" selected>' + prodEsc(nomeVecchio) + ' (da scegliere)</option>';
        return html;
    },

    aggiungiConfezione: function (c) {
        const tr = document.createElement('tr');
        tr.dataset.id = c.id || '';
        tr.dataset.nome = c.nome || '';
        tr.innerHTML =
            '<td data-etichetta="Contenitore"><select class="form-select form-select-sm c-cont"></select></td>' +
            '<td data-etichetta="Pezzi" style="width:8rem"><div class="input-group input-group-sm"><input class="form-control c-pezzi" inputmode="numeric" placeholder="pezzi">' +
            '<span class="input-group-text">pz</span></div></td>' +
            '<td class="prod-togli"><button type="button" class="btn btn-sm btn-outline-secondary" title="Togli"><i class="bi bi-x"></i></button></td>';
        tr.querySelector('.c-cont').innerHTML = this.opzioniContenitori(c.contenitore_id, c.nome);
        tr.querySelector('.c-pezzi').value = c.pezzi != null ? c.pezzi : '';
        tr.querySelector('.c-cont').addEventListener('change', function () { FinestraLotto.confezioniCambiate(); });
        tr.querySelector('.c-pezzi').addEventListener('input', function () { FinestraLotto.confezioniCambiate(); });
        tr.querySelector('button').addEventListener('click', function () { tr.remove(); FinestraLotto.confezioniCambiate(); });
        this.el('lotConfezioni').appendChild(tr);
    },

    aggiornaTendineConfezioni: function () {
        this.el('lotConfezioni').querySelectorAll('tr').forEach(function (tr) {
            const sel = tr.querySelector('.c-cont');
            sel.innerHTML = FinestraLotto.opzioniContenitori(sel.value, tr.dataset.nome);
        });
    },

    confezioni: function () {
        const out = [];
        this.el('lotConfezioni').querySelectorAll('tr').forEach(function (tr) {
            const cid = tr.querySelector('.c-cont').value, pezzi = tr.querySelector('.c-pezzi').value.trim();
            if (cid || pezzi) out.push({ id: tr.dataset.id || null, contenitore_id: cid || null, pezzi: pezzi });
        });
        return out;
    },

    /* Totale: pezzi e kg (dai pesi dei contenitori proposti dalla ricetta). */
    mostraTotale: function () {
        let pezzi = 0, kg = 0;
        const perId = {};
        this.contenitori.forEach(function (c) { perId[c.id] = c; });
        this.confezioni().forEach(function (c) {
            const n = parseInt(c.pezzi, 10) || 0, k = perId[c.contenitore_id];
            pezzi += n;
            if (k && k.peso_netto) kg += n * k.peso_netto * ({ kg: 1000, l: 1000 }[k.unita] || 1) / 1000;
        });
        this.el('lotTotale').textContent = pezzi ? 'Totale: ' + pezzi + ' pezzi' +
            (kg ? ' · ' + kg.toLocaleString('it-IT', { maximumFractionDigits: 2 }) + ' kg' : '') +
            (this.fattore && this.fattore !== 1 && !this.lottoId ? ' · dosi della ricetta × ' + String(this.fattore).replace('.', ',') : '') : '';
    },

    confezioniCambiate: function () {
        this.mostraTotale();
        if (this.lottoId || !this.prodotto) return;           // correzione: niente ricalcolo delle dosi
        clearTimeout(this._c);
        this._c = setTimeout(function () { FinestraLotto.prepara('pezzi'); }, 500);
    },

    testoConfezioni: function () {
        const perId = {};
        this.contenitori.forEach(function (c) { perId[c.id] = c; });
        return this.confezioni().filter(function (c) { return parseInt(c.pezzi, 10) > 0; }).map(function (c) {
            const k = perId[c.contenitore_id];
            return c.pezzi + ' × ' + (k ? k.nome : '?');
        }).join(', ');
    },

    /* ---------------- ingredienti ---------------- */
    aggiungiRiga: function (r) {
        const tr = document.createElement('tr');
        tr.dataset.materiaId = r.materia_prima_id || '';
        // data-etichetta: su telefono le celle diventano una scheda con il nome del campo (prodotti.css)
        tr.innerHTML =
            '<td data-etichetta="Ingrediente"><input class="form-control form-control-sm l-nome" list="lotMaterie" placeholder="Ingrediente"></td>' +
            '<td data-etichetta="Quantità"><div class="input-group input-group-sm"><input class="form-control l-q" inputmode="decimal">' +
            '<span class="input-group-text l-unita"></span></div></td>' +
            '<td data-etichetta="Propria" class="text-center"><input type="checkbox" class="form-check-input l-propria" title="Produzione propria"></td>' +
            '<td data-etichetta="Fornitore"><input class="form-control form-control-sm l-forn" list="lotFornitori" placeholder="Fornitore"></td>' +
            '<td data-etichetta="Lotto"><div class="position-relative"><input class="form-control form-control-sm l-lotto" placeholder="Lotto">' +
            (r.precompilato ? '<i class="bi bi-magic text-cb-prod prod-magia" title="Ripreso dall\'ultimo lotto"></i>' : '') + '</div></td>' +
            '<td data-etichetta="DDT/fattura"><input class="form-control form-control-sm l-doc" placeholder="DDT n°…"></td>' +
            '<td class="prod-togli"><button type="button" class="btn btn-sm btn-outline-secondary" title="Togli"><i class="bi bi-x"></i></button></td>';
        tr.querySelector('.l-nome').value = r.nome || '';
        tr.querySelector('.l-q').value = r.quantita != null ? String(r.quantita).replace('.', ',') : '';
        tr.querySelector('.l-unita').textContent = r.unita || 'g';
        tr.querySelector('.l-propria').checked = !!r.produzione_propria;
        tr.querySelector('.l-forn').value = r.fornitore_nome || '';
        tr.querySelector('.l-lotto').value = r.lotto_fornitore || '';
        tr.querySelector('.l-doc').value = r.rif_documento || '';
        const propria = tr.querySelector('.l-propria');
        // produzione propria: niente fornitore né DDT; il lotto resta come riferimento interno facoltativo
        // (es. "raccolta 10/11 campo nord"), utile per la tracciabilità
        const aggiorna = function () {
            ['.l-forn', '.l-doc'].forEach(function (c) { tr.querySelector(c).disabled = propria.checked; });
            tr.querySelector('.l-lotto').placeholder = propria.checked ? 'rif. interno (facolt.)' : 'Lotto';
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
            ['Confezioni', prodEsc(this.testoConfezioni() || '—')],
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
            data: this.el('lotData').value, confezioni: this.confezioni(),
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
    // cambiando data o ricetta si ricalcola solo quello che ne dipende (solo per un lotto nuovo);
    // le confezioni hanno i loro eventi (confezioniCambiate)
    const modi = { lotData: 'data', lotRicetta: 'tutto' };
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
