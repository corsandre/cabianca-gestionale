#!/bin/bash
# ============================================
# Fattoria Ca Bianca - Gestionale
# Script di installazione
# ============================================

set -e

GREEN='\033[0;32m'
GOLD='\033[0;33m'
NC='\033[0m'

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Fattoria Ca Bianca - Gestionale        ║${NC}"
echo -e "${GREEN}║   Installazione                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo -e "${GOLD}Docker non trovato. Installazione in corso...${NC}"
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo -e "${GREEN}Docker installato.${NC}"
    echo "NOTA: Potrebbe essere necessario fare logout e login per i permessi Docker."
fi

# Check docker compose
if ! docker compose version &> /dev/null; then
    echo -e "${GOLD}Docker Compose non trovato. Installazione...${NC}"
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

echo -e "${GREEN}Configurazione dell'applicazione${NC}"
echo "Inserisci i dati richiesti (premi Invio per il valore predefinito)."
echo ""

# Admin credentials
read -p "Username amministratore [admin]: " ADMIN_USER
ADMIN_USER=${ADMIN_USER:-admin}

while true; do
    read -s -p "Password amministratore: " ADMIN_PASS
    echo ""
    if [ -z "$ADMIN_PASS" ]; then
        echo "La password non puo essere vuota."
    elif [ ${#ADMIN_PASS} -lt 6 ]; then
        echo "La password deve avere almeno 6 caratteri."
    else
        break
    fi
done

read -p "Nome visualizzato admin [Amministratore]: " ADMIN_NAME
ADMIN_NAME=${ADMIN_NAME:-Amministratore}

echo ""
echo -e "${GREEN}Telegram (opzionale - premi Invio per saltare)${NC}"
read -p "Telegram Bot Token: " TG_TOKEN
read -p "Telegram Chat ID: " TG_CHAT

echo ""
echo -e "${GREEN}4CloudOffice - Registratore di cassa (opzionale)${NC}"
read -p "URL [https://www.4cloudoffice.com/v2/]: " CO_URL
CO_URL=${CO_URL:-https://www.4cloudoffice.com/v2/}
read -p "Username: " CO_USER
read -s -p "Password: " CO_PASS
echo ""

echo ""
echo -e "${GREEN}Email IMAP - Recupero fatture SDI (opzionale)${NC}"
read -p "IMAP Host (es. imap.hostinger.com): " IMAP_HOST
read -p "IMAP Porta [993]: " IMAP_PORT
IMAP_PORT=${IMAP_PORT:-993}
read -p "IMAP Username (email): " IMAP_USER
read -s -p "IMAP Password: " IMAP_PASS
echo ""
read -p "Cartella IMAP [INBOX]: " IMAP_FOLDER
IMAP_FOLDER=${IMAP_FOLDER:-INBOX}
read -p "Filtra per mittente (opzionale): " IMAP_FROM

echo ""
echo -e "${GREEN}Google Drive Backup (opzionale)${NC}"
read -p "Google Drive Folder ID: " GD_FOLDER
read -p "Percorso file credenziali JSON (o premi Invio): " GD_CREDS

echo ""
read -p "Porta applicazione [8080]: " APP_PORT
APP_PORT=${APP_PORT:-8080}

# Generate secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32)

# Create .env file
cat > .env << ENVEOF
# Generato automaticamente da setup.sh - $(date)
SECRET_KEY=${SECRET_KEY}
DATABASE_URL=sqlite:///data/gestionale.db
ADMIN_USERNAME=${ADMIN_USER}
ADMIN_PASSWORD=${ADMIN_PASS}
ADMIN_DISPLAY_NAME=${ADMIN_NAME}
TELEGRAM_BOT_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}
CLOUD_OFFICE_URL=${CO_URL}
CLOUD_OFFICE_USER=${CO_USER}
CLOUD_OFFICE_PASSWORD=${CO_PASS}
GOOGLE_DRIVE_FOLDER_ID=${GD_FOLDER}
GOOGLE_DRIVE_CREDENTIALS_JSON=${GD_CREDS}
IMAP_HOST=${IMAP_HOST}
IMAP_PORT=${IMAP_PORT}
IMAP_USER=${IMAP_USER}
IMAP_PASSWORD=${IMAP_PASS}
IMAP_FOLDER=${IMAP_FOLDER}
IMAP_SEARCH_FROM=${IMAP_FROM}
APP_PORT=${APP_PORT}
APP_HOST=0.0.0.0
APP_DEBUG=false
ENVEOF

echo ""
echo -e "${GREEN}File .env creato.${NC}"

# Create data directories
mkdir -p data backups app/static/uploads

# Build and start
echo ""
echo -e "${GREEN}Avvio dell'applicazione con Docker...${NC}"
docker compose up -d --build

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installazione completata!              ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Get IP address
IP=$(hostname -I | awk '{print $1}')
echo -e "Accedi al gestionale da:"
echo -e "  Locale:  ${GOLD}http://localhost:${APP_PORT}${NC}"
echo -e "  Rete:    ${GOLD}http://${IP}:${APP_PORT}${NC}"
echo ""
echo -e "Credenziali: ${GOLD}${ADMIN_USER}${NC} / (la password inserita)"
echo ""
echo "Comandi utili:"
echo "  docker compose logs -f     # Visualizza i log"
echo "  docker compose restart     # Riavvia"
echo "  docker compose down        # Ferma"
echo "  docker compose up -d       # Avvia"
echo ""
