"""
Shared metric primitives for offline evals and live monitoring. Pure functions.

Four metric groups:
- validity_metrics: parsing + schema + semantic checks
- cost_metrics: token counts and latency (no USD — convert at analysis time)
- structural_metrics: element/flow counts, branching, path length, cycle flag
- reference_metrics: comparison against a gold-standard trace (eval-only)

generation_metrics() bundles the first three (used live + offline).
reference_metrics() is offline-only.
"""

from collections import Counter

from services.schema_validator import validate_schema, validate_semantics


def _adjacency(trace):
    out_edges = {el["id"]: [] for el in trace.get("elements", [])}
    for f in trace.get("flows", []):
        if f["from"] in out_edges and f["to"] in out_edges:
            out_edges[f["from"]].append(f["to"])
    return out_edges


def _entry_id(trace):
    incoming = {f["to"] for f in trace.get("flows", [])}
    for el in trace.get("elements", []):
        if el["id"] not in incoming:
            return el["id"]
    return None


def _has_cycle(out_edges):
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in out_edges}

    def dfs(n):
        stack = [(n, iter(out_edges.get(n, [])))]
        color[n] = GRAY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                continue
            if nxt not in color:
                continue
            if color[nxt] == GRAY:
                return True
            if color[nxt] == WHITE:
                color[nxt] = GRAY
                stack.append((nxt, iter(out_edges.get(nxt, []))))
        return False

    for n in out_edges:
        if color[n] == WHITE and dfs(n):
            return True
    return False


def _max_path_length(out_edges, entry):
    # Longest simple path from entry to any terminal. Caller guarantees no cycles.
    if entry is None:
        return None
    best = 0
    stack = [(entry, 0)]
    while stack:
        node, depth = stack.pop()
        children = out_edges.get(node, [])
        if not children and depth > best:
            best = depth
        for c in children:
            stack.append((c, depth + 1))
    return best


def _branching_factor(trace):
    decision_ids = {
        el["id"] for el in trace.get("elements", []) if el["type"] == "decisionPoint"
    }
    if not decision_ids:
        return 0.0
    out_counts = Counter()
    for f in trace.get("flows", []):
        if f["from"] in decision_ids:
            out_counts[f["from"]] += 1
    total = sum(out_counts.get(d, 0) for d in decision_ids)
    return round(total / len(decision_ids), 3)


def structural_metrics(trace):
    """Structural properties of a trace JSON. None values where undefined."""
    if not trace or not isinstance(trace, dict):
        return {
            "num_elements": 0,
            "num_flows": 0,
            "element_type_counts": {},
            "num_final_outcomes": 0,
            "branching_factor": 0.0,
            "max_path_length": None,
            "has_cycle": False,
        }
    type_counts = Counter(el["type"] for el in trace.get("elements", []))
    out_edges = _adjacency(trace)
    cycle = _has_cycle(out_edges)
    return {
        "num_elements": len(trace.get("elements", [])),
        "num_flows": len(trace.get("flows", [])),
        "element_type_counts": dict(type_counts),
        "num_final_outcomes": type_counts.get("finalOutcome", 0),
        "branching_factor": _branching_factor(trace),
        "max_path_length": None if cycle else _max_path_length(out_edges, _entry_id(trace)),
        "has_cycle": cycle,
    }


def validity_metrics(trace, parse_error=None):
    """Run schema + semantic validation. Trace may be None when parse failed."""
    if trace is None:
        return {
            "parsed_ok": False,
            "schema_pass": False,
            "semantic_pass": False,
            "errors": [parse_error or "Failed to parse JSON"],
        }
    schema_ok, schema_errs = validate_schema(trace)
    if not schema_ok:
        return {
            "parsed_ok": True,
            "schema_pass": False,
            "semantic_pass": False,
            "errors": schema_errs,
        }
    sem_ok, sem_errs = validate_semantics(trace)
    return {
        "parsed_ok": True,
        "schema_pass": True,
        "semantic_pass": sem_ok,
        "errors": sem_errs,
    }


def cost_metrics(usage, latency_ms):
    """Raw token usage + latency. `usage` is the OpenAI usage object or a dict."""
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "latency_ms": latency_ms,
        }
    pt = (
        getattr(usage, "prompt_tokens", None)
        if not isinstance(usage, dict)
        else usage.get("prompt_tokens", 0)
    ) or 0
    ct = (
        getattr(usage, "completion_tokens", None)
        if not isinstance(usage, dict)
        else usage.get("completion_tokens", 0)
    ) or 0
    return {
        "prompt_tokens": pt,
        "completion_tokens": ct,
        "total_tokens": pt + ct,
        "latency_ms": latency_ms,
    }


def generation_metrics(trace, usage, latency_ms, parse_error=None):
    """All non-reference metrics for a single LLM generation. Trace may be None."""
    return {
        **validity_metrics(trace, parse_error=parse_error),
        **cost_metrics(usage, latency_ms),
        **structural_metrics(trace),
    }


def _multiset_jaccard(a, b):
    intersection = sum((a & b).values())
    union = sum((a | b).values())
    return intersection / union if union else 1.0


def _name_tokens(s):
    return {tok for tok in "".join(c.lower() if c.isalnum() else " " for c in s).split() if tok}


def _token_overlap(a, b):
    sa, sb = _name_tokens(a), _name_tokens(b)
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def reference_metrics(predicted, gold, name_match_threshold=0.5):
    """Compare predicted trace to a gold-standard trace from workflows.json."""
    gold_elements = gold.get("elements", [])
    gold_flows = gold.get("flows", [])

    if predicted is None or not isinstance(predicted, dict):
        return {
            "element_count_delta": -len(gold_elements),
            "flow_count_delta": -len(gold_flows),
            "element_type_jaccard_multiset": 0.0,
            "gold_type_coverage": 0.0,
            "final_outcome_recall": 0.0,
        }

    pred_elements = predicted.get("elements", [])
    pred_flows = predicted.get("flows", [])

    pred_types = Counter(el["type"] for el in pred_elements)
    gold_types = Counter(el["type"] for el in gold_elements)

    gold_type_set = set(gold_types.keys())
    pred_type_set = set(pred_types.keys())
    coverage = (
        len(gold_type_set & pred_type_set) / len(gold_type_set)
        if gold_type_set
        else 1.0
    )

    pred_final_names = [el["name"] for el in pred_elements if el["type"] == "finalOutcome"]
    gold_final_names = [el["name"] for el in gold_elements if el["type"] == "finalOutcome"]
    matched = sum(
        1
        for g in gold_final_names
        if any(_token_overlap(g, p) >= name_match_threshold for p in pred_final_names)
    )
    final_recall = matched / len(gold_final_names) if gold_final_names else 1.0

    return {
        "element_count_delta": len(pred_elements) - len(gold_elements),
        "flow_count_delta": len(pred_flows) - len(gold_flows),
        "element_type_jaccard_multiset": round(_multiset_jaccard(pred_types, gold_types), 4),
        "gold_type_coverage": round(coverage, 4),
        "final_outcome_recall": round(final_recall, 4),
    }
