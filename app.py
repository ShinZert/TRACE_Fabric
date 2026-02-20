"""
BPMN ProcessPilot - Flask Application
Converts text descriptions and images into BPMN 2.0 workflow diagrams.
"""

import json
import os
from flask import Flask, render_template, request, jsonify, session, Response
from config import SECRET_KEY, UPLOAD_FOLDER, MAX_CONTENT_LENGTH
from services.llm_service import generate_bpmn, generate_summary
from services.schema_validator import validate
from services.bpmn_converter import json_to_bpmn_xml, bpmn_xml_to_json

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


@app.route("/")
def index():
    """Serve the chat interface."""
    # Initialize session state
    if "conversation" not in session:
        session["conversation"] = []
    if "current_json" not in session:
        session["current_json"] = None
    if "pending_confirmation" not in session:
        session["pending_confirmation"] = None
    return render_template("index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    Process user input through the LLM pipeline with a summarize-then-confirm flow.

    Four flows:
      A) Edit — current_json exists, no image, no pending → direct diagram generation
      B) Summarize — new diagram or image, no pending → generate summary, await confirmation
      C) Confirm — pending exists, confirm=true → generate diagram from stored message
      D) Revise — pending exists, new user message → combine with original, re-summarize
    """
    data = request.get_json()
    if not data:
        return jsonify({"error": "No input provided"}), 400

    user_message = data.get("message", "").strip()
    image_base64 = data.get("image_base64")
    confirm = data.get("confirm", False)

    # Get session state
    conversation = session.get("conversation", [])
    current_json = session.get("current_json")
    pending = session.get("pending_confirmation")

    # --- Flow C: Confirm pending summary ---
    if pending and confirm:
        original_message = pending["original_message"]
        summary_text = pending["summary"]
        session["pending_confirmation"] = None

        # If user edited the summary inline, use the edited text instead
        edited_summary = data.get("edited_summary")
        if edited_summary and isinstance(edited_summary, str):
            original_message = edited_summary.strip()

        result = generate_bpmn(
            user_message=original_message,
            conversation_history=conversation,
            current_json=None,
            image_base64=image_base64
        )

        if result["error"]:
            return jsonify({"error": result["error"]})

        bpmn_json = result["json"]

        is_valid, errors = validate(bpmn_json)
        if not is_valid:
            return jsonify({"error": "Validation errors: " + "; ".join(errors)})

        try:
            bpmn_xml = json_to_bpmn_xml(bpmn_json)
        except Exception as e:
            return jsonify({"error": f"XML conversion error: {str(e)}"})

        # Append conversation: original message, summary, confirmation, result
        conversation.append({"role": "user", "content": original_message or "[Image uploaded]"})
        conversation.append({"role": "assistant", "content": summary_text})
        conversation.append({"role": "user", "content": "[Confirmed]"})
        conversation.append({"role": "assistant", "content": result["raw_response"]})
        session["conversation"] = conversation
        session["current_json"] = bpmn_json

        return jsonify({
            "type": "diagram",
            "bpmn_xml": bpmn_xml,
            "bpmn_json": bpmn_json,
            "process_name": bpmn_json.get("process_name", "Process"),
            "error": None
        })

    # --- Flow D: Revise — pending exists but user sent a new message (not confirm) ---
    if pending and user_message:
        original_message = pending["original_message"]
        combined_message = f"{original_message}\n\nAdditional details/corrections: {user_message}"
        session["pending_confirmation"] = None
        # Fall through to summarize with the combined message
        user_message = combined_message
        image_base64 = None  # Image not re-sent on revise; user can re-upload if needed

    if not user_message and not image_base64:
        return jsonify({"error": "Please provide a message or upload an image"}), 400

    # --- Flow A: Edit existing diagram (no image, diagram exists) ---
    if current_json and not image_base64:
        result = generate_bpmn(
            user_message=user_message,
            conversation_history=conversation,
            current_json=current_json,
            image_base64=None
        )

        if result["error"]:
            return jsonify({"error": result["error"]})

        bpmn_json = result["json"]

        is_valid, errors = validate(bpmn_json)
        if not is_valid:
            return jsonify({"error": "Validation errors: " + "; ".join(errors)})

        try:
            bpmn_xml = json_to_bpmn_xml(bpmn_json)
        except Exception as e:
            return jsonify({"error": f"XML conversion error: {str(e)}"})

        conversation.append({"role": "user", "content": user_message})
        conversation.append({"role": "assistant", "content": result["raw_response"]})
        session["conversation"] = conversation
        session["current_json"] = bpmn_json

        return jsonify({
            "type": "diagram",
            "bpmn_xml": bpmn_xml,
            "bpmn_json": bpmn_json,
            "process_name": bpmn_json.get("process_name", "Process"),
            "error": None
        })

    # --- Flow B: Summarize (new diagram or image) ---
    summary_result = generate_summary(
        user_message=user_message,
        image_base64=image_base64
    )

    if summary_result["error"]:
        return jsonify({"error": summary_result["error"]})

    session["pending_confirmation"] = {
        "original_message": user_message,
        "summary": summary_result["summary"]
    }

    return jsonify({
        "type": "summary",
        "summary": summary_result["summary"],
        "error": None
    })


@app.route("/api/upload", methods=["POST"])
def upload():
    """Handle image file upload, return base64."""
    import base64

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Read and encode
    file_bytes = file.read()
    b64 = base64.b64encode(file_bytes).decode("utf-8")

    return jsonify({"image_base64": b64})


@app.route("/api/export")
def export():
    """Download current diagram as .bpmn file."""
    current_json = session.get("current_json")
    if not current_json:
        return jsonify({"error": "No diagram to export"}), 404

    try:
        bpmn_xml = json_to_bpmn_xml(current_json)
    except Exception as e:
        return jsonify({"error": f"Export error: {str(e)}"}), 500

    process_name = current_json.get("process_name", "diagram")
    filename = process_name.replace(" ", "_").lower() + ".bpmn"

    return Response(
        bpmn_xml,
        mimetype="application/xml",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@app.route("/api/sync", methods=["POST"])
def sync():
    """
    Sync manually edited BPMN XML back to the session.
    Converts XML → intermediate JSON, validates leniently, updates session.
    """
    data = request.get_json()
    if not data or not data.get("bpmn_xml"):
        return jsonify({"error": "No BPMN XML provided"}), 400

    try:
        bpmn_json = bpmn_xml_to_json(data["bpmn_xml"])
    except Exception as e:
        return jsonify({"error": f"Failed to parse BPMN XML: {str(e)}"}), 400

    # Validate leniently — store even if there are warnings
    warnings = []
    is_valid, errors = validate(bpmn_json)
    if not is_valid:
        warnings = errors

    # Update session state
    session["current_json"] = bpmn_json

    # Append synthetic conversation entries so LLM knows about manual edits
    conversation = session.get("conversation", [])
    element_count = len(bpmn_json.get("elements", []))
    flow_count = len(bpmn_json.get("flows", []))
    conversation.append({
        "role": "user",
        "content": "[Diagram was manually edited in the visual editor]"
    })
    conversation.append({
        "role": "assistant",
        "content": (
            f"Noted — the diagram was manually updated. "
            f"It now has {element_count} elements and {flow_count} flows."
        )
    })
    session["conversation"] = conversation

    return jsonify({
        "status": "ok",
        "warnings": warnings,
        "bpmn_json": bpmn_json,
    })


@app.route("/api/reset", methods=["POST"])
def reset():
    """Reset conversation and diagram state."""
    session["conversation"] = []
    session["current_json"] = None
    session["pending_confirmation"] = None
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
