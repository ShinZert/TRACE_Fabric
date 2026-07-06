"""
Weaver — Flask Application
Generates Fabric decision-trace JSON from natural language descriptions and
sketches. The frontend (React + React Flow, built via Vite into static/dist/)
renders the trace directly.
"""

import base64
import hmac
import json as _json
import os

from flask import Flask, render_template, request, jsonify, session, Response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from config import SECRET_KEY, MAX_CONTENT_LENGTH, OPENAI_MODEL, APP_PASSWORD
from services.llm_service import generate_trace, generate_summary
from services.schema_validator import validate_schema, validate_semantics
from services.image_validator import validate_image_base64, validate_image_bytes
from services.event_logger import log_event
from services.telemetry import generation_metrics, structural_metrics, cost_metrics

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


# --- Password gate ---------------------------------------------------------
# Endpoints reachable without the shared password. Everything else under /api/
# is blocked until the session is authed. The index shell and static bundle are
# left open on purpose — they're inert without the API, and the React gate needs
# to load in order to render the login screen.
_GATE_EXEMPT_PATHS = {"/api/health", "/api/login", "/api/auth/status"}


@app.before_request
def _require_password():
    """Block /api/* until the session has cleared the shared password gate."""
    if not APP_PASSWORD:
        return  # gate disabled — open access
    path = request.path
    if not path.startswith("/api/") or path in _GATE_EXEMPT_PATHS:
        return
    if session.get("authed"):
        return
    return jsonify({"error": "Password required", "auth_required": True}), 401


@app.route("/api/auth/status")
@limiter.exempt
def auth_status():
    """Report whether the gate is active and whether this session has cleared it."""
    return jsonify({
        "gate": bool(APP_PASSWORD),
        "authed": (not APP_PASSWORD) or bool(session.get("authed")),
    })


@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute; 100 per day")
def login():
    """Check the shared password and mark the session authenticated."""
    if not APP_PASSWORD:
        session["authed"] = True
        return jsonify({"status": "ok", "gate": False})

    data = request.get_json(silent=True) or {}
    supplied = data.get("password", "")
    if not isinstance(supplied, str):
        supplied = ""

    # Constant-time compare so response timing can't leak the password.
    if hmac.compare_digest(supplied, APP_PASSWORD):
        session["authed"] = True
        log_event("login", status="ok")
        return jsonify({"status": "ok"})

    log_event("login", status="failed")
    return jsonify({"error": "Incorrect password"}), 401


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


def _trace_response(result, original_message, flow):
    """
    Common LLM-result handling for chat flows. Returns either a finished
    Flask response (on error or success) or None if the caller should keep
    going. Centralises the LLM-error / schema-error / diagram-response
    triad that was repeated for each chat flow.
    """
    trace = result.get("json")
    metrics = generation_metrics(
        trace,
        usage=result.get("usage"),
        latency_ms=result.get("latency_ms", 0),
        parse_error=result.get("error") if trace is None else None,
    )
    log_event(
        "chat_generation",
        flow=flow,
        message_len=len(original_message or ""),
        finish_reason=result.get("finish_reason"),
        api_error=result.get("error") if trace is None else None,
        **metrics,
    )

    if result["error"]:
        return jsonify({"error": result["error"]}), 502
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
        return _trace_response(result, original_message, flow="confirm")

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
        return _trace_response(result, user_message, flow="edit")

    # --- Flow B: summarize before generating -------------------------------
    summary_result = generate_summary(
        user_message=user_message,
        image_base64=image_base64,
        image_mime=image_mime,
    )
    log_event(
        "chat_summarize",
        message_len=len(user_message or ""),
        has_image=bool(image_base64),
        api_error=summary_result.get("error"),
        summary_len=len(summary_result.get("summary") or ""),
        **cost_metrics(summary_result.get("usage"), summary_result.get("latency_ms", 0)),
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
        log_event(
            "sync",
            status="rejected",
            schema_errors=schema_errors,
            **structural_metrics(trace),
        )
        return jsonify({
            "status": "rejected",
            "error": "Cannot sync invalid trace: " + "; ".join(schema_errors),
            "warnings": schema_errors,
            "trace": session.get("current_trace"),
        }), 400

    session["current_trace"] = trace
    log_event(
        "sync",
        status="ok",
        semantic_warnings=semantic_warnings,
        **structural_metrics(trace),
    )
    # The next /api/chat call sees the updated trace via EDIT_CONTEXT_TEMPLATE,
    # so we don't need synthetic "[Trace was edited]" turns here — those just
    # burn slots in the 6-turn conversation window.
    return jsonify({"status": "ok", "warnings": semantic_warnings, "trace": trace})


@app.route("/api/export")
def export_json():
    """Download the current trace as a .json file."""
    trace = session.get("current_trace")
    if not trace:
        log_event("export", status="empty")
        return jsonify({"error": "No trace to export"}), 404

    process_name = trace.get("process_name", "fabric-trace")
    filename = process_name.replace(" ", "_").lower() + ".json"

    log_event(
        "export",
        status="ok",
        process_name=process_name,
        **structural_metrics(trace),
    )

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
        log_event("upload", status="rejected", error=image_error, bytes=len(file_bytes))
        return jsonify({"error": image_error}), 400

    b64 = base64.b64encode(file_bytes).decode("utf-8")
    log_event("upload", status="ok", bytes=len(file_bytes), mime=image_mime)
    return jsonify({"image_base64": b64, "image_mime": image_mime})


@app.route("/api/reset", methods=["POST"])
def reset():
    """Reset conversation and trace state."""
    log_event(
        "reset",
        had_trace=bool(session.get("current_trace")),
        conversation_len=len(session.get("conversation", [])),
    )
    session["conversation"] = []
    session["current_trace"] = None
    session["pending_confirmation"] = None
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    # Werkzeug's debugger is an RCE vector when reachable from the network,
    # so it stays off unless explicitly opted into via FLASK_DEBUG=1.
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", port=5000)
