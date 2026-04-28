"""Tests for pure helpers in services.llm_service."""

from services.llm_service import _extract_json, _build_messages


# --- _extract_json ---------------------------------------------------------

def test_extract_raw_json():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_fenced_json_with_lang():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_fenced_json_no_lang():
    assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}


def test_extract_embedded_json():
    text = 'Here is the trace: {"a": 1, "b": [2, 3]} hope this helps!'
    assert _extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_invalid_returns_none():
    assert _extract_json("definitely not json") is None


def test_extract_handles_nested_braces():
    text = 'prefix {"a": {"b": {"c": 1}}} suffix'
    assert _extract_json(text) == {"a": {"b": {"c": 1}}}


# --- _build_messages -------------------------------------------------------

def test_build_messages_starts_with_system_prompt():
    msgs = _build_messages(conversation_history=[], user_message="hi")
    assert msgs[0]["role"] == "system"
    assert len(msgs[0]["content"]) > 0


def test_build_messages_ends_with_user():
    msgs = _build_messages(conversation_history=[], user_message="hi")
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"] == "hi"


def test_build_messages_includes_few_shot_examples():
    msgs = _build_messages(conversation_history=[], user_message="hi")
    # system + ≥1 few-shot pair + user
    assert len(msgs) >= 3


def test_build_messages_truncates_history():
    from config import MAX_CONVERSATION_TURNS
    history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg{i}"}
        for i in range(40)
    ]
    msgs = _build_messages(conversation_history=history, user_message="latest")
    history_msgs = [
        m for m in msgs
        if isinstance(m.get("content"), str) and m["content"].startswith("msg")
    ]
    assert len(history_msgs) == MAX_CONVERSATION_TURNS * 2
    assert history_msgs[-1]["content"] == "msg39"


def test_build_messages_injects_edit_context_when_trace_present(valid_trace):
    msgs = _build_messages(
        conversation_history=[],
        user_message="add a step",
        current_trace=valid_trace,
    )
    last = msgs[-1]["content"]
    assert "User request: add a step" in last
    assert "Test Process" in last  # process_name embedded via EDIT_CONTEXT_TEMPLATE


def test_build_messages_skips_edit_context_when_image_present(valid_trace):
    msgs = _build_messages(
        conversation_history=[],
        user_message="hi",
        current_trace=valid_trace,
        image_base64="ZmFrZQ==",
        image_mime="image/png",
    )
    last = msgs[-1]
    assert isinstance(last["content"], list)
    text_part = next(p for p in last["content"] if p["type"] == "text")
    assert "Test Process" not in text_part["text"]
