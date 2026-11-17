// Foto delle bolle e invio dei moduli con nuovi tentativi: usato da Consegne, Spostamenti e Modello 4.
// Prima della 3.1.4 era copiato in ognuna delle tre pagine.

// Riduce una foto prima di inviarla (lato più lungo maxDim, JPEG di qualità qualita).
// PDF o altri file, o una foto che compressa non diventa più piccola: si tiene l'originale.
function cbComprimiImmagine(file, maxDim, qualita) {
    return new Promise(function (resolve) {
        if (!file.type.startsWith('image/')) {
            resolve(file);
            return;
        }
        const img = new Image();
        const url = URL.createObjectURL(file);
        img.onload = function () {
            URL.revokeObjectURL(url);
            let w = img.width, h = img.height;
            if (w > maxDim || h > maxDim) {
                if (w > h) { h = Math.round(h * maxDim / w); w = maxDim; }
                else { w = Math.round(w * maxDim / h); h = maxDim; }
            }
            const canvas = document.createElement('canvas');
            canvas.width = w;
            canvas.height = h;
            canvas.getContext('2d').drawImage(img, 0, 0, w, h);
            canvas.toBlob(function (blob) {
                if (!blob || blob.size >= file.size) {
                    resolve(file);
                    return;
                }
                resolve(new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' }));
            }, 'image/jpeg', qualita);
        };
        img.onerror = function () {
            URL.revokeObjectURL(url);
            resolve(file);
        };
        img.src = url;
    });
}

// Ogni campo foto della bolla (.cb-bolla-input) comprime la foto appena scelta.
document.querySelectorAll('.cb-bolla-input').forEach(function (input) {
    input.addEventListener('change', async function () {
        if (!input.files || !input.files[0]) return;
        const originale = input.files[0];
        const compressa = await cbComprimiImmagine(originale, 1600, 0.75);
        if (compressa !== originale) {
            const dt = new DataTransfer();
            dt.items.add(compressa);
            input.files = dt.files;
        }
    });
});

// Token del modulo scaduto (pagina aperta da molto o sessione cambiata): se ne chiede uno nuovo,
// lo si mette in tutti i moduli della pagina e si riprova subito, senza perdere i dati inseriti.
async function cbNuovoTokenCsrf() {
    const resp = await fetch('/csrf-token', { credentials: 'same-origin' });
    const json = await resp.json();
    document.querySelectorAll('input[name="csrf_token"]').forEach(function (i) { i.value = json.csrf_token; });
    return json.csrf_token;
}

// POST con fino a tentativiMax tentativi (1,5 s tra uno e l'altro); il rinnovo del token non conta.
async function cbFetchConRetry(url, body, tentativiMax, onTentativo) {
    let tokenRinnovato = false;
    for (let tentativo = 1; tentativo <= tentativiMax; tentativo++) {
        if (onTentativo) onTentativo(tentativo, tentativiMax);
        try {
            const resp = await fetch(url, {
                method: 'POST',
                body: body,
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'fetch' },
            });
            let json = null;
            try { json = await resp.json(); } catch (e) {}
            if (resp.ok && json) return json;
            if (json && json.csrf_scaduto && !tokenRinnovato) {
                tokenRinnovato = true;
                body.set('csrf_token', await cbNuovoTokenCsrf());
                tentativo--;                // non conta come tentativo
                continue;
            }
            if (json && json.csrf_scaduto) throw new Error(json.error);
            throw new Error((json && json.error) || 'risposta non valida dal server');
        } catch (err) {
            if (tentativo === tentativiMax) throw err;
            await new Promise(function (r) { setTimeout(r, 1500); });
        }
    }
}
