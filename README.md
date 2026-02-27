# Fabric

A conversational AI application that converts natural language descriptions and flowchart images into BPMN 2.0 workflow diagrams. Users describe processes in chat, upload sketches, and iteratively refine diagrams through conversation.

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Flask](https://img.shields.io/badge/Flask-3.1-lightgrey)
![OpenAI](https://img.shields.io/badge/OpenAI-GPT--5--mini-green)
![bpmn-js](https://img.shields.io/badge/bpmn--js-17.11.1-orange)

## Features

- **Text-to-BPMN** — Describe a business process in plain language and get a standards-compliant BPMN 2.0 diagram
- **Image-to-BPMN** — Upload a hand-drawn flowchart or screenshot and have it converted into a structured diagram
- **Conversational editing** — Refine diagrams iteratively ("add an approval step before payment", "make the review gateway parallel")
- **Visual editor** — Drag, resize, and rewire elements directly on the canvas using bpmn-js, then sync changes back
- **Export** — Download diagrams as `.bpmn` files compatible with Camunda, Signavio, and other BPMN tools
- **Summary-and-confirm flow** — New diagrams go through a summary step so you can review the AI's interpretation before generation

## Architecture

```
User input ─→ Flask /api/chat ─→ Build message array ─→ OpenAI API
                                   (system prompt +       │
                                    few-shot examples +   │
                                    conversation history + │
                                    edit context)         │
                                                          ▼
bpmn-js renders ◄── json_to_bpmn_xml() ◄── Validation ◄── Parse JSON response
in browser            with auto-layout      (schema +
                                             semantic)
```

### Key Modules

| Module | Responsibility |
|---|---|
| `app.py` | Flask routes — `/api/chat`, `/api/upload`, `/api/export`, `/api/sync`, `/api/reset` |
| `config.py` | Centralized settings — model, token limits, conversation window, upload size |
| `prompts/system_prompt.py` | LLM system prompt and edit-context template |
| `prompts/few_shot_examples.py` | 3 few-shot examples included in every request |
| `services/llm_service.py` | OpenAI integration with JSON extraction (raw, code-fenced, brace-matching fallback) |
| `services/schema_validator.py` | Two-pass validation — jsonschema + semantic checks (orphans, flow refs, duplicates) |
| `services/bpmn_converter.py` | Bidirectional JSON↔XML conversion with type mapping for unsupported elements |
| `services/layout_engine.py` | Auto-layout via topological sort with L/Z-shaped edge routing |

### Supported BPMN Elements

`startEvent` · `endEvent` · `task` · `userTask` · `serviceTask` · `scriptTask` · `exclusiveGateway` · `parallelGateway`

Unsupported types from manual edits are automatically mapped to supported equivalents (e.g., `inclusiveGateway` → `exclusiveGateway`, `subProcess` → `task`).

## Getting Started

### Prerequisites

- Python 3.10+
- An OpenAI API key

### Installation

```bash
# Clone the repository
git clone https://github.com/ShinZert/TRACE_Fabric.git
cd TRACE_Fabric

# Install dependencies
pip install -r requirements.txt

# Create your .env file
cp .env.example .env  # or create manually
```

Add your keys to `.env`:

```
OPENAI_API_KEY=your-openai-api-key
SECRET_KEY=change-this-in-production
```

### Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000) in your browser.

## Usage

1. **Describe a process** — Type something like *"Order processing: customer places order, warehouse checks stock, if in stock ship it, otherwise notify customer"*
2. **Review the summary** — The AI summarizes its understanding; confirm or provide corrections
3. **Refine** — Ask for changes: *"Add a payment verification step after order placement"*
4. **Edit visually** — Drag elements on the canvas, then click **Sync Edits** to persist changes
5. **Export** — Click **Export** to download the `.bpmn` file

You can also **drag and drop an image** of a flowchart onto the chat panel to convert it into a BPMN diagram.

## Tech Stack

- **Backend:** Flask, OpenAI Python SDK, jsonschema
- **Frontend:** Vanilla JS, bpmn-js (CDN), HTML/CSS
- **State:** Flask sessions (ephemeral, no database)

## License

This project is for educational and research purposes.
