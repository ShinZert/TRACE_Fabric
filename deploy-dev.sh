#!/bin/bash
set -e

# =============================================================================
# Fabric Deploy Script — DEV environment
# =============================================================================
# Mirrors deploy.sh but targets the dev droplet and defaults the deploy
# tag to the dev branch. Keep this script the only one that touches dev.
#
# Usage (same as deploy.sh, just s/deploy.sh/deploy-dev.sh/):
#   ./deploy-dev.sh setup
#   ./deploy-dev.sh set-token
#   ./deploy-dev.sh login
#   ./deploy-dev.sh deploy            # defaults to dev branch image
#   ./deploy-dev.sh deploy <TAG>      # deploy a specific tag/sha
#   ./deploy-dev.sh logs | status | restart | stop | ssh
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
# Fill in DROPLET_IP after creating the dev droplet on Digital Ocean.
DROPLET_IP=""                                       # <-- TODO: set to dev droplet IP
DROPLET_USER="root"
APP_DIR="/opt/trace_fabric_dev"
REPO_URL="https://github.com/ShinZert/TRACE_Fabric.git"
# Default tag for `./deploy-dev.sh deploy` with no argument. Matches the
# branch name the GHA workflow uses for `type=ref,event=branch`.
DEFAULT_TAG="dev-create-fabric-ontology"
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

    local tag="${1:-$DEFAULT_TAG}"

    echo -e "${YELLOW}=== Deploying tag '$tag' to $DROPLET_IP ===${NC}"

    echo -e "\n${GREEN}[1/4] Updating compose/nginx config from git...${NC}"
    remote "cd $APP_DIR && git pull"

    echo -e "\n${GREEN}[2/4] Pinning TAG=$tag in .env...${NC}"
    # Replace the existing TAG= line if present, else append. Atomic via temp file.
    remote "cd $APP_DIR && (grep -v '^TAG=' .env 2>/dev/null; echo 'TAG=$tag') > .env.new && mv .env.new .env"

    echo -e "\n${GREEN}[3/4] Pulling image from GHCR and restarting...${NC}"
    remote "cd $APP_DIR && docker compose pull && docker compose up -d"

    echo -e "\n${GREEN}[4/4] Verifying...${NC}"
    remote "cd $APP_DIR && docker compose ps"

    echo -e "\n${GREEN}=== Deploy complete (tag: $tag) ===${NC}"
}

cmd_login() {
    check_config

    if [ -z "$GITHUB_USER" ] || [ -z "$GITHUB_TOKEN" ]; then
        echo -e "${RED}Error: GITHUB_USER and GITHUB_TOKEN must be set in .env${NC}"
        echo ""
        echo "The token needs the 'read:packages' scope to pull from GHCR."
        echo "Add to your .env:"
        echo "  GITHUB_USER=your-github-username"
        echo "  GITHUB_TOKEN=ghp_your-personal-access-token"
        exit 1
    fi

    echo -e "${YELLOW}=== Logging server into ghcr.io as $GITHUB_USER ===${NC}"
    remote "echo '$GITHUB_TOKEN' | docker login ghcr.io -u $GITHUB_USER --password-stdin"
    echo -e "${GREEN}Done. The droplet can now pull private images from ghcr.io.${NC}"
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
    echo "Fabric Deploy Script"
    echo ""
    echo "Usage: ./deploy.sh <command> [args]"
    echo ""
    echo "Commands:"
    echo "  setup           First-time server setup (installs Docker, clones repo)"
    echo "  login           Log the server into GHCR (run once, after set-token)"
    echo "  deploy [TAG]    Pull image tag (default: latest) from GHCR and restart"
    echo "                    e.g. ./deploy.sh deploy v1.2.0"
    echo "                         ./deploy.sh deploy sha-a1b2c3d"
    echo "  logs            Tail live logs from all containers"
    echo "  status          Show container status and resource usage"
    echo "  restart         Restart the app container (e.g. after .env change)"
    echo "  stop            Stop all containers"
    echo "  set-token       Store your GitHub token on the server (run once)"
    echo "  ssh             Open an interactive SSH session to the droplet"
    echo ""
    echo "First time? Edit DROPLET_IP and REPO_URL at the top of this script, then run:"
    echo "  ./deploy.sh setup"
    echo "  ./deploy.sh set-token"
    echo "  ./deploy.sh login"
    echo "  ./deploy.sh deploy"
}

# --- Main --------------------------------------------------------------------

case "${1:-}" in
    setup)     cmd_setup ;;
    login)     cmd_login ;;
    deploy)    cmd_deploy "${2:-}" ;;
    logs)      cmd_logs ;;
    status)    cmd_status ;;
    restart)   cmd_restart ;;
    stop)      cmd_stop ;;
    set-token) cmd_set_token ;;
    ssh)       cmd_ssh ;;
    *)         cmd_help ;;
esac
