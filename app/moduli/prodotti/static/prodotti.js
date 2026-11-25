/* JavaScript comune del modulo Prodotti (caricato da prodotti/_base.html).
 *
 *  prodPost(url, dati)        salvataggio JSON con token CSRF (rinnovato da solo se scaduto)
 *  prodAvviso(testo, tipo)    messaggio in alto a destra
 *  prodCerca(input, elenco)   filtro di una lista mentre si scrive
 *  ModaleMateria              finestra "materia prima" (usata anche dall'editor delle ricette)
 *  ModaleProdotto             finestra "prodotto"
 * L'editor delle ricette è in ricette.js, la finestra "Nuovo lotto" in lotti.js.
 */
'use strict';

function prodToken() {
    const m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
}

async function prodPost(url, dati, giaRinnovato) {
    const resp = await fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': prodToken(), 'X-Requested-With': 'fetch' },
        body: JSON.stringify(dati || {}),
    });
    let json = null;
    try { json = await resp.json(); } catch (e) { /* risposta non JSON */ }
    if (json && json.csrf_scaduto && !giaRinnovato) {
        // pagina aperta da tanto: token nuovo e si riprova, senza perdere quanto scritto
        const r = await fetch('/csrf-token', { credentials: 'same-origin' });
        const t = await r.json();
        document.querySelector('meta[name="csrf-token"]').content = t.csrf_token;
        return prodPost(url, dati, true);
    }
    if (!resp.ok || !json || json.ok === false) {
        if (resp.status === 403) throw new Error('Permesso negato: il tuo utente può solo consultare.');
        throw new Error((json && json.error) || 'Errore del server (' + resp.status + ')');
    }
    return json;
}

function prodAvviso(testo, tipo) {
    let box = document.getElementById('prod-avvisi');
    if (!box) {
        box = document.createElement('div');
        box.id = 'prod-avvisi';
        box.className = 'prod-avvisi';
        document.body.appendChild(box);
    }
    const el = document.createElement('div');
    el.className = 'alert alert-' + (tipo || 'success') + ' shadow-sm py-2 px-3 mb-2';
    el.textContent = testo;
    box.appendChild(el);
    setTimeout(function () { el.remove(); }, tipo === 'danger' ? 9000 : 4500);
}

/* Filtra gli elementi [data-cerca] dentro `contenitore` mentre si scrive in `input`. */
function prodCerca(input, contenitore) {
    input.addEventListener('input', function () {
        const q = input.value.trim().toLowerCase();
        contenitore.querySelectorAll('[data-cerca]').forEach(function (el) {
            el.classList.toggle('d-none', q && el.dataset.cerca.toLowerCase().indexOf(q) < 0);
        });
    });
}

function prodEsc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

/* Imposta i campi di un form da un oggetto: name="x" ← dati.x (checkbox: true/false). */
function prodRiempi(form, dati) {
    form.reset();
    Object.keys(dati || {}).forEach(function (k) {
        const campi = form.querySelectorAll('[name="' + k + '"]');
        campi.forEach(function (c) {
            if (c.type === 'checkbox') {
                c.checked = Array.isArray(dati[k]) ? dati[k].indexOf(c.value) >= 0 : !!dati[k];
            } else {
                c.value = dati[k] == null ? '' : dati[k];
            }
        });
    });
}

/* Legge i campi di un form in un oggetto (checkbox multipli con lo stesso nome → lista). */
function prodLeggi(form) {
    const out = {};
    form.querySelectorAll('[name]').forEach(function (c) {
        if (c.type === 'checkbox') {
            const multipli = form.querySelectorAll('[name="' + c.name + '"]').length > 1;
            if (multipli) {
                out[c.name] = out[c.name] || [];
                if (c.checked) out[c.name].push(c.value);
            } else {
                out[c.name] = c.checked;
            }
        } else if (c.type !== 'button') {
            out[c.name] = c.value;
        }
    });
    return out;
}

/* Pulsante "in corso": disattivato con rotellina finché la promessa non finisce. */
/* Indicatore di attesa dentro un riquadro (anteprime, PDF): rotella, messaggio, secondi che passano e barra
   animata. Il server non sa quanto manca, quindi la barra non ha percentuale: i secondi fanno vedere che la
   pagina non è bloccata. Restituisce la funzione che lo toglie.
   uso:  const fine = prodAttesa(box, 'Preparo l’anteprima…');  …  fine();                                 */
