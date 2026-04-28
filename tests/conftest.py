"""
Shared pytest fixtures and environment setup for Weaver tests.

Importing app/config has side effects: config.py calls sys.exit() if
SECRET_KEY is not set, and services/llm_service.py constructs an OpenAI
client at import time. Setting safe defaults here, BEFORE any project
imports below, prevents test collection from blowing up.
"""

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-pytest-only")
os.environ.setdefault("OPENAI_API_KEY", "test-key-mocked-in-unit-tests")
os.environ.setdefault("FLASK_DEBUG", "1")

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def valid_trace():
    """Minimal Fabric trace that passes both schema and semantic validation.

    Fabric has no start-event type — the entry is identified structurally
    as the only element with no incoming flow (here, `human`).
    """
    return {
        "process_name": "Test Process",
        "elements": [
            {"id": "human", "type": "humanSource", "name": "Operator"},
            {"id": "model", "type": "fixedAIModel", "name": "Classifier"},
            {"id": "outcome", "type": "finalOutcome", "name": "Recorded"},
        ],
        "flows": [
            {"id": "f1", "from": "human", "to": "model"},
            {"id": "f2", "from": "model", "to": "outcome"},
        ],
    }


@pytest.fixture
def app():
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    return flask_app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        yield c


def _fake_openai_response(content):
    """Mock object matching the shape returned by client.chat.completions.create()."""
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content, refusal=None),
            finish_reason="stop",
        )]
    )


@pytest.fixture
def mock_llm(monkeypatch):
    """
    Replace the OpenAI client with a queue-based mock.

    Tests must explicitly queue every response they expect — empty queue raises
    so missing setup is loud. Queue order = call order: a /api/chat that does
    summarize-then-confirm consumes one queued summary then one queued trace.

    Inspect mock_llm.calls (list of {"messages": [...]}) to assert what was
    sent to the LLM (e.g., that edit context was injected).
    """
    queue = []
    calls = []

    def create(**kwargs):
        calls.append({"messages": kwargs.get("messages", [])})
        if not queue:
            raise RuntimeError(
                "mock_llm has no queued response — call queue_trace/queue_summary "
                "before triggering the LLM call."
            )
        return _fake_openai_response(queue.pop(0))

    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = create
    monkeypatch.setattr("services.llm_service.client", fake_client)

    return SimpleNamespace(
        queue_trace=lambda trace: queue.append(json.dumps(trace)),
        queue_summary=lambda text: queue.append(text),
        queue_raw=lambda raw: queue.append(raw),
        calls=calls,
    )
