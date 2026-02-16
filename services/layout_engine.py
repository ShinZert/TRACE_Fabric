"""
Auto-layout engine for BPMN diagrams.

Uses topological sort for column assignment, then row assignment
to handle gateway branching. Produces pixel coordinates for shapes
and waypoints for edges.
"""

from graphlib import TopologicalSorter, CycleError
from collections import defaultdict

# Dimension constants
EVENT_SIZE = 36
TASK_WIDTH = 100
TASK_HEIGHT = 80
GATEWAY_SIZE = 50

# Spacing
HORIZONTAL_GAP = 80
VERTICAL_GAP = 60
START_X = 50
START_Y = 50


def _get_element_dimensions(el_type):
    """Return (width, height) for an element type."""
    if el_type in ("startEvent", "endEvent"):
        return EVENT_SIZE, EVENT_SIZE
    elif el_type in ("exclusiveGateway", "parallelGateway"):
        return GATEWAY_SIZE, GATEWAY_SIZE
    else:
        return TASK_WIDTH, TASK_HEIGHT


def _build_adjacency(elements, flows):
    """Build adjacency lists from flows."""
    successors = defaultdict(list)
    predecessors = defaultdict(list)
    for flow in flows:
        src, tgt = flow["from"], flow["to"]
        successors[src].append(tgt)
        predecessors[tgt].append(src)
    return successors, predecessors


def _assign_columns(elements, flows):
    """
    Assign each element to a column (layer) using topological sort.
    Each element's column = max(predecessor columns) + 1.
    """
    element_ids = [el["id"] for el in elements]
    successors, predecessors = _build_adjacency(elements, flows)

    # Build dependency graph for TopologicalSorter
    graph = {}
    for eid in element_ids:
        graph[eid] = set(predecessors[eid])

    try:
        sorter = TopologicalSorter(graph)
        topo_order = list(sorter.static_order())
    except CycleError:
        # Fallback: use element order
        topo_order = element_ids

    # Assign columns based on longest path from any root
    columns = {}
    for eid in topo_order:
        preds = predecessors[eid]
        if not preds:
            columns[eid] = 0
        else:
            columns[eid] = max(columns.get(p, 0) for p in preds) + 1

    return columns


def _assign_rows(elements, flows, columns):
    """
    Assign rows to elements within each column.
    Elements in the same column are stacked vertically.
    Gateway branches are spread across multiple rows.
    """
    element_map = {el["id"]: el for el in elements}
    successors, predecessors = _build_adjacency(elements, flows)

    # Group elements by column
    col_groups = defaultdict(list)
    for el in elements:
        col_groups[columns[el["id"]]].append(el["id"])

    # Sort columns
    max_col = max(columns.values()) if columns else 0

    rows = {}
    # Process column by column
    for col in range(max_col + 1):
        group = col_groups[col]
        if not group:
            continue

        if col == 0:
            # First column: stack sequentially
            for i, eid in enumerate(group):
                rows[eid] = i
        else:
            # For each element, try to align with its predecessor's row
            assigned = {}
            unassigned = []

            for eid in group:
                preds = predecessors[eid]
                pred_rows = [rows[p] for p in preds if p in rows]
                if pred_rows:
                    # Use mean of predecessor rows for alignment
                    assigned[eid] = sum(pred_rows) / len(pred_rows)
                else:
                    unassigned.append(eid)

            # Sort assigned by their target row
            sorted_assigned = sorted(assigned.items(), key=lambda x: x[1])

            # Assign integer rows avoiding collisions
            used_rows = set()
            for eid, target_row in sorted_assigned:
                row = round(target_row)
                while row in used_rows:
                    row += 1
                rows[eid] = row
                used_rows.add(row)

            # Place unassigned elements
            next_row = max(used_rows) + 1 if used_rows else 0
            for eid in unassigned:
                rows[eid] = next_row
                used_rows.add(next_row)
                next_row += 1

    # Re-center: for gateways, spread successors symmetrically
    for el in elements:
        if el["type"] in ("exclusiveGateway", "parallelGateway"):
            gw_id = el["id"]
            succs = successors[gw_id]
            # Only spread if multiple successors are in the same column
            succ_cols = defaultdict(list)
            for s in succs:
                succ_cols[columns[s]].append(s)
            for col_val, col_succs in succ_cols.items():
                if len(col_succs) > 1:
                    gw_row = rows[gw_id]
                    spread = len(col_succs)
                    start_row = gw_row - (spread - 1) / 2
                    for i, s in enumerate(col_succs):
                        rows[s] = start_row + i

    # Normalize rows to be 0-based integers
    all_rows = sorted(set(rows.values()))
    row_map = {r: i for i, r in enumerate(all_rows)}
    for eid in rows:
        rows[eid] = row_map[rows[eid]]

    return rows


