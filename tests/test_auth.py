"""Password-gate tests.

The gate keys off config.APP_PASSWORD, which app.py imports at module load.
These tests monkeypatch the name in the `app` module namespace (where the
before_request handler and the /api/login route actually read it), so they work
regardless of whether APP_PASSWORD was set in the environment.
"""

import app as app_module


def test_gate_disabled_by_default(client, monkeypatch):
    """No APP_PASSWORD → /api/* is open and status reports gate off."""
    monkeypatch.setattr(app_module, "APP_PASSWORD", "")
    r = client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json == {"gate": False, "authed": True}


def test_gate_blocks_api_without_password(client, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "deployment")

    status = client.get("/api/auth/status")
    assert status.json == {"gate": True, "authed": False}

    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 401
    assert r.json["auth_required"] is True


def test_health_stays_open_when_gated(client, monkeypatch):
    """Liveness probe must never be gated (docker/monitoring rely on it)."""
    monkeypatch.setattr(app_module, "APP_PASSWORD", "deployment")
    assert client.get("/api/health").status_code == 200


def test_wrong_password_rejected(client, monkeypatch):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "deployment")
    r = client.post("/api/login", json={"password": "nope"})
    assert r.status_code == 401
    assert r.json["error"] == "Incorrect password"


def test_correct_password_unlocks_api(client, monkeypatch, mock_llm):
    monkeypatch.setattr(app_module, "APP_PASSWORD", "deployment")

    login = client.post("/api/login", json={"password": "deployment"})
    assert login.status_code == 200
    assert login.json["status"] == "ok"

    # Session cookie now carries authed=True → the gated endpoint works.
    mock_llm.queue_summary("A user submits a form and an AI reviews it.")
    r = client.post("/api/chat", json={"message": "users submit forms"})
    assert r.status_code == 200, r.json
    assert r.json["type"] == "summary"
