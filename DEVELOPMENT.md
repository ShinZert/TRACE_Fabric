# Development & Deployment Guide

## Local Development

### Prerequisites

- Python 3.10+ ([python.org](https://www.python.org/downloads/))
- Git
- An OpenAI API key ([platform.openai.com](https://platform.openai.com/api-keys))

### Setup

```bash
# Clone the repo
git clone <your-repo-url>
cd bpmn-chatbot

# Create a virtual environment
python -m venv .venv

# Activate it
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env
# Then edit .env and fill in your keys
```

### Environment variables

Create a `.env` file in the project root:

```
OPENAI_API_KEY=sk-proj-your-key-here
SECRET_KEY=generate-a-random-secret-here
```

Generate a secret key:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Run the dev server

```bash
python app.py
```

Open http://localhost:5000 in your browser. The Flask dev server runs with `debug=True`, so it auto-reloads on file changes.

### Project structure at a glance

```
app.py                  # Flask routes (chat, upload, export, sync, reset)
config.py               # Settings (model, token limits, upload size)
prompts/
  system_prompt.py      # LLM system prompt + edit context template
  few_shot_examples.py  # 3 few-shot examples included in every request
services/
  llm_service.py        # OpenAI API calls + JSON extraction
  schema_validator.py   # Schema + semantic validation
  bpmn_converter.py     # JSON <-> BPMN XML conversion
  layout_engine.py      # Auto-layout (topological sort, waypoint routing)
static/
  js/app.js             # Frontend logic (chat, bpmn-js modeler, sync)
  css/style.css         # Styles
templates/
  index.html            # Single-page app template
nginx/
  nginx.conf            # Nginx reverse proxy config (used in production)
Dockerfile              # Container image definition
docker-compose.yml      # Production orchestration (app + nginx)
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
# Clone the repo
cd /opt
git clone <your-repo-url> processpilot
cd processpilot

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
0 3 * * * certbot renew --pre-hook "cd /opt/processpilot && docker compose stop nginx" --post-hook "cd /opt/processpilot && docker compose up -d nginx"
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
cd /opt/processpilot
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
APP_DIR="/opt/processpilot"

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
3. SSH into the droplet and add them to `/opt/processpilot/.env`
4. Restart: `docker compose restart app`
