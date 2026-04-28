import jsonschema

BPMN_JSON_SCHEMA = {
    "type": "object",
    "required": ["process_name", "elements", "flows"],
    "properties": {
        "process_name": {"type": "string", "minLength": 1},
        "elements": {
            "type": "array",
            "minItems": 2,
            "items": {
                "type": "object",
                "required": ["id", "type", "name"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "type": {
                        "type": "string",
                        "enum": [
                            "startEvent", "endEvent",
                            "task", "userTask", "serviceTask", "scriptTask",
                            "exclusiveGateway", "parallelGateway",
                            "humanSource", "inputOutput",
                            "fixedAIModel", "trainingAIModel",
                            "governanceMechanism", "ui", "decisionPoint",
                            "accept", "reject", "modify", "restart",
                            "finalOutcome"
                        ]
                    },
                    "name": {"type": "string"}
                },
                "additionalProperties": False
            }
        },
        "flows": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "from", "to"],
                "properties": {
                    "id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "name": {"type": "string"}
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


def validate_schema(data):
    """Validate JSON against the BPMN schema. Returns (is_valid, errors)."""
    errors = []
    try:
        jsonschema.validate(instance=data, schema=BPMN_JSON_SCHEMA)
    except jsonschema.ValidationError as e:
        errors.append(f"Schema error: {e.message}")
    except jsonschema.SchemaError as e:
        errors.append(f"Internal schema error: {e.message}")
    return len(errors) == 0, errors


END_TYPES = {"endEvent", "finalOutcome"}


def validate_semantics(data):
    """Semantic validation for BPMN correctness. Returns (is_valid, errors)."""
    errors = []
    elements = data.get("elements", [])
    flows = data.get("flows", [])

    element_ids = {el["id"] for el in elements}
    element_types = {el["id"]: el["type"] for el in elements}

    # Exactly one startEvent
    start_events = [el for el in elements if el["type"] == "startEvent"]
    if len(start_events) == 0:
        errors.append("Process must have exactly one startEvent.")
    elif len(start_events) > 1:
        errors.append(f"Process has {len(start_events)} startEvents; exactly 1 is required.")

    # At least one terminal node (endEvent or Fabric finalOutcome)
    end_events = [el for el in elements if el["type"] in END_TYPES]
    if len(end_events) == 0:
        errors.append("Process must have at least one endEvent or finalOutcome.")

    # Unique element IDs
    seen_ids = set()
    for el in elements:
        if el["id"] in seen_ids:
            errors.append(f"Duplicate element ID: '{el['id']}'.")
        seen_ids.add(el["id"])

    # Unique flow IDs
    seen_flow_ids = set()
    for flow in flows:
        if flow["id"] in seen_flow_ids:
            errors.append(f"Duplicate flow ID: '{flow['id']}'.")
        seen_flow_ids.add(flow["id"])

    # All flow references point to existing elements
    for flow in flows:
        if flow["from"] not in element_ids:
            errors.append(f"Flow '{flow['id']}' references unknown source '{flow['from']}'.")
        if flow["to"] not in element_ids:
            errors.append(f"Flow '{flow['id']}' references unknown target '{flow['to']}'.")

    # No orphan nodes (every non-start element must have incoming, every non-end must have outgoing)
    incoming = {eid: 0 for eid in element_ids}
    outgoing = {eid: 0 for eid in element_ids}
    for flow in flows:
        if flow["from"] in incoming:
            outgoing[flow["from"]] += 1
        if flow["to"] in incoming:
            incoming[flow["to"]] += 1

    for el in elements:
        eid = el["id"]
        etype = el["type"]
        if etype != "startEvent" and incoming.get(eid, 0) == 0:
            errors.append(f"Element '{eid}' has no incoming flows (orphan).")
        if etype not in END_TYPES and outgoing.get(eid, 0) == 0:
            errors.append(f"Element '{eid}' has no outgoing flows (dead end).")

    # startEvent should not have incoming flows
    for el in start_events:
        if incoming.get(el["id"], 0) > 0:
            errors.append(f"startEvent '{el['id']}' should not have incoming flows.")

    # Terminal nodes should not have outgoing flows
    for el in end_events:
        if outgoing.get(el["id"], 0) > 0:
            errors.append(f"Terminal node '{el['id']}' should not have outgoing flows.")

    return len(errors) == 0, errors