function prodAttesa(box, testo) {
    const v = document.createElement('div');
    v.className = 'prod-attesa';
    v.setAttribute('role', 'status');
    v.innerHTML = '<div class="spinner-border text-cb-prod" aria-hidden="true"></div>' +
        '<div class="prod-attesa-testo"></div><div class="small text-muted prod-attesa-secondi">&nbsp;</div>' +
        '<div class="progress prod-attesa-barra"><div class="progress-bar progress-bar-striped progress-bar-animated" style="width:100%"></div></div>';
    v.querySelector('.prod-attesa-testo').textContent = testo || 'Un momento…';
    box.classList.add('prod-in-attesa');
    box.appendChild(v);
    const inizio = Date.now();
    const t = setInterval(function () {
        const s = Math.round((Date.now() - inizio) / 1000);
        v.querySelector('.prod-attesa-secondi').textContent = s >= 2 ? s + ' s' + (s >= 15 ? ' – quasi fatto, non chiudere la pagina' : '') : ' ';
    }, 500);
    return function () { clearInterval(t); v.remove(); if (!box.querySelector('.prod-attesa')) box.classList.remove('prod-in-attesa'); };
}

async function prodInCorso(bottone, promessa) {
    const html = bottone.innerHTML;
    bottone.disabled = true;
    bottone.innerHTML = '<span class="spinner-border spinner-border-sm"></span> ' + bottone.textContent.trim();
    try { return await promessa; } finally { bottone.disabled = false; bottone.innerHTML = html; }
}

/* ------------------------------------------------------------------ finestra materia prima */
const ModaleMateria = {
    _dopo: null,
    el: function () { return document.getElementById('modaleMateria'); },
    apri: function (materia, dopoSalvataggio) {
        const el = this.el();
        const form = el.querySelector('form');
        prodRiempi(form, Object.assign({ unita: 'g', attiva: true }, materia || {}));
        el.querySelector('.modal-title').textContent = materia && materia.id ? 'Modifica materia prima' : 'Nuova materia prima';
        el.querySelector('[name="nuovo_fornitore"]').value = '';
        this._dopo = dopoSalvataggio || null;
        this.aggiornaFornitore();
        bootstrap.Modal.getOrCreateInstance(el).show();
        setTimeout(function () { form.querySelector('[name="nome"]').focus(); }, 300);
    },
    aggiornaFornitore: function () {
        const form = this.el().querySelector('form');
        const propria = form.querySelector('[name="produzione_propria"]').checked;
        form.querySelector('.prod-fornitore').classList.toggle('d-none', propria);
    },
    salva: async function (bottone) {
        const form = this.el().querySelector('form');
        const dati = prodLeggi(form);
        try {
            const r = await prodInCorso(bottone, prodPost(form.action, dati));
            bootstrap.Modal.getInstance(this.el()).hide();
            prodAvviso('Materia prima salvata: ' + r.materia.nome);
            if (this._dopo) this._dopo(r.materia); else location.reload();
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },
};

/* ------------------------------------------------------------------ finestra prodotto */
const ModaleProdotto = {
    _dopo: null,
    el: function () { return document.getElementById('modaleProdotto'); },
    /* dopoSalvataggio(prodotto): se indicato si resta nella pagina (es. finestra Nuovo lotto),
       altrimenti si va alla scheda del prodotto. */
    apri: function (prodotto, dopoSalvataggio) {
        this._dopo = dopoSalvataggio || null;
        const el = this.el();
        const form = el.querySelector('form');
        const nuovo = !(prodotto && prodotto.id);
        prodRiempi(form, Object.assign({ unita: 'g', tipo_scadenza: 'tmc', attivo: true,
                                         prodotto_da: el.dataset.produttore }, prodotto || {}));
        form.dataset.siglaManuale = nuovo ? '' : '1';
        el.querySelector('.modal-title').textContent = nuovo ? 'Nuovo prodotto' : 'Modifica prodotto';
        bootstrap.Modal.getOrCreateInstance(el).show();
        setTimeout(function () { form.querySelector('[name="nome"]').focus(); }, 300);
    },
    proponiSigla: async function () {
        const form = this.el().querySelector('form');
        if (form.dataset.siglaManuale) return;
        const nome = form.querySelector('[name="nome"]').value;
        const r = await fetch(form.dataset.urlSigla + '?nome=' + encodeURIComponent(nome), { credentials: 'same-origin' });
        form.querySelector('[name="sigla"]').value = (await r.json()).sigla;
    },
    salva: async function (bottone) {
        const form = this.el().querySelector('form');
        try {
            const r = await prodInCorso(bottone, prodPost(form.action, prodLeggi(form)));
            bootstrap.Modal.getInstance(this.el()).hide();
            prodAvviso('Prodotto salvato: ' + r.prodotto.nome_completo);
            if (this._dopo) this._dopo(r.prodotto); else location.href = r.url;
        } catch (e) { prodAvviso(e.message, 'danger'); }
    },
};
