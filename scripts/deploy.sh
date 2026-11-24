#!/usr/bin/env bash
# Aggiornamento del gestionale sul server di produzione (dalla 3.4.0). Vedi README, sezione "Moduli".
#
#   scripts/deploy.sh sito            aggiorna solo il sito (e i moduli, es. Prodotti): riavvio di pochi
#                                     secondi; bot, lavori programmati e impianto NON si fermano
#   scripts/deploy.sh tutto           aggiorna anche servizi (scheduler + bot) e impianto
#   scripts/deploy.sh indietro sito   torna all'immagine del sito precedente all'ultimo deploy
#   scripts/deploy.sh indietro tutto  idem anche per servizi e impianto
#
# Cosa fa (sito e tutto):
#   1. git pull
#   2. controlla se dall'ultimo deploy "tutto" sono cambiati file usati da servizi/impianto: in quel
#      caso un deploy "sito" non basterebbe e lo propone
#   3. copia di sicurezza coerente di tutti i database in backups/pre-deploy_<data>/
#   4. tiene l'immagine attuale come :web-precedente (e :servizi-precedente) per tornare indietro
#   5. costruisce la nuova immagine e riavvia i container
#   6. controlla /salute per 60 secondi
#   7. segna il commit con il tag git deploy-sito / deploy-tutto (locale, serve al punto 2)
set -euo pipefail
cd "$(dirname "$0")/.."

IMG=cabianca-gestionale
PORTA=$(grep -E '^APP_PORT=' .env 2>/dev/null | cut -d= -f2 || true)
PORTA=${PORTA:-8080}

# File che usano servizi o impianto: se cambiano, serve il deploy "tutto".
# (app/services contiene i lavori dello scheduler e il bot; models/config sono di tutti.)
FILE_SERVIZI=(app/__init__.py app/servizi.py app/ruoli.py app/models.py app/config.py app/utils
              app/services app/version.py requirements.txt Dockerfile docker-compose.yml gunicorn.conf.py)

esiste_immagine() { docker image inspect "$1" >/dev/null 2>&1; }

salute() {
  echo "→ Controllo /salute (max 60 s)…"
  for _ in $(seq 1 30); do
    if risposta=$(curl -fsS "http://127.0.0.1:${PORTA}/salute" 2>/dev/null); then
      echo "  OK: $risposta"; return 0
    fi
    sleep 2
  done
  echo "  ✗ Il sito non risponde bene. Registro:  docker compose logs web --tail=80"
  echo "    Per tornare indietro:                 scripts/deploy.sh indietro $1"
  return 1
}

copia_database() {
  local dest="backups/pre-deploy_$(date +%Y%m%d_%H%M%S)"
  echo "→ Copia di sicurezza dei database in $dest"
  # Copia coerente con l'API di sqlite3 (i DB sono in WAL: un cp non basta), fatta dentro un
  # container così sul server non servono python o sqlite3. Il codice è scritto qui e non importa
  # il gestionale: deve funzionare anche con l'immagine vecchia (:latest, prima della 3.4.0).
  local cmd="import os, sqlite3
d = '/app/$dest'; os.makedirs(d, exist_ok=True)
for f in sorted(os.listdir('/app/data')):
    if not f.endswith('.db') or f.startswith(('_', '.')): continue
    s = sqlite3.connect('file:/app/data/%s?mode=ro' % f, uri=True, timeout=30); t = sqlite3.connect(os.path.join(d, f))
    s.backup(t); print('  ', f, t.execute('PRAGMA integrity_check').fetchone()[0]); t.close(); s.close()"
  local img=""
  for i in "$IMG:web" "$IMG:latest"; do esiste_immagine "$i" && { img=$i; break; }; done
  if [ -n "$img" ]; then
    docker run --rm -v "$PWD/data:/app/data" -v "$PWD/backups:/app/backups" "$img" python -c "$cmd"
  else
    echo "  (prima installazione: nessuna immagine, nessun database da copiare)"
  fi
}

controlla_file_servizi() {
  if ! git rev-parse -q --verify deploy-tutto >/dev/null; then
    echo "  (nessun deploy 'tutto' registrato: al primo giro usare 'tutto')"; return 1
  fi
  local cambiati
  cambiati=$(git diff --name-only deploy-tutto HEAD -- "${FILE_SERVIZI[@]}" || true)
  if [ -n "$cambiati" ]; then
    echo "  Dall'ultimo deploy 'tutto' sono cambiati file usati anche da servizi/impianto:"
    echo "$cambiati" | sed 's/^/    /'
    return 1
  fi
  return 0
}

deploy() {
  local modo=$1
  echo "→ git pull"; git pull --ff-only

  if [ "$modo" = sito ] && ! controlla_file_servizi; then
    read -r -p "  Fare il deploy 'tutto' invece di 'sito'? [S/n] " r
    [[ "$r" =~ ^[nN] ]] || modo=tutto
  fi
  echo "→ Deploy: $modo"

  copia_database

  esiste_immagine "$IMG:web" && docker image tag "$IMG:web" "$IMG:web-precedente"
  echo "→ Costruzione immagine (il sito resta acceso durante la compilazione)"
  docker compose build --no-cache web

  if [ "$modo" = sito ]; then
    docker compose up -d --no-deps web
  else
    esiste_immagine "$IMG:servizi" && docker image tag "$IMG:servizi" "$IMG:servizi-precedente"
    docker image tag "$IMG:web" "$IMG:servizi"
    docker compose up -d        # ricrea web, servizi e impianto (il sito aggiorna lo schema, gli altri aspettano)
  fi

  salute "$modo"
  git tag -f "deploy-$modo" >/dev/null
  [ "$modo" = tutto ] && git tag -f deploy-sito >/dev/null

  # pulizia: la cache di build e le immagini senza nome non servono (le :*-precedente restano)
  docker builder prune -af >/dev/null; docker image prune -f >/dev/null
  echo "✓ Fatto."; docker compose ps
}

indietro() {
  local modo=$1
  esiste_immagine "$IMG:web-precedente" || { echo "Nessuna immagine :web-precedente"; exit 1; }
  docker image tag "$IMG:web-precedente" "$IMG:web"
  if [ "$modo" = tutto ]; then
    esiste_immagine "$IMG:servizi-precedente" && docker image tag "$IMG:servizi-precedente" "$IMG:servizi"
    docker compose up -d --no-build
  else
    docker compose up -d --no-deps --no-build web
  fi
  echo "Tornato all'immagine precedente. Se un modulo segnala 'database più nuovo del codice',"
  echo "ripristinare la copia backups/<modulo>_pre_v*.db (README, sezione Moduli → Tornare indietro)."
  salute "$modo"
}

case "${1:-}" in
  sito|tutto) deploy "$1" ;;
  indietro)   [[ "${2:-}" =~ ^(sito|tutto)$ ]] || { echo "uso: $0 indietro sito|tutto"; exit 2; }; indietro "$2" ;;
  *) sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
