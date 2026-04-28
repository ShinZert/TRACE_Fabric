# Development & Deployment Guide

## Local Development

### Prerequisites

- Python 3.12+ ([python.org](https://www.python.org/downloads/))
- Node.js 20+ ([nodejs.org](https://nodejs.org/)) — required for the frontend
- Git
- An OpenAI API key ([platform.openai.com](https://platform.openai.com/api-keys))

### Setup

```bash
# Clone the repo
git clone https://github.com/ShinZert/TRACE_Fabric.git
cd TRACE_Fabric

# Create a virtual environment
python -m venv .venv

# Activate it
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd frontend && npm install && cd ..

# Create your .env file
cp .env.example .env
# Then edit .env and fill in your keys
```

### Environment variables

Create a `.env` file in the project root. The minimum is:

```
OPENAI_API_KEY=sk-proj-your-key-here
SECRET_KEY=generate-a-random-secret-here
```

The app refuses to start without `SECRET_KEY` (predictable cookie keys let attackers forge sessions). Generate one with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Optional overrides (defaults are sensible):

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_DEBUG` | unset | `1` enables Flask's debugger and uses an ephemeral generated `SECRET_KEY` for local dev |
| `OPENAI_TIMEOUT` | `60` | Hard timeout (seconds) for OpenAI HTTP calls |
| `MAX_TRACE_TOKENS` | `16384` | Token cap for trace generation |
| `MAX_SUMMARY_TOKENS_TEXT` | `4096` | Token cap for text-only summaries |
| `MAX_SUMMARY_TOKENS_IMAGE` | `8192` | Token cap for image summaries |
| `RATELIMIT_STORAGE_URI` | `memory://` | Set to a Redis URL for shared rate-limit counters across workers |

### Run the dev server

The frontend (Vite + React) and backend (Flask) run as two processes in development:

```bash
# Terminal 1 — Flask API on :5000
python app.py

# Terminal 2 — Vite dev server on :5173 (proxies /api/* to Flask, with HMR)
cd frontend && npm run dev
```

Open http://localhost:5173 in your browser. The Flask debugger is opt-in via `FLASK_DEBUG=1`.

For a one-process production-style run, build the bundle once and skip the Vite server:

```bash
cd frontend && npm run build && cd ..
python app.py
# Now open http://localhost:5000 — Flask serves the built bundle from static/dist/
```

### Project structure at a glance

```
app.py                          # Flask routes + rate limiting + ProxyFix
config.py                       # Settings (model, token caps, timeout, secret key)
prompts/
  system_prompt.py              # LLM system prompt + edit-context template
  few_shot_examples.py          # Loader for the JSON few-shot examples
  few_shot_examples.json        # 3 few-shot examples included in every request
services/
  llm_service.py                # OpenAI calls + JSON extraction
  schema_validator.py           # Schema + semantic validation
  image_validator.py            # Pillow-based image sniffing
frontend/                       # React + Vite frontend (compiled to static/dist/)
  src/App.jsx                   # Top-level component
  src/components/Editor.jsx     # React Flow canvas
  src/components/ChatPanel.jsx  # Chat panel + image drop
  src/lib/layout.js             # traceToFlow / flowToTrace + dagre auto-layout
templates/
  index.html                    # Jinja shell that loads the Vite bundle
nginx/
  nginx.conf                    # Nginx reverse proxy config (production)
Dockerfile                      # Multi-stage build (Node → Python)
docker-compose.yml              # Production orchestration (app + nginx)
deploy.sh                       # SSH-based deploy helper
```

---

## Deploying to a Digital Ocean Droplet

### 1. Create the droplet

1. Log in to [cloud.digitalocean.com](https://cloud.digitalocean.com/)
2. **Create Droplet** with these settings:
   - **Image:** Ubuntu 24.04 LTS
   - **Plan:** Basic, $6/mo (1 vCPU, 1 GB RAM) is enough to start
   - **Region:** Choose the one closest to your users
   - **Authentication:** SSH key (recommended) or password
3. Note the droplet's **IP address** once it's created

### 2. Initial server setup

SSH into your droplet:

```bash
ssh root@YOUR_DROPLET_IP
```

Secure the server and install Docker:

```bash
# Update packages
apt update && apt upgrade -y

# Create a non-root user (optional but recommended)
adduser deployer
usermod -aG sudo deployer

# Install Docker
curl -fsSL https://get.docker.com | sh

# Install Docker Compose plugin
apt install -y docker-compose-plugin

# Allow your user to run Docker without sudo
usermod -aG docker deployer

# Enable firewall
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### 3. Deploy the application

From your droplet (SSH in as `deployer` or `root`):

```bash
# Clone the repo. The directory is named `bpmn-chatbot` for compatibility
# with the existing `deploy.sh` (APP_DIR=/opt/bpmn-chatbot) — legacy from
# before the project was renamed to Fabric.
cd /opt
git clone <your-repo-url> bpmn-chatbot
cd bpmn-chatbot

# Create the .env file
nano .env
```

Add your environment variables:

```
OPENAI_API_KEY=sk-proj-your-key-here
SECRET_KEY=generate-a-random-secret-here
```

Build and start:

```bash
docker compose up -d --build
```

Your app is now running at `http://YOUR_DROPLET_IP`.

### 4. Verify it's working

```bash
# Check containers are running
docker compose ps

# Check logs
docker compose logs -f app
docker compose logs -f nginx
```

### 5. Set up a domain (optional)

1. Point your domain's A record to your droplet's IP address
2. Update `nginx/nginx.conf` — replace `server_name _;` with your domain:

   ```nginx
   server_name yourdomain.com;
   ```

3. Rebuild nginx: `docker compose up -d --build nginx`

### 6. Add HTTPS with Let's Encrypt (recommended)

Install Certbot on the host and get a certificate:

```bash
# Install certbot
apt install -y certbot

# Stop nginx temporarily to free port 80
docker compose stop nginx

# Get certificate
certbot certonly --standalone -d yourdomain.com

# Restart nginx
docker compose up -d nginx
```

Update `docker-compose.yml` to mount the certificates:

```yaml
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - /etc/letsencrypt:/etc/letsencrypt:ro
    depends_on:
      - app
    restart: unless-stopped
```

Update `nginx/nginx.conf` to handle HTTPS:

```nginx
events {
    worker_connections 1024;
}

http {
    upstream app {
        server app:8000;
    }

    # Redirect HTTP to HTTPS
    server {
        listen 80;
        server_name yourdomain.com;
        return 301 https://$host$request_uri;
    }

    server {
        listen 443 ssl;
        server_name yourdomain.com;

        ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;

        client_max_body_size 16M;

        location / {
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 120s;
        }
    }
}
```

Rebuild: `docker compose up -d --build`

Set up auto-renewal:

```bash
# Add a cron job to renew certificates
crontab -e
# Add this line:
0 3 * * * certbot renew --pre-hook "cd /opt/bpmn-chatbot && docker compose stop nginx" --post-hook "cd /opt/bpmn-chatbot && docker compose up -d nginx"
```

---

## Ongoing Development Workflow

### Develop locally, deploy to production

The day-to-day workflow:

```bash
# 1. Develop locally
python app.py
# Make changes, test at http://localhost:5000

# 2. Commit your work
git add -A
git commit -m "Description of changes"
git push

# 3. Deploy to production
ssh deployer@YOUR_DROPLET_IP
cd /opt/bpmn-chatbot
git pull
docker compose up -d --build
```

### Quick deploy script

Create `deploy.sh` on your local machine for one-command deploys:

```bash
#!/bin/bash
set -e

DROPLET_IP="YOUR_DROPLET_IP"
DROPLET_USER="deployer"
APP_DIR="/opt/bpmn-chatbot"

echo "Deploying to $DROPLET_IP..."
ssh $DROPLET_USER@$DROPLET_IP "cd $APP_DIR && git pull && docker compose up -d --build"
echo "Done."
```

```bash
chmod +x deploy.sh
./deploy.sh
```

### Useful commands on the droplet

```bash
# View live logs
docker compose logs -f

# Restart the app (e.g. after .env change)
docker compose restart app

# Full rebuild (after Dockerfile or dependency changes)
docker compose up -d --build

# Stop everything
docker compose down

# Check disk/memory usage
df -h
free -m
docker system df

# Clean up old Docker images
docker image prune -f
```

### Updating dependencies

```bash
# Locally: update requirements.txt, then on the droplet:
git pull
docker compose up -d --build
# The Docker build will install the new dependencies
```

### Checking .env differences

The `.env` file is gitignored and lives independently on each environment. If you add new environment variables:

1. Add them to `.env.example` (committed to git) as documentation
2. Add them to your local `.env`
3. SSH into the droplet and add them to `/opt/bpmn-chatbot/.env`
4. Restart: `docker compose restart app`
