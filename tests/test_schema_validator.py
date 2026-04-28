"""Schema and semantic validation — pure functions, no external deps."""

from copy import deepcopy

from services.schema_validator import validate_schema, validate_semantics


def test_valid_trace_passes_both(valid_trace):
    schema_ok, schema_errs = validate_schema(valid_trace)
    sem_ok, sem_errs = validate_semantics(valid_trace)
    assert schema_ok, schema_errs
    assert sem_ok, sem_errs


def test_missing_process_name_fails_schema(valid_trace):
    bad = deepcopy(valid_trace)
    del bad["process_name"]
    ok, errs = validate_schema(bad)
    assert not ok
    assert any("process_name" in e for e in errs)


def test_invalid_id_pattern_fails_schema(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][0]["id"] = "Start"  # capital letters not allowed
    ok, _ = validate_schema(bad)
    assert not ok


def test_unknown_element_type_fails_schema(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][1]["type"] = "definitelyNotAType"
    ok, _ = validate_schema(bad)
    assert not ok


def test_no_start_event_fails_semantics(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][0]["type"] = "userTask"
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("startEvent" in e for e in errs)


def test_two_start_events_fails_semantics(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][1]["type"] = "startEvent"
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("startEvent" in e for e in errs)


def test_no_terminal_node_fails_semantics(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][2]["type"] = "userTask"
    ok, _ = validate_semantics(bad)
    assert not ok


def test_finalOutcome_counts_as_terminal(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][2]["type"] = "finalOutcome"
    ok, errs = validate_semantics(bad)
    assert ok, errs


def test_duplicate_element_id_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "start", "type": "userTask", "name": "Dupe"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("Duplicate" in e for e in errs)


def test_flow_to_unknown_element_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["flows"][1]["to"] = "ghost"
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("ghost" in e for e in errs)


def test_orphan_node_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "lonely", "type": "userTask", "name": "Lonely"})
    bad["flows"].append({"id": "f3", "from": "lonely", "to": "end"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("incoming" in e.lower() or "orphan" in e.lower() for e in errs)


def test_start_event_with_incoming_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["flows"].append({"id": "f3", "from": "task1", "to": "start"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("startEvent" in e for e in errs)
