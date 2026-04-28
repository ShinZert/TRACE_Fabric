# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Weaver — a conversational AI app that converts natural language descriptions and flowchart images into **Fabric decision-trace** diagrams (a design language for AI-system workflows: humans, AI models, governance steps, accept/modify/reject decisions). Users describe processes in chat, upload sketches, and iteratively refine the trace through conversation and direct manipulation.

## Development Commands

```bash
# Backend (Python / Flask) — install + run
pip install -r requirements.txt
python app.py             # Flask dev server on http://localhost:5000 (API + production bundle)

# Frontend (React + Vite) — install + dev / build
cd frontend
npm install
npm run dev               # Vite dev server on http://localhost:5173 with HMR
npm run build             # Production bundle → ../static/dist/

# Required .env file at repo root
OPENAI_API_KEY=your-key
SECRET_KEY=<random hex; the app refuses to start without one unless FLASK_DEBUG=1>
```

Optional env vars: `FLASK_DEBUG=1` (enables Werkzeug debugger + ephemeral generated SECRET_KEY), `OPENAI_TIMEOUT` (seconds, default 60), `MAX_TRACE_TOKENS` / `MAX_SUMMARY_TOKENS_TEXT` / `MAX_SUMMARY_TOKENS_IMAGE`, `RATELIMIT_STORAGE_URI` (defaults to `memory://`; set to a Redis URL for shared rate-limit counters across workers).

**Two run modes**
- **Development:** run `python app.py` AND `npm run dev` in parallel, then open `http://localhost:5173`. Vite proxies `/api/*` to Flask. HMR works.
- **Production / one-process:** run `npm run build`, then `python app.py`, then open `http://localhost:5000`. Flask serves the built bundle from `static/dist/`.

There is no test suite or linter config.

## Architecture

**Stack:** Flask backend (Python 3.12, gunicorn in prod) + React 18 frontend (Vite build, React Flow 12 for the editor canvas, dagre for auto-layout). All wire-format between frontend and backend is JSON — there is no BPMN XML round-trip.

**Request pipeline:** User input → React `App.handleSend` → `POST /api/chat` → `_build_messages()` constructs conversation (system prompt + 3 few-shot examples + last 6 turns + edit context) → OpenAI API → `_extract_json()` parses LLM output → schema + semantic validation → returned as `{ trace, process_name }` → React Flow renders via `traceToFlow()` and `layoutWithDagre()`.

**Edit round-trip:** User edits trace in React Flow editor → editor calls `onTraceCommit(newTrace)` after each user action → `App` tracks `traceDraft` vs `trace` to compute `isDirty` → user clicks "Sync edits" → `POST /api/sync` with the trace JSON → backend rejects (HTTP 400) on schema errors and keeps the previous `current_trace`, otherwise stores it in the session → LLM sees updated trace in next request via `EDIT_CONTEXT_TEMPLATE`. No XML conversion at any step.

### Chat flows (`/api/chat`)

The chat endpoint handles four distinct flows:

- **Flow A (Edit):** `current_trace` exists, no image, no pending → direct LLM generation with edit context injected
- **Flow B (Summarize):** New diagram or image, no pending → `generate_summary()` produces plain-text summary, stored in `pending_confirmation`, awaits user confirm/revise
- **Flow C (Confirm):** `pending_confirmation` exists, `confirm=true` → generates trace from stored message (supports inline summary edits via `edited_summary`)
- **Flow D (Revise):** `pending_confirmation` exists, new user message → combines with original message, clears pending, falls through to re-summarize

### Backend modules

