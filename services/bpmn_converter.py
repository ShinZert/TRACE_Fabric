"""
Converts BPMN JSON intermediate representation to BPMN 2.0 XML
with diagram interchange (DI) coordinates for rendering,
and converts BPMN XML back to intermediate JSON.
"""

import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from services.layout_engine import compute_layout

# BPMN 2.0 namespaces
NS = {
    "bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
    "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
    "dc": "http://www.omg.org/spec/DD/20100524/DC",
    "di": "http://www.omg.org/spec/DD/20100524/DI",
    "xsi": "http://www.w3.org/2001/XMLSchema-instance",
}

# Map JSON element types to BPMN XML tag names
TYPE_MAP = {
    "startEvent": "bpmn:startEvent",
    "endEvent": "bpmn:endEvent",
    "task": "bpmn:task",
    "userTask": "bpmn:userTask",
    "serviceTask": "bpmn:serviceTask",
    "scriptTask": "bpmn:scriptTask",
    "exclusiveGateway": "bpmn:exclusiveGateway",
    "parallelGateway": "bpmn:parallelGateway",
}

# Reverse map: BPMN XML local tag names → intermediate JSON types
REVERSE_TYPE_MAP = {
    "startEvent": "startEvent",
    "endEvent": "endEvent",
    "task": "task",
    "userTask": "userTask",
    "serviceTask": "serviceTask",
    "scriptTask": "scriptTask",
    "exclusiveGateway": "exclusiveGateway",
    "parallelGateway": "parallelGateway",
    # Unsupported modeler elements mapped to closest supported type
    "inclusiveGateway": "exclusiveGateway",
    "complexGateway": "exclusiveGateway",
    "eventBasedGateway": "exclusiveGateway",
    "subProcess": "task",
    "callActivity": "task",
    "sendTask": "serviceTask",
    "receiveTask": "serviceTask",
    "manualTask": "userTask",
    "businessRuleTask": "serviceTask",
    "intermediateThrowEvent": "endEvent",
    "intermediateCatchEvent": "startEvent",
    "boundaryEvent": "startEvent",
}

_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def _register_namespaces():
    """Register namespaces to avoid ns0/ns1 prefixes in output."""
    for prefix, uri in NS.items():
        ET.register_namespace(prefix, uri)


def _build_incoming_outgoing(flows):
    """Build maps of incoming/outgoing flow IDs per element."""
    incoming = {}
    outgoing = {}
    for flow in flows:
        src = flow["from"]
        tgt = flow["to"]
        outgoing.setdefault(src, []).append(flow["id"])
        incoming.setdefault(tgt, []).append(flow["id"])
    return incoming, outgoing


def json_to_bpmn_xml(bpmn_json):
    """
    Convert BPMN JSON to BPMN 2.0 XML string.

    Args:
        bpmn_json: dict with process_name, elements, flows

    Returns:
        str: BPMN 2.0 XML string
    """
    _register_namespaces()

    elements = bpmn_json.get("elements", [])
    flows = bpmn_json.get("flows", [])
    process_name = bpmn_json.get("process_name", "Process")
    process_id = "Process_1"

    # Compute layout
    layout = compute_layout(bpmn_json)
    positions = layout["positions"]
    waypoints = layout["waypoints"]

    incoming_map, outgoing_map = _build_incoming_outgoing(flows)

    # Root: definitions
    definitions = ET.Element(f"{{{NS['bpmn']}}}definitions")
    definitions.set("id", "Definitions_1")
    definitions.set(f"xmlns:xsi", NS["xsi"])
    definitions.set("targetNamespace", "http://bpmn.io/schema/bpmn")
    definitions.set("exporter", "BPMN ProcessPilot")
    definitions.set("exporterVersion", "1.0")

    # Process
    process = ET.SubElement(definitions, f"{{{NS['bpmn']}}}process")
    process.set("id", process_id)
    process.set("name", process_name)
    process.set("isExecutable", "true")

    # Add elements
    for el in elements:
        tag = TYPE_MAP.get(el["type"])
        if not tag:
            continue

        node = ET.SubElement(process, f"{{{NS['bpmn']}}}{el['type']}")
        node.set("id", el["id"])
        if el.get("name"):
            node.set("name", el["name"])

        # Add incoming/outgoing references
        for flow_id in incoming_map.get(el["id"], []):
            inc = ET.SubElement(node, f"{{{NS['bpmn']}}}incoming")
            inc.text = flow_id
        for flow_id in outgoing_map.get(el["id"], []):
            out = ET.SubElement(node, f"{{{NS['bpmn']}}}outgoing")
            out.text = flow_id

    # Add sequence flows
    for flow in flows:
        sf = ET.SubElement(process, f"{{{NS['bpmn']}}}sequenceFlow")
        sf.set("id", flow["id"])
        sf.set("sourceRef", flow["from"])
        sf.set("targetRef", flow["to"])
        if flow.get("name"):
            sf.set("name", flow["name"])

    # Diagram interchange
    diagram = ET.SubElement(definitions, f"{{{NS['bpmndi']}}}BPMNDiagram")
    diagram.set("id", "BPMNDiagram_1")

    plane = ET.SubElement(diagram, f"{{{NS['bpmndi']}}}BPMNPlane")
    plane.set("id", "BPMNPlane_1")
    plane.set("bpmnElement", process_id)

    # Shapes
    for el in elements:
        pos = positions.get(el["id"])
        if not pos:
            continue

        shape = ET.SubElement(plane, f"{{{NS['bpmndi']}}}BPMNShape")
        shape.set("id", f"{el['id']}_di")
        shape.set("bpmnElement", el["id"])

        if el["type"] in ("exclusiveGateway", "parallelGateway"):
            shape.set("isMarkerVisible", "true")

        bounds = ET.SubElement(shape, f"{{{NS['dc']}}}Bounds")
        bounds.set("x", str(pos["x"]))
        bounds.set("y", str(pos["y"]))
        bounds.set("width", str(pos["width"]))
        bounds.set("height", str(pos["height"]))

        # Add label for events and gateways
        if el["type"] in ("startEvent", "endEvent", "exclusiveGateway", "parallelGateway"):
            label = ET.SubElement(shape, f"{{{NS['bpmndi']}}}BPMNLabel")
            label_bounds = ET.SubElement(label, f"{{{NS['dc']}}}Bounds")
            label_bounds.set("x", str(pos["x"] - 10))
            label_bounds.set("y", str(pos["y"] + pos["height"] + 5))
            label_bounds.set("width", str(pos["width"] + 20))
            label_bounds.set("height", "14")

    # Edges
    for flow in flows:
        wps = waypoints.get(flow["id"], [])
        if not wps:
            continue

        edge = ET.SubElement(plane, f"{{{NS['bpmndi']}}}BPMNEdge")
        edge.set("id", f"{flow['id']}_di")
        edge.set("bpmnElement", flow["id"])

        for wp in wps:
            waypoint = ET.SubElement(edge, f"{{{NS['di']}}}waypoint")
            waypoint.set("x", str(wp["x"]))
            waypoint.set("y", str(wp["y"]))

        # Add label for named flows (condition labels)
        if flow.get("name"):
            # Position label at midpoint of the edge
            mid_idx = len(wps) // 2
            mid_wp = wps[mid_idx] if mid_idx < len(wps) else wps[0]
            label = ET.SubElement(edge, f"{{{NS['bpmndi']}}}BPMNLabel")
            label_bounds = ET.SubElement(label, f"{{{NS['dc']}}}Bounds")
            label_bounds.set("x", str(mid_wp["x"] - 20))
            label_bounds.set("y", str(mid_wp["y"] - 20))
            label_bounds.set("width", "60")
            label_bounds.set("height", "14")

    # Serialize to string
    rough_xml = ET.tostring(definitions, encoding="unicode", xml_declaration=False)
    xml_declaration = '<?xml version="1.0" encoding="UTF-8"?>\n'

    # Pretty print
    try:
        parsed = minidom.parseString(rough_xml)
        pretty = parsed.toprettyxml(indent="  ", encoding=None)
        # Remove the minidom xml declaration (we add our own)
        lines = pretty.split("\n")
        if lines[0].startswith("<?xml"):
            lines = lines[1:]
        return xml_declaration + "\n".join(lines)
    except Exception:
        return xml_declaration + rough_xml


