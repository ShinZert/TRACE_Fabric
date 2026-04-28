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

All wire-format between frontend and backend is JSON — there is no BPMN XML round-trip.

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
| `frontend/src/App.jsx` | Top-level React component wiring chat → editor → `/api/sync` |
| `frontend/src/components/Editor.jsx` | React Flow canvas with palette, undo/redo, keyboard shortcuts |
| `frontend/src/lib/layout.js` | `traceToFlow` / `flowToTrace` + dagre auto-layout |

### Supported element types

- **Fabric types:** `humanSource`, `inputOutput`, `fixedAIModel`, `trainingAIModel`, `governanceMechanism`, `ui`, `decisionPoint`, `accept`, `modify`, `reject`, `restart`, `finalOutcome`
- **Generic activities/gateways (rarely used):** `task`, `userTask`, `serviceTask`, `scriptTask`, `exclusiveGateway`, `parallelGateway`

The entry of a trace is the single element with no incoming flow (typically a `humanSource`, `ui`, or `inputOutput`); terminals are `finalOutcome` nodes — there's no separate start/end event type.

## Getting started

### Prerequisites

- Python 3.12+
- Node.js 20+ (for the frontend dev server / build)
- An OpenAI API key

### Installation

```bash
git clone https://github.com/ShinZert/TRACE_Fabric.git
cd TRACE_Fabric

# Backend deps
pip install -r requirements.txt

# Frontend deps
cd frontend && npm install && cd ..

# Environment
cp .env.example .env  # then edit and add your keys
```

`.env` requires at minimum:

```
OPENAI_API_KEY=sk-proj-...
SECRET_KEY=<a random hex string — generate with `python -c "import secrets; print(secrets.token_hex(32))"`>
```

The app **refuses to start without `SECRET_KEY`** in production. For quick local hacking, set `FLASK_DEBUG=1` to use an ephemeral generated key (and to enable Flask's debugger).

### Run

Two modes:

**Development (HMR)** — run both processes in parallel and open <http://localhost:5173>:

```bash
# Terminal 1 — Flask API on :5000
python app.py

# Terminal 2 — Vite dev server on :5173 (proxies /api/* to Flask)
cd frontend && npm run dev
```

**Production / one-process** — build the bundle once, then run Flask alone and open <http://localhost:5000>:

```bash
cd frontend && npm run build && cd ..
python app.py
```

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