- **`app.py`** — Flask routes: `/api/chat` (main pipeline with 4 flows), `/api/upload` (image to base64), `/api/export` (download trace JSON), `/api/sync` (JSON round-trip for manual edits), `/api/reset` (clear session), `/api/health` (liveness probe). Renders `templates/index.html` at `/`. Per-IP rate limiting via Flask-Limiter (30/min, 500/day on chat; 60/min, 500/day on upload; 200/min global default).
- **`config.py`** — Centralized settings: model (`gpt-5-mini`), conversation window (6 turns = 12 messages), upload limit (16MB), secret key, OpenAI request timeout, and token budgets (`MAX_TRACE_TOKENS=16384`, `MAX_SUMMARY_TOKENS_TEXT=4096`, `MAX_SUMMARY_TOKENS_IMAGE=8192`) — all overridable via env vars. GPT-5-mini does not accept a `temperature` parameter, so none is sent. Image bytes are sniffed via Pillow (`services/image_validator.py`) before being forwarded to OpenAI.
- **`prompts/system_prompt.py`** — `SYSTEM_PROMPT` defines the JSON output format and the 12 Fabric element types; `SUMMARY_PROMPT` instructs the LLM to produce plain-text process summaries; `EDIT_CONTEXT_TEMPLATE` injects current trace state for edits.
- **`prompts/few_shot_examples.py`** — 3 few-shot examples always included in every request, all using Fabric types. Loaded from `prompts/few_shot_examples.json`.
- **`services/llm_service.py`** — OpenAI integration; `generate_trace()` for trace generation, `generate_summary()` for the summarize-then-confirm step; `_extract_json()` handles raw JSON, code-fenced JSON, and embedded JSON via brace-matching fallback; `_build_messages()` assembles the full conversation array.
- **`services/schema_validator.py`** — Two-pass validation: jsonschema against the Fabric schema, then semantic checks (≥1 finalOutcome, exactly 1 entry node — i.e. a single element with no incoming flow — no dead ends, valid flow refs, no duplicate IDs, finalOutcomes have no outgoing flows). Fabric has no separate start-event type; the entry is identified structurally.

### Frontend modules

