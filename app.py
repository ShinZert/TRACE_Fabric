"""
Weaver — Flask Application
Generates Fabric decision-trace JSON from natural language descriptions and
sketches. The frontend (React + React Flow, built via Vite into static/dist/)
renders the trace directly — no BPMN XML round-trip.
"""

import base64
import json as _json
import os

from flask import Flask, render_template, request, jsonify, session, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import SECRET_KEY, MAX_CONTENT_LENGTH, OPENAI_MODEL
from services.llm_service import generate_trace, generate_summary
from services.schema_validator import validate_schema, validate_semantics
from services.image_validator import validate_image_base64, validate_image_bytes

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

# Trust one proxy hop (nginx → gunicorn per docker-compose). Without this,
# every request looks like it came from nginx's container IP and the rate
# limiter buckets all users together.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Per-IP rate limiting. The in-memory backend means each gunicorn worker
# tracks its own counters — with 2 workers, the effective allowance is
# roughly doubled. For a stricter cap, point RATELIMIT_STORAGE_URI at Redis.
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
    headers_enabled=True,
)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": f"Rate limit exceeded: {e.description}. Please slow down.",
    }), 429


@app.route("/api/health")
@limiter.exempt
def health():
    """Liveness probe — fast, no external dependencies."""
    return jsonify({"status": "ok", "model": OPENAI_MODEL})


@app.route("/")
def index():
    """Serve the chat interface."""
    if "conversation" not in session:
        session["conversation"] = []
    if "current_trace" not in session:
        session["current_trace"] = None
    if "pending_confirmation" not in session:
        session["pending_confirmation"] = None
    return render_template("index.html")


def _diagram_response(trace, raw_response, original_message, warnings=None):
    """Append a user/assistant turn and return the diagram payload."""
    conversation = session.get("conversation", [])
    conversation.append({"role": "user", "content": original_message or "[Image uploaded]"})
    conversation.append({"role": "assistant", "content": raw_response})
    session["conversation"] = conversation
    session["current_trace"] = trace
    return jsonify({
        "type": "diagram",
        "trace": trace,
        "process_name": trace.get("process_name", "Process"),
        "warnings": warnings or [],
        "error": None,
    })


def _validate_for_render(trace):
    """
    Schema errors are hard failures (we can't render an unparseable trace).
    Semantic errors (orphans, dead-ends, etc.) are returned as warnings —
    the trace renders, the user sees the issues, and they can fix in the
    editor. Returns (schema_errors, warnings).
    """
    schema_ok, schema_errors = validate_schema(trace)
    if not schema_ok:
        return schema_errors, []
    _, semantic_errors = validate_semantics(trace)
    return [], semantic_errors


def _trace_response(result, original_message):
    """
    Common LLM-result handling for chat flows. Returns either a finished
    Flask response (on error or success) or None if the caller should keep
    going. Centralises the LLM-error / schema-error / diagram-response
    triad that was repeated for each chat flow.
    """
    if result["error"]:
        return jsonify({"error": result["error"]}), 502
    trace = result["json"]
    schema_errors, warnings = _validate_for_render(trace)
    if schema_errors:
        return jsonify({
            "error": "Schema errors: " + "; ".join(schema_errors),
        }), 422
    return _diagram_response(trace, result["raw_response"], original_message, warnings=warnings)


