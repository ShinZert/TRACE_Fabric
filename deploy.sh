#!/bin/bash
set -e

# =============================================================================
# ProcessPilot Deploy Script
# =============================================================================
# Usage:
#   ./deploy.sh setup         First-time server setup (installs Docker, clones repo)
#   ./deploy.sh deploy        Deploy latest changes (git pull + rebuild)
#   ./deploy.sh logs          Tail live logs
#   ./deploy.sh status        Show container status
#   ./deploy.sh restart       Restart app (e.g. after .env change)
#   ./deploy.sh stop          Stop all containers
#   ./deploy.sh set-token     Store GitHub token on server for git pull
#   ./deploy.sh ssh           Open an interactive SSH session
# =============================================================================

# --- Load .env ---------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/.env" ]; then
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi
# -----------------------------------------------------------------------------

# --- Configuration -----------------------------------------------------------
# Edit these to match your droplet
DROPLET_IP="159.223.152.23"
DROPLET_USER="root"
APP_DIR="/opt/bpmn-chatbot"
REPO_URL="https://github.com/ShinZert/TRACE_Fabric.git"
# Use Windows OpenSSH so it connects to the Windows ssh-agent
SSH_CMD="/c/Windows/System32/OpenSSH/ssh.exe"
# -----------------------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_config() {
    if [ -z "$DROPLET_IP" ]; then
        echo -e "${RED}Error: DROPLET_IP is not set.${NC}"
        echo "Edit deploy.sh and fill in your droplet's IP address."
        exit 1
    fi
}

check_repo_url() {
    if [ -z "$REPO_URL" ]; then
        echo -e "${RED}Error: REPO_URL is not set.${NC}"
        echo "Edit deploy.sh and fill in your git repository URL."
        exit 1
    fi
}

remote() {
    "$SSH_CMD" -o ConnectTimeout=10 "$DROPLET_USER@$DROPLET_IP" "$@"
}

# --- Commands ----------------------------------------------------------------

cmd_setup() {
    check_config
    check_repo_url

    echo -e "${YELLOW}=== Setting up server at $DROPLET_IP ===${NC}"

    echo -e "\n${GREEN}[1/4] Updating system packages...${NC}"
    remote "apt update && apt upgrade -y"

    echo -e "\n${GREEN}[2/4] Installing Docker...${NC}"
    remote "if ! command -v docker &> /dev/null; then
        curl -fsSL https://get.docker.com | sh
        apt install -y docker-compose-plugin
    else
        echo 'Docker already installed'
    fi"

    echo -e "\n${GREEN}[3/4] Configuring firewall...${NC}"
    remote "ufw allow OpenSSH && ufw allow 80/tcp && ufw allow 443/tcp && yes | ufw enable || true"

    echo -e "\n${GREEN}[4/4] Cloning repository...${NC}"
    remote "if [ -d $APP_DIR ]; then
        echo 'App directory already exists, pulling latest...'
        cd $APP_DIR && git pull
    else
        git clone $REPO_URL $APP_DIR
    fi"

    echo -e "\n${YELLOW}=== Server setup complete ===${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. SSH in and create the .env file:"
    echo "     ssh $DROPLET_USER@$DROPLET_IP"
    echo "     nano $APP_DIR/.env"
    echo ""
    echo "     Add these lines:"
    echo "       OPENAI_API_KEY=sk-proj-your-key-here"
    echo "       SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
    echo ""
    echo "  2. Then start the app:"
    echo "     ./deploy.sh deploy"
}

cmd_deploy() {
    check_config

    echo -e "${YELLOW}=== Deploying to $DROPLET_IP ===${NC}"

    echo -e "\n${GREEN}[1/3] Pulling latest code...${NC}"
    remote "cd $APP_DIR && git pull"

    echo -e "\n${GREEN}[2/3] Building and starting containers...${NC}"
    remote "cd $APP_DIR && docker compose up -d --build"

    echo -e "\n${GREEN}[3/3] Verifying...${NC}"
    remote "cd $APP_DIR && docker compose ps"

    echo -e "\n${GREEN}=== Deploy complete ===${NC}"
}