- **`frontend/src/App.jsx`** — Top-level React component. Owns `messages`, `trace` (canonical, server-blessed) and `traceDraft` (editor's working copy). Computes `isDirty` from a JSON signature diff. Wires chat → editor → `/api/sync`.
- **`frontend/src/components/Editor.jsx`** — React Flow canvas with hand/select cursor modes, drag-and-drop palette, undo/redo (60-deep snapshot history), keyboard shortcuts (V/H, Ctrl+Z, Ctrl+Shift+Z), inline inspector for the selected node. `onTraceCommit` fires after every user action.
- **`frontend/src/components/FabricNode.jsx`** — Custom React Flow node type. SVG shape from `lib/shapes.jsx`, HTML label overlay, target/source handles (left/right).
- **`frontend/src/components/LeftPalette.jsx`** — Floating left-edge tool bar: hand/select tools at top, separator, then a 2-column grid of draggable shape thumbnails (one per Fabric type).
- **`frontend/src/components/Inspector.jsx`** — Side panel that shows the selected node's id (read-only), type (dropdown), label (input), and a delete button.
- **`frontend/src/components/ChatPanel.jsx`** — Chat panel with messages, image upload + drop overlay, summary message with Confirm/Revise inline editing, reset button.
- **`frontend/src/lib/types.js`** — `TYPE_STYLES` table — single source of truth for visual styling per Fabric type (used by canvas nodes, palette thumbnails, inspector, minimap).
- **`frontend/src/lib/shapes.jsx`** — `ShapeSVG` component that renders the appropriate SVG primitive (rect, ellipse, polygon) per type, sized by props. Reused by `FabricNode` and palette thumbnails.
- **`frontend/src/lib/layout.js`** — `traceToFlow()` / `flowToTrace()` conversion + `layoutWithDagre()` left-to-right auto-layout. Layout runs on initial load, on Re-layout, and after sync.
- **`frontend/src/lib/api.js`** — Thin `fetch` wrappers around `/api/chat`, `/api/sync`, `/api/reset`, plus `traceDownloadUrl()` for the Export JSON action. Each request has a 90s `AbortSignal.timeout`; backend OpenAI calls time out at 60s, so the user sees the real error before the abort fires.

### Trace JSON format

The LLM produces (and the editor consumes) the same intermediate JSON schema:

```json
{
  "process_name": "string",
  "elements": [{ "id": "snake_case_id", "type": "humanSource|fixedAIModel|...", "name": "Display Label" }],
  "flows": [{ "id": "flow_id", "from": "source_id", "to": "target_id", "name": "optional condition" }]
}
```

Element IDs must match `^[a-z][a-z0-9_]*$`. Supported element types (from `services/schema_validator.py`):

- **Fabric types:** `humanSource`, `inputOutput`, `fixedAIModel`, `trainingAIModel`, `governanceMechanism`, `ui`, `decisionPoint`, `accept`, `modify`, `reject`, `restart`, `finalOutcome`
- **Generic activities/gateways (rarely used):** `task`, `userTask`, `serviceTask`, `scriptTask`, `exclusiveGateway`, `parallelGateway`

The entry of a trace is whichever element has no incoming flow — typically a `humanSource`, `ui`, or `inputOutput`. Terminal nodes are `finalOutcome`s. There is no dedicated start- or end-event type.

### State management

- **Backend session** (Flask, ephemeral): `conversation` (max 6 turns = 12 messages), `current_trace` (the blessed state for edit-context injection), `pending_confirmation` (original message + summary while awaiting confirm/revise). No database.
- **Frontend state** (React): `messages` (chat log), `trace` (canonical, last server-blessed), `traceDraft` (editor's working copy after local edits), `pendingImage` (image held for re-send on confirm), `isProcessing`, `isSyncing`. `isDirty` is derived from JSON signature comparison.
- **Editor internal state** (React Flow): `nodes`, `edges`, selection, mode (`pan`|`select`), undo/redo history. The editor receives `trace` as a prop and resets when the trace's signature changes (catches LLM regenerations).

### Frontend build pipeline

- Vite (`frontend/vite.config.js`) builds to `../static/dist/` with predictable filenames (no hashes).
- Flask `templates/index.html` references `/static/dist/assets/main.css` and `/static/dist/assets/main.js` directly via Jinja's `url_for`.
- `static/dist/` is gitignored (along with `frontend/node_modules/` and `frontend/dist/`). Production deploys must run `npm install && npm run build` before starting Flask. The `Dockerfile` does this in a multi-stage build automatically.

### Gotchas

- **Manual node positions ARE preserved** across edits within a session (React Flow tracks positions in nodes state). Only Re-layout or a fresh trace from the LLM clears manual positions — different from the previous bpmn-js setup, where layout was always recomputed.
- **Image inputs skip edit context** — providing an image always treats the request as a fresh generation, even if `current_trace` exists.
- **`/api/sync` rejects schema-invalid traces** — schema errors return HTTP 400 with the previous `current_trace` echoed back; the editor keeps its draft so the user can fix the issues. Semantic warnings (orphans, dead-ends, etc.) still pass through.
- **Sync is manual** — users must click "Sync edits" before chatting again, or the LLM operates on the last-synced trace and unsynced visual edits are effectively lost on the next AI generation. The "unsaved edits" pill on the editor toolbar warns about this.
- **Few-shot examples** are sent with every request — they live in `prompts/few_shot_examples.json` and are loaded by `prompts/few_shot_examples.py`. Keep that JSON in sync with the Fabric type list if the schema changes.
- **No BPMN export** — the .bpmn export was removed when bpmn-js was retired in favour of React Flow. Export is JSON-only (`/api/export` and the editor's Export JSON button).

## Deployment

Production runs as two containers via `docker-compose.yml`: the Flask app (gunicorn, 2 workers, 120s timeout) on port 8000, fronted by nginx on port 80. The Dockerfile is multi-stage: stage 1 (`node:20-slim`) builds the Vite bundle, stage 2 (`python:3.12-slim`) runs Flask with the bundle copied in.

The `deploy.sh` script wraps SSH-based deploys to a Digital Ocean droplet — `./deploy.sh deploy` does `git pull` + `docker compose up -d --build` on the remote (the multi-stage Dockerfile handles the npm build inside the container, so the host doesn't need Node). See `DEVELOPMENT.md` for full droplet setup, HTTPS via Certbot, and the `set-token` flow for storing a GitHub PAT on the server.

Note: `deploy.sh` references `APP_DIR=/opt/bpmn-chatbot` (legacy name from before the Fabric rename and the React Flow migration).