def _normalize_id(raw_id, seen_ids):
    """
    Normalize a bpmn-js generated ID to match ^[a-z][a-z0-9_]*$.

    Lowercases, replaces invalid characters with '_', ensures it starts
    with a letter, and deduplicates collisions by appending a suffix.
    """
    normalized = raw_id.lower()
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)

    # Ensure starts with a letter
    if not normalized or not normalized[0].isalpha():
        normalized = "e_" + normalized

    # Strip trailing underscores
    normalized = normalized.rstrip("_")

    # Deduplicate
    base = normalized
    counter = 2
    while normalized in seen_ids:
        normalized = f"{base}_{counter}"
        counter += 1

    seen_ids.add(normalized)
    return normalized


def bpmn_xml_to_json(bpmn_xml):
    """
    Convert BPMN 2.0 XML back to the intermediate JSON format.

    Extracts process structure (elements + flows) from XML.
    DI coordinates are not preserved — layout will be recomputed.

    Args:
        bpmn_xml: str, BPMN 2.0 XML string

    Returns:
        dict with process_name, elements, flows
    """
    bpmn_ns = NS["bpmn"]
    root = ET.fromstring(bpmn_xml)

    # Find <bpmn:process>
    process = root.find(f"{{{bpmn_ns}}}process")
    if process is None:
        raise ValueError("No <bpmn:process> element found in XML")

    process_name = process.get("name", "Process")

    # Track ID mapping: original XML id → normalized id
    seen_ids = set()
    id_map = {}
    elements = []
    flows = []

    # First pass: extract elements and build ID map
    for child in process:
        tag = child.tag
        # Strip namespace to get local name
        if "}" in tag:
            local_name = tag.split("}")[1]
        else:
            local_name = tag

        if local_name == "sequenceFlow":
            continue  # Handle in second pass

        json_type = REVERSE_TYPE_MAP.get(local_name)
        if json_type is None:
            continue  # Skip unsupported elements (e.g., textAnnotation)

        raw_id = child.get("id", "")
        normalized = _normalize_id(raw_id, seen_ids)
        id_map[raw_id] = normalized

        elements.append({
            "id": normalized,
            "type": json_type,
            "name": child.get("name", ""),
        })

    # Second pass: extract sequence flows
    for child in process:
        tag = child.tag
        if "}" in tag:
            local_name = tag.split("}")[1]
        else:
            local_name = tag

        if local_name != "sequenceFlow":
            continue

        raw_id = child.get("id", "")
        source_ref = child.get("sourceRef", "")
        target_ref = child.get("targetRef", "")

        # Skip flows referencing unknown elements
        if source_ref not in id_map or target_ref not in id_map:
            continue

        flow_id = _normalize_id(raw_id, seen_ids)

        flow = {
            "id": flow_id,
            "from": id_map[source_ref],
            "to": id_map[target_ref],
        }
        flow_name = child.get("name", "")
        if flow_name:
            flow["name"] = flow_name

        flows.append(flow)

    return {
        "process_name": process_name,
        "elements": elements,
        "flows": flows,
    }