cmd_logs() {
    check_config
    echo -e "${YELLOW}=== Tailing logs (Ctrl+C to stop) ===${NC}"
    # Use -t to force pseudo-terminal so Ctrl+C works
    "$SSH_CMD" -t "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && docker compose logs -f --tail=50"
}

cmd_status() {
    check_config
    echo -e "${YELLOW}=== Container status ===${NC}"
    remote "cd $APP_DIR && docker compose ps"
    echo ""
    echo -e "${YELLOW}=== Resource usage ===${NC}"
    remote "echo 'Disk:' && df -h / | tail -1 && echo '' && echo 'Memory:' && free -h | head -2"
}

cmd_restart() {
    check_config
    echo -e "${YELLOW}=== Restarting app ===${NC}"
    remote "cd $APP_DIR && docker compose restart app"
    echo -e "${GREEN}Done.${NC}"
}

cmd_stop() {
    check_config
    echo -e "${YELLOW}=== Stopping all containers ===${NC}"
    remote "cd $APP_DIR && docker compose down"
    echo -e "${GREEN}Done.${NC}"
}

cmd_set_token() {
    check_config

    if [ -z "$GITHUB_USER" ] || [ -z "$GITHUB_TOKEN" ]; then
        echo -e "${RED}Error: GITHUB_USER and GITHUB_TOKEN must be set in .env${NC}"
        echo ""
        echo "Add these lines to your .env file:"
        echo "  GITHUB_USER=your-github-username"
        echo "  GITHUB_TOKEN=ghp_your-personal-access-token"
        exit 1
    fi

    echo -e "${YELLOW}=== Configure GitHub token on server ===${NC}"

    # Extract owner/repo from REPO_URL (handles both https://github.com/owner/repo.git and .../repo)
    REPO_PATH=$(echo "$REPO_URL" | sed 's|https://github.com/||' | sed 's|\.git$||')

    remote "cd $APP_DIR && git remote set-url origin https://${GITHUB_USER}:${GITHUB_TOKEN}@github.com/${REPO_PATH}.git"
    echo -e "${GREEN}Token configured for ${GITHUB_USER}. git pull will now work without prompting.${NC}"
}

cmd_ssh() {
    check_config
    echo -e "${YELLOW}=== Connecting to $DROPLET_IP ===${NC}"
    "$SSH_CMD" "$DROPLET_USER@$DROPLET_IP"
}

cmd_help() {
    echo "ProcessPilot Deploy Script"
    echo ""
    echo "Usage: ./deploy.sh <command>"
    echo ""
    echo "Commands:"
    echo "  setup      First-time server setup (installs Docker, clones repo)"
    echo "  deploy     Deploy latest changes (git pull + rebuild)"
    echo "  logs       Tail live logs from all containers"
    echo "  status     Show container status and resource usage"
    echo "  restart    Restart the app container (e.g. after .env change)"
    echo "  stop       Stop all containers"
    echo "  set-token  Store your GitHub token on the server (run once)"
    echo "  ssh        Open an interactive SSH session to the droplet"
    echo ""
    echo "First time? Edit the DROPLET_IP and REPO_URL at the top of this script, then run:"
    echo "  ./deploy.sh set-token"
    echo "  ./deploy.sh deploy"
}

# --- Main --------------------------------------------------------------------

case "${1:-}" in
    setup)   cmd_setup ;;
    deploy)  cmd_deploy ;;
    logs)    cmd_logs ;;
    status)  cmd_status ;;
    restart) cmd_restart ;;
    stop)    cmd_stop ;;
    set-token) cmd_set_token ;;
    ssh)     cmd_ssh ;;
    *)       cmd_help ;;
esac
