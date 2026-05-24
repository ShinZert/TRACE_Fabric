"""
Append-only JSON-lines event log for live monitoring. One line per event.
Rotates at 10 MB × 10 files. Default path is ./data/weaver.jsonl; override
via LOG_DIR env var (the docker-compose service mounts the host's ./data
directory at /data inside the container).
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import has_request_context, session

LOG_DIR = Path(os.environ.get("LOG_DIR", "./data"))
LOG_FILE = LOG_DIR / "weaver.jsonl"

_logger = logging.getLogger("weaver.events")
_logger.setLevel(logging.INFO)
_logger.propagate = False

if not _logger.handlers:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)


def session_anon_id():
    """
    Stable per-session anonymous ID. A UUID is lazily stored in the Flask
    session the first time logging happens, and the SHA-256 prefix is what
    gets written to logs — so the on-disk ID can't be reversed to a session
    cookie. Returns 'no-session' if called outside a request context.
    """
    if not has_request_context():
        return "no-session"
    sid = session.get("_telemetry_sid")
    if not sid:
        sid = uuid.uuid4().hex
        session["_telemetry_sid"] = sid
    return hashlib.sha256(sid.encode()).hexdigest()[:12]


def log_event(name, **fields):
    """
    Append one JSON line to the event log. Never raises — a logging failure
    must not break a live request.
    """
    try:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": name,
            "session": session_anon_id(),
            **fields,
        }
        _logger.info(json.dumps(record, default=str, ensure_ascii=False))
    except Exception:
        logging.getLogger(__name__).exception("event_logger failed")