def _compute_coordinates(elements, columns, rows):
    """Convert column/row assignments to pixel coordinates."""
    element_map = {el["id"]: el for el in elements}
    positions = {}

    # Find max dimensions per column for alignment
    col_widths = defaultdict(int)
    for el in elements:
        w, h = _get_element_dimensions(el["type"])
        col = columns[el["id"]]
        col_widths[col] = max(col_widths[col], w)

    # Compute cumulative X offsets
    col_x = {}
    x = START_X
    for col in sorted(col_widths.keys()):
        col_x[col] = x
        x += col_widths[col] + HORIZONTAL_GAP

    for el in elements:
        eid = el["id"]
        w, h = _get_element_dimensions(el["type"])
        col = columns[eid]
        row = rows[eid]

        # Center element within its column width
        col_w = col_widths[col]
        x_offset = (col_w - w) / 2

        px = col_x[col] + x_offset
        py = START_Y + row * (TASK_HEIGHT + VERTICAL_GAP)

        # Vertically center smaller elements relative to task height
        py += (TASK_HEIGHT - h) / 2

        positions[eid] = {
            "x": round(px),
            "y": round(py),
            "width": w,
            "height": h
        }

    return positions


def _compute_waypoints(flows, positions):
    """Generate waypoints for each flow (edge routing)."""
    waypoints = {}

    for flow in flows:
        src_pos = positions.get(flow["from"])
        tgt_pos = positions.get(flow["to"])
        if not src_pos or not tgt_pos:
            continue

        # Source: right center
        src_x = src_pos["x"] + src_pos["width"]
        src_y = src_pos["y"] + src_pos["height"] / 2

        # Target: left center
        tgt_x = tgt_pos["x"]
        tgt_y = tgt_pos["y"] + tgt_pos["height"] / 2

        if abs(src_y - tgt_y) < 5:
            # Same row: straight line
            points = [
                {"x": round(src_x), "y": round(src_y)},
                {"x": round(tgt_x), "y": round(tgt_y)}
            ]
        else:
            # Different rows: L-shaped or Z-shaped routing
            mid_x = round((src_x + tgt_x) / 2)
            points = [
                {"x": round(src_x), "y": round(src_y)},
                {"x": mid_x, "y": round(src_y)},
                {"x": mid_x, "y": round(tgt_y)},
                {"x": round(tgt_x), "y": round(tgt_y)}
            ]

        waypoints[flow["id"]] = points

    return waypoints


def compute_layout(bpmn_json):
    """
    Main entry point. Takes BPMN JSON, returns layout data:
    {
        "positions": { element_id: {x, y, width, height} },
        "waypoints": { flow_id: [{x, y}, ...] }
    }
    """
    elements = bpmn_json.get("elements", [])
    flows = bpmn_json.get("flows", [])

    if not elements:
        return {"positions": {}, "waypoints": {}}

    columns = _assign_columns(elements, flows)
    rows = _assign_rows(elements, flows, columns)
    positions = _compute_coordinates(elements, columns, rows)
    waypoints = _compute_waypoints(flows, positions)

    return {
        "positions": positions,
        "waypoints": waypoints
    }
