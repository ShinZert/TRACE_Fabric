"""Flask route tests with mocked OpenAI — covers the four /api/chat flows."""

import json


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"


# --- /api/chat: four flows -------------------------------------------------

def test_chat_flow_B_summarize(client, mock_llm):
    """Fresh request with no current_trace → summary returned, pending stored."""
    mock_llm.queue_summary("This process accepts a form, an AI reviews, a human approves.")
    r = client.post("/api/chat", json={"message": "users submit forms for review"})
    assert r.status_code == 200, r.json
    assert r.json["type"] == "summary"
    assert r.json["summary"]


def test_chat_flow_C_confirm(client, mock_llm, valid_trace):
    """Summary + confirm=true → trace generated from stored message."""
    mock_llm.queue_summary("Summary of the process.")
    r1 = client.post("/api/chat", json={"message": "describe a workflow"})
    assert r1.status_code == 200

    mock_llm.queue_trace(valid_trace)
    r2 = client.post("/api/chat", json={"confirm": True})
    assert r2.status_code == 200, r2.json
    assert r2.json["type"] == "diagram"
    assert r2.json["trace"]["process_name"] == valid_trace["process_name"]


def test_chat_flow_A_edit_injects_context(client, mock_llm, valid_trace):
    """current_trace exists → edit context appears in the LLM prompt."""
    r0 = client.post("/api/sync", json={"trace": valid_trace})
    assert r0.status_code == 200

    mock_llm.queue_trace(valid_trace)
    r = client.post("/api/chat", json={"message": "rename the start to 'Begin'"})
    assert r.status_code == 200, r.json
    assert r.json["type"] == "diagram"

    last_user_msg = mock_llm.calls[-1]["messages"][-1]["content"]
    assert valid_trace["process_name"] in last_user_msg
    assert "User request:" in last_user_msg


def test_chat_flow_D_revise(client, mock_llm):
    """New user message after summary → combined message re-summarized."""
    mock_llm.queue_summary("First summary.")
    client.post("/api/chat", json={"message": "original description"})

    mock_llm.queue_summary("Second summary with corrections.")
    r = client.post("/api/chat", json={"message": "also add a governance step"})
    assert r.status_code == 200
    assert r.json["type"] == "summary"

    last_user = mock_llm.calls[-1]["messages"][-1]["content"]
    assert "original description" in last_user
    assert "governance step" in last_user


# --- /api/sync -------------------------------------------------------------

def test_sync_valid_trace(client, valid_trace):
    r = client.post("/api/sync", json={"trace": valid_trace})
    assert r.status_code == 200
    assert r.json["status"] == "ok"


def test_sync_schema_invalid_rejected(client, valid_trace):
    bad = dict(valid_trace)
    bad["elements"] = [{"id": "Bad-Id", "type": "startEvent", "name": "X"}]
    r = client.post("/api/sync", json={"trace": bad})
    assert r.status_code == 400
    assert r.json["status"] == "rejected"


def test_sync_semantic_warning_still_passes(client):
    """Schema-valid but semantically imperfect traces sync with warnings."""
    # No startEvent — schema-valid, semantically wrong.
    bad = {
        "process_name": "x",
        "elements": [
            {"id": "a", "type": "userTask", "name": "A"},
            {"id": "b", "type": "endEvent", "name": "B"},
        ],
        "flows": [{"id": "f", "from": "a", "to": "b"}],
    }
    r = client.post("/api/sync", json={"trace": bad})
    assert r.status_code == 200
    assert r.json["warnings"]


def test_sync_missing_trace_returns_400(client):
    r = client.post("/api/sync", json={})
    assert r.status_code == 400


# --- /api/export -----------------------------------------------------------

def test_export_404_when_no_trace(client):
    r = client.get("/api/export")
    assert r.status_code == 404


def test_export_returns_json_after_sync(client, valid_trace):
    client.post("/api/sync", json={"trace": valid_trace})
    r = client.get("/api/export")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/json")
    body = json.loads(r.data)
    assert body["process_name"] == valid_trace["process_name"]


# --- /api/reset ------------------------------------------------------------

def test_reset_clears_trace(client, valid_trace):
    client.post("/api/sync", json={"trace": valid_trace})
    r = client.post("/api/reset")
    assert r.status_code == 200
    assert client.get("/api/export").status_code == 404
