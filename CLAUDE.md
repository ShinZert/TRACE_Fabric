# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Fabric — a conversational AI app that converts natural language descriptions and flowchart images into BPMN 2.0 workflow diagrams. Users describe processes in chat, upload sketches, and iteratively refine diagrams through conversation.

## Development Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app (Flask dev server on http://localhost:5000)
python app.py

# Required .env file
OPENAI_API_KEY=your-key
SECRET_KEY=change-this-in-production
```

There is no test suite, linter config, or frontend build step. The frontend uses vanilla JS with bpmn-js (v17.11.1) loaded from CDN.

## Architecture

**Request pipeline:** User input → Flask `/api/chat` → `_build_messages()` constructs conversation (system prompt + 3 few-shot examples + last 6 turns + edit context) → OpenAI API → `_extract_json()` parses LLM output → schema + semantic validation → `json_to_bpmn_xml()` with auto-layout → bpmn-js renders in browser.

**Edit round-trip:** User edits diagram in bpmn-js → frontend `syncDiagram()` calls `/api/sync` → `bpmn_xml_to_json()` converts XML back to intermediate JSON (normalizes IDs to snake_case, maps unsupported element types via `REVERSE_TYPE_MAP`) → stored in session → LLM sees updated diagram in next request via `EDIT_CONTEXT_TEMPLATE`.

### Chat flows (`/api/chat`)

The chat endpoint handles four distinct flows:

- **Flow A (Edit):** `current_json` exists, no image, no pending → direct LLM generation with edit context injected
- **Flow B (Summarize):** New diagram or image, no pending → `generate_summary()` produces plain-text summary, stored in `pending_confirmation`, awaits user confirm/revise
- **Flow C (Confirm):** `pending_confirmation` exists, `confirm=true` → generates diagram from stored message (supports inline summary edits via `edited_summary`)
- **Flow D (Revise):** `pending_confirmation` exists, new user message → combines with original message, clears pending, falls through to re-summarize

### Key modules

- **`app.py`** — Flask routes: `/api/chat` (main pipeline with 4 flows), `/api/upload` (image to base64), `/api/export` (download .bpmn), `/api/sync` (XML→JSON round-trip for manual edits), `/api/reset` (clear session)
- **`config.py`** — Centralized config: model (`gpt-5-mini`), max completion tokens (4096), conversation window (6 turns), upload limit (16MB). No temperature parameter — GPT-5-mini doesn't support it
- **`prompts/system_prompt.py`** — `SYSTEM_PROMPT` defines JSON output format and BPMN rules; `SUMMARY_PROMPT` instructs the LLM to produce plain-text process summaries; `EDIT_CONTEXT_TEMPLATE` injects current diagram state for edits
- **`prompts/few_shot_examples.py`** — 3 few-shot examples always included in every request: linear workflow, exclusive gateway branching, parallel gateway fork/join. Loaded from `few_shot_examples.json`
- **`services/llm_service.py`** — OpenAI integration; `generate_bpmn()` for diagram generation, `generate_summary()` for the summarize-then-confirm step; `_extract_json()` handles raw JSON, code-fenced JSON, and embedded JSON objects via brace-matching fallback; `_build_messages()` assembles the full conversation array
- **`services/schema_validator.py`** — Two-pass validation: jsonschema against `BPMN_JSON_SCHEMA`, then semantic checks (exactly 1 startEvent, ≥1 endEvent, no orphans, valid flow refs, no duplicate IDs, correct start/end flow directions)
- **`services/bpmn_converter.py`** — Bidirectional JSON↔XML conversion. `REVERSE_TYPE_MAP` maps unsupported BPMN types to supported ones (e.g., inclusiveGateway→exclusiveGateway, subProcess→task, sendTask→serviceTask, manualTask→userTask)
- **`services/layout_engine.py`** — Auto-layout: topological sort assigns columns, predecessors inform row alignment, gateway successors spread symmetrically. Edge routing uses L-shaped/Z-shaped waypoints. Layout is **always recomputed** — manual positioning from bpmn-js is not preserved

### Intermediate JSON format

The LLM produces a custom JSON schema (not standard BPMN), which is then converted to XML:
```json
{
  "process_name": "string",
  "elements": [{ "id": "snake_case_id", "type": "startEvent|endEvent|task|exclusiveGateway|...", "name": "Label" }],
  "flows": [{ "id": "flow_id", "from": "source_id", "to": "target_id", "name": "optional condition" }]
}
```

Element IDs must match `^[a-z][a-z0-9_]*$`. Supported types: `startEvent`, `endEvent`, `task`, `userTask`, `serviceTask`, `scriptTask`, `exclusiveGateway`, `parallelGateway`.

### State management

- **Backend:** Flask sessions store `conversation` (message history, max 6 turns = 12 messages), `current_json` (current BPMN model for edit context injection), and `pending_confirmation` (stores original message + summary text while awaiting user confirm/revise). No database — all state is ephemeral
- **Frontend:** `static/js/app.js` tracks `currentXml`, `pendingImageBase64`, `confirmationImageBase64` (image held for re-send on confirm), `isDirty` (via bpmn-js `commandStack` index comparison against `baselineStackIndex`), and processing flags
- When an image is provided, edit context is skipped — the LLM treats it as a fresh generation from the image

### Frontend

Single-page app: `templates/index.html` + `static/js/app.js` + `static/css/style.css`. Two-panel layout: chat (400px fixed left) + bpmn-js modeler (flex right). Features: image drag-drop upload, .bpmn and PNG export, undo/redo via commandStack, sync button (amber highlight when dirty), zoom controls, inline summary editing with confirm/revise buttons, new session reset.

## Validation pipeline

Schema validation runs first (jsonschema against `BPMN_JSON_SCHEMA`), then semantic validation: exactly 1 startEvent, ≥1 endEvent, no orphan nodes, no dead ends, valid flow references, no duplicate IDs, startEvent has no incoming flows, endEvent has no outgoing flows. The `/api/sync` route stores JSON even on validation failure (lenient mode) to allow incremental fixing.
