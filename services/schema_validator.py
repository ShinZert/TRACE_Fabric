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
                    "name": {"type": "string"},
                    "from_side": {"type": "string", "enum": ["top", "right", "bottom", "left"]},
                    "to_side": {"type": "string", "enum": ["top", "right", "bottom", "left"]}
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


TERMINAL_TYPES = {"finalOutcome"}


def validate_semantics(data):
    """Semantic validation for Fabric trace correctness. Returns (is_valid, errors).

    Fabric does not use a dedicated start-event marker. Instead, the entry
    point is identified structurally as the single element with no incoming
    flows. This keeps the ontology focused on AI-workflow primitives
    (humanSource, fixedAIModel, finalOutcome, …).
    """
    errors = []
    elements = data.get("elements", [])
    flows = data.get("flows", [])

    element_ids = {el["id"] for el in elements}

    # At least one terminal (finalOutcome) — Fabric's only terminal type.
    terminals = [el for el in elements if el["type"] in TERMINAL_TYPES]
    if len(terminals) == 0:
        errors.append("Process must have at least one finalOutcome.")

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

    # Per-node connectivity counts
    incoming = {eid: 0 for eid in element_ids}
    outgoing = {eid: 0 for eid in element_ids}
    for flow in flows:
        if flow["from"] in incoming:
            outgoing[flow["from"]] += 1
        if flow["to"] in incoming:
            incoming[flow["to"]] += 1

    # Exactly one entry point — the element with no incoming flows.
    entry_ids = [eid for eid in element_ids if incoming.get(eid, 0) == 0]
    if len(entry_ids) == 0 and elements:
        errors.append("Process has no entry point — every element has an incoming flow (cycle).")
    elif len(entry_ids) > 1:
        joined = ", ".join(sorted(entry_ids))
        errors.append(f"Process has multiple entry points ({joined}); exactly 1 is required.")

    # Non-terminal elements must have ≥1 outgoing flow
    for el in elements:
        if el["type"] not in TERMINAL_TYPES and outgoing.get(el["id"], 0) == 0:
            errors.append(f"Element '{el['id']}' has no outgoing flows (dead end).")

    # Terminal nodes must not have outgoing flows
    for el in terminals:
        if outgoing.get(el["id"], 0) > 0:
            errors.append(f"Terminal node '{el['id']}' should not have outgoing flows.")

    return len(errors) == 0, errors
