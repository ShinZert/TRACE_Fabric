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
    bad["elements"][0]["id"] = "Operator"  # capital letters not allowed
    ok, _ = validate_schema(bad)
    assert not ok


def test_unknown_element_type_fails_schema(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][1]["type"] = "definitelyNotAType"
    ok, _ = validate_schema(bad)
    assert not ok


def test_startEvent_no_longer_in_schema(valid_trace):
    """Boundary events were removed from the Fabric ontology."""
    bad = deepcopy(valid_trace)
    bad["elements"][0]["type"] = "startEvent"
    ok, _ = validate_schema(bad)
    assert not ok


def test_endEvent_no_longer_in_schema(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"][2]["type"] = "endEvent"
    ok, _ = validate_schema(bad)
    assert not ok


def test_missing_finalOutcome_fails_semantics(valid_trace):
    """Trace must have at least one finalOutcome."""
    bad = deepcopy(valid_trace)
    bad["elements"][2]["type"] = "userTask"
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("finalOutcome" in e for e in errs)


def test_multiple_entry_points_fails_semantics(valid_trace):
    """Two elements with no incoming flow → ambiguous start."""
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "loose", "type": "humanSource", "name": "Loose"})
    bad["flows"].append({"id": "f3", "from": "loose", "to": "model"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("entry" in e.lower() for e in errs)


def test_no_entry_point_fails_semantics(valid_trace):
    """Pure cycle — every node has incoming, so there's no entry."""
    bad = deepcopy(valid_trace)
    bad["flows"].append({"id": "f3", "from": "outcome", "to": "human"})
    # outcome is finalOutcome with outgoing → terminal_has_outgoing also fires,
    # but the entry-point error must be among the reported errors.
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("entry" in e.lower() or "cycle" in e.lower() for e in errs)


def test_duplicate_element_id_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "human", "type": "userTask", "name": "Dupe"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("Duplicate" in e for e in errs)


def test_flow_to_unknown_element_fails(valid_trace):
    bad = deepcopy(valid_trace)
    bad["flows"][1]["to"] = "ghost"
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("ghost" in e for e in errs)


def test_dead_end_fails(valid_trace):
    """Non-terminal element with no outgoing flow."""
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "stranded", "type": "userTask", "name": "Stranded"})
    bad["flows"].append({"id": "f3", "from": "human", "to": "stranded"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("dead end" in e.lower() or "outgoing" in e.lower() for e in errs)


def test_finalOutcome_with_outgoing_fails(valid_trace):
    """Terminal nodes must not have outgoing flows."""
    bad = deepcopy(valid_trace)
    bad["elements"].append({"id": "after", "type": "userTask", "name": "After"})
    bad["flows"].append({"id": "f3", "from": "outcome", "to": "after"})
    # Re-route `after` to a new terminal so the only error is the bad outgoing.
    bad["elements"].append({"id": "outcome2", "type": "finalOutcome", "name": "Done"})
    bad["flows"].append({"id": "f4", "from": "after", "to": "outcome2"})
    ok, errs = validate_semantics(bad)
    assert not ok
    assert any("outgoing" in e.lower() for e in errs)
