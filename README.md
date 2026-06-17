# Weaver

A conversational AI application that turns natural-language descriptions and flowchart images into **Fabric decision-trace** diagrams — a design language for AI-system workflows that captures humans, AI models, governance steps, and accept/modify/reject decisions. Users describe processes in chat, upload sketches, and refine the trace through conversation or direct manipulation in a visual editor.

![Python](https://img.shields.io/badge/Python-3.12+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5--mini-green)
![React](https://img.shields.io/badge/React-18-61dafb)
![React%20Flow](https://img.shields.io/badge/React%20Flow-12-orange)

## Features

- **Text-to-trace** — describe an AI workflow in plain language and get a structured Fabric decision trace
- **Image-to-trace** — drop a hand-drawn flowchart or screenshot onto the chat panel and have it converted (image bytes are sniffed server-side via Pillow before being forwarded to the model)
- **Summary-and-confirm flow** — new diagrams go through a summary step so you can review, inline-edit, or revise the AI's interpretation before generation
- **Conversational editing** — refine the trace iteratively (*"add a governance review before the final outcome"*, *"replace the manual review with a fixed AI model"*)
- **Visual editor** — drag, rewire, undo/redo, and inspect elements directly on a React Flow canvas; manual positions are preserved across edits within a session
- **JSON export** — download the trace as a `.json` file from the editor toolbar

## Architecture

```
User input ─→ Flask /api/chat ─→ _build_messages() ─→ OpenAI API
                                  (system prompt +    │
                                   3 few-shot examples │
                                   + last 6 turns +   │
                                   edit context)      │
                                                      ▼
React Flow ◄── traceToFlow() ◄── schema + ◄── _extract_json()
canvas         + dagre layout    semantic
                                 validation
```

The wire format between frontend and backend is the Fabric trace JSON.

### Key modules

| Module | Responsibility |
|---|---|
| `app.py` | Flask routes (`/api/chat`, `/api/upload`, `/api/export`, `/api/sync`, `/api/reset`, `/api/health`); per-IP rate limiting via Flask-Limiter |
| `config.py` | Centralised settings — model, conversation window, upload size, token budgets, OpenAI timeout (all overridable via env vars) |
| `prompts/system_prompt.py` | LLM system prompt, summary prompt, and edit-context template |
| `prompts/few_shot_examples.py` | 3 few-shot examples included in every trace request (loaded from `prompts/few_shot_examples.json`) |
| `services/llm_service.py` | OpenAI integration with JSON extraction (raw, code-fenced, brace-matching fallback) |
| `services/schema_validator.py` | Two-pass validation — jsonschema + semantic checks (orphans, flow refs, duplicates, terminal nodes) |
| `services/image_validator.py` | Pillow-based image sniffing — only PNG/JPEG/GIF/WEBP reach the model |
| `services/event_logger.py` + `services/telemetry.py` | Append-only JSONL event log + shared metric primitives — one line per request (see `MONITORING.md`) |
| `scripts/run_evals.py` | Offline eval harness — runs the 20 gold fixtures in `prompts/workflows.json` and writes metrics to `evals/results/` |
| `frontend/src/App.jsx` | Top-level React component wiring chat → editor → `/api/sync` |
| `frontend/src/components/Editor.jsx` | React Flow canvas with palette, undo/redo, keyboard shortcuts |
| `frontend/src/lib/layout.js` | `traceToFlow` / `flowToTrace` + dagre auto-layout |

### Supported element types

- **Fabric types:** `humanSource`, `inputOutput`, `fixedAIModel`, `trainingAIModel`, `governanceMechanism`, `ui`, `decisionPoint`, `accept`, `modify`, `reject`, `restart`, `finalOutcome`

The entry of a trace is the single element with no incoming flow (typically a `humanSource`, `ui`, or `inputOutput`); terminals are `finalOutcome` nodes — there's no separate start/end event type.

## Run locally

**Prerequisites:** Python 3.12+, Node.js 20+, an OpenAI API key.

```bash
# 1. Clone + install
git clone https://github.com/ShinZert/TRACE_Fabric.git
cd TRACE_Fabric
pip install -r requirements.txt
(cd frontend && npm install)

# 2. Configure .env
cp .env.example .env
#   set OPENAI_API_KEY=sk-proj-...
#   set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")

# 3a. Dev mode (HMR) — open http://localhost:5173
python app.py                          # terminal 1 (Flask API on :5000)
cd frontend && npm run dev             # terminal 2 (Vite proxies /api/* to Flask)

# 3b. One-process mode — open http://localhost:5000
(cd frontend && npm run build)
python app.py
```

The app **refuses to start without `SECRET_KEY`**. For quick hacking, set `FLASK_DEBUG=1` to skip that check and enable Flask's debugger.

## Tests & evaluation

```bash
# Backend (pytest) — live OpenAI tests are skipped unless opted in
pip install -r requirements-dev.txt
pytest                              # default — skips live OpenAI calls
RUN_LIVE_OPENAI=1 pytest -m live    # opt in to live OpenAI smoke tests

# Frontend (vitest)
cd frontend && npm test

# Offline eval harness — runs the 20 gold fixtures through the model,
# writes per-run + aggregated metrics to evals/results/<UTC-timestamp>/
python scripts/run_evals.py
```

Every live request also emits one telemetry event (tokens, latency, structural metrics) to `${LOG_DIR}/weaver.jsonl`. See `MONITORING.md` for the event schema and `DEVELOPMENT.md` for droplet setup and HTTPS.

## Deploy to a Digital Ocean droplet

The droplet runs the prebuilt GHCR image via `docker compose` (Flask on :8000 behind nginx on :80). `deploy.sh` wraps all SSH steps.

**Prerequisites:** an Ubuntu droplet with SSH key access as `root`, plus a GitHub PAT with `read:packages`.

```bash
# 1. Configure local .env (already needed for the app)
#   DROPLET_IP=1.2.3.4
#   GITHUB_USER=your-gh-username
#   GITHUB_TOKEN=ghp_...

# 2. One-time server bootstrap (installs Docker, clones repo, opens firewall)
./deploy.sh setup
./deploy.sh set-token        # writes the PAT into the droplet's git remote
./deploy.sh login            # docker login ghcr.io on the droplet

# 3. Create the remote .env on the droplet
./deploy.sh ssh
#   on the droplet:
#     nano /opt/trace-fabric/.env
#     # add OPENAI_API_KEY and SECRET_KEY (see local .env above)
#     exit

# 4. Deploy (pulls latest image from GHCR and restarts)
./deploy.sh deploy           # or: ./deploy.sh deploy v1.2.0
```

The app is then live at `http://<DROPLET_IP>/`. For HTTPS via Certbot see `DEVELOPMENT.md`.

Other useful commands: `./deploy.sh logs` (tail), `./deploy.sh status`, `./deploy.sh restart` (after `.env` change), `./deploy.sh stop`.

## Usage

1. **Describe a workflow** — e.g. *"Loan-approval workflow: applicant submits, an AI model scores the application, a human reviewer accepts or rejects."*
2. **Review the summary** — Weaver summarises its understanding; confirm, inline-edit, or send corrections.
3. **Refine** — *"Add a governance check before the AI scoring step."*
4. **Edit visually** — drag, rewire, and inspect on the canvas. Click **Sync edits** to persist before chatting again.
5. **Export** — click **Export JSON** for a downloadable `.json` of the current trace.

You can also drop an image of a flowchart onto the chat panel; image bytes are validated server-side before being forwarded to the model.

## Tech stack

- **Backend:** Flask 3, gunicorn, Flask-Limiter, OpenAI Python SDK, jsonschema, Pillow
- **Frontend:** React 18, Vite, React Flow 12, dagre
- **State:** Flask sessions (ephemeral, no database)
- **Deployment:** Docker (multi-stage) + nginx, with `/api/health` for liveness probes

## License

This project is for educational and research purposes.