@app.route("/api/chat", methods=["POST"])
@limiter.limit("30 per minute; 500 per day")
def chat():
    """
    Process user input through the LLM pipeline with a summarize-then-confirm flow.

    Four flows:
      A) Edit — current_trace exists, no image, no pending → direct generation
      B) Summarize — new diagram or image, no pending → summary, await confirmation
      C) Confirm — pending exists, confirm=true → generate from stored message
      D) Revise — pending exists, new user message → combine + re-summarize
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input provided"}), 400

    user_message = data.get("message", "").strip()
    image_base64 = data.get("image_base64")
    confirm = data.get("confirm", False)

    image_mime = None
    if image_base64:
        image_mime, image_error = validate_image_base64(image_base64)
        if image_error:
            return jsonify({"error": image_error}), 400

    conversation = session.get("conversation", [])
    current_trace = session.get("current_trace")
    pending = session.get("pending_confirmation")

    # --- Flow C: confirm pending summary -----------------------------------
    if pending and confirm:
        original_message = pending["original_message"]
        session["pending_confirmation"] = None

        edited_summary = data.get("edited_summary")
        if edited_summary and isinstance(edited_summary, str):
            original_message = edited_summary.strip()

        result = generate_trace(
            user_message=original_message,
            conversation_history=conversation,
            current_trace=None,
            image_base64=image_base64,
            image_mime=image_mime,
        )
        return _trace_response(result, original_message)

    # --- Flow D: pending exists + new message → combine and re-summarize ---
    if pending and user_message:
        original_message = pending["original_message"]
        combined_message = (
            f"{original_message}\n\n"
            f"Additional details/corrections: {user_message}"
        )
        session["pending_confirmation"] = None
        user_message = combined_message
        image_base64 = None  # image not retained on revise
        image_mime = None

    if not user_message and not image_base64:
        return jsonify({"error": "Please provide a message or upload an image"}), 400

    # --- Flow A: edit existing trace (text-only, trace already loaded) -----
    if current_trace and not image_base64:
        result = generate_trace(
            user_message=user_message,
            conversation_history=conversation,
            current_trace=current_trace,
            image_base64=None,
        )
        return _trace_response(result, user_message)

    # --- Flow B: summarize before generating -------------------------------
    summary_result = generate_summary(
        user_message=user_message,
        image_base64=image_base64,
        image_mime=image_mime,
    )
    if summary_result["error"]:
        return jsonify({"error": summary_result["error"]}), 502

    session["pending_confirmation"] = {
        "original_message": user_message,
        "summary": summary_result["summary"],
    }
    return jsonify({
        "type": "summary",
        "summary": summary_result["summary"],
        "error": None,
    })


@app.route("/api/sync", methods=["POST"])
def sync():
    """Accept the editor's current trace JSON, validate leniently, store it."""
    data = request.get_json()
    if not data or "trace" not in data:
        return jsonify({"error": "No trace provided"}), 400

    trace = data["trace"]
    if not isinstance(trace, dict):
        return jsonify({"error": "Trace must be an object"}), 400

    schema_errors, semantic_warnings = _validate_for_render(trace)
    # Schema errors mean we can't store this trace — the next /api/chat would
    # inject a malformed trace into the LLM's edit context. Reject the sync
    # so the editor keeps its draft and the user can fix the issues. Semantic
    # warnings (orphans, dead-ends, etc.) are still allowed through so the
    # user can iterate on them in conversation.
    if schema_errors:
        return jsonify({
            "status": "rejected",
            "error": "Cannot sync invalid trace: " + "; ".join(schema_errors),
            "warnings": schema_errors,
            "trace": session.get("current_trace"),
        }), 400

    session["current_trace"] = trace
    # The next /api/chat call sees the updated trace via EDIT_CONTEXT_TEMPLATE,
    # so we don't need synthetic "[Trace was edited]" turns here — those just
    # burn slots in the 6-turn conversation window.
    return jsonify({"status": "ok", "warnings": semantic_warnings, "trace": trace})


@app.route("/api/export")
def export_json():
    """Download the current trace as a .json file."""
    trace = session.get("current_trace")
    if not trace:
        return jsonify({"error": "No trace to export"}), 404

    process_name = trace.get("process_name", "fabric-trace")
    filename = process_name.replace(" ", "_").lower() + ".json"

    return Response(
        _json.dumps(trace, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/api/upload", methods=["POST"])
@limiter.limit("60 per minute; 500 per day")
def upload():
    """Accept a multipart image upload, return base64."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    file_bytes = file.read()
    image_mime, image_error = validate_image_bytes(file_bytes)
    if image_error:
        return jsonify({"error": image_error}), 400

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    return jsonify({"image_base64": b64, "image_mime": image_mime})


@app.route("/api/reset", methods=["POST"])
def reset():
    """Reset conversation and trace state."""
    session["conversation"] = []
    session["current_trace"] = None
    session["pending_confirmation"] = None
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Werkzeug's debugger is an RCE vector when reachable from the network,
    # so it stays off unless explicitly opted into via FLASK_DEBUG=1.
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)
