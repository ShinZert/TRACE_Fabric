"""
Shared metric primitives for offline evals and live monitoring. Pure functions.

Four metric groups:
- validity_metrics: parsing + schema + semantic checks
- cost_metrics: token counts and latency (no USD — convert at analysis time)
- structural_metrics: element/flow counts, branching, path length, cycle flag
- reference_metrics: fidelity vs a gold-standard trace (eval-only)

generation_metrics() bundles the first three (used live + offline).
reference_metrics() is offline-only.
"""

import math
import threading
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


# --- Fidelity (reference) metrics ------------------------------------------
#
# Fidelity decomposes into two axes that are reported SEPARATELY and never
# aggregated into a single score — there is no principled weighting across
# them, and a single mean would bury the shape-vs-meaning attribution.
#
#   Shape   (name-agnostic): structural_similarity, type_distribution_similarity
#   Meaning (label-aware):   name_semantic_similarity, name_type_semantic_similarity
#
# Method follows the multi-dimensional similarity suite of Matei et al. (2026):
# ratio-based topology stats + degree-sequence correlation (structural),
# Jensen-Shannon divergence over type frequencies (type distribution), and
# embedding cosine under optimal assignment (semantic). The semantic metrics
# need sentence-transformers + scipy (eval-only); they return None when those
# packages are absent so the live path never imports them.


def _ratio_sim(a, b):
    """Symmetric size-ratio similarity in [0, 1]. Both zero -> identical -> 1.0."""
    hi = max(a, b)
    return min(a, b) / hi if hi else 1.0


def _pearson(xs, ys):
    """Pearson correlation. Constant sequences correlate iff identical."""
    n = len(xs)
    if n < 2:
        return 1.0 if xs == ys else 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx == 0 or vy == 0:
        return 1.0 if xs == ys else 0.0
    return cov / math.sqrt(vx * vy)


def _degree_sequence(trace):
    """Total degree (in + out) per element, sorted descending."""
    deg = {el["id"]: 0 for el in trace.get("elements", [])}
    for f in trace.get("flows", []):
        if f["from"] in deg:
            deg[f["from"]] += 1
        if f["to"] in deg:
            deg[f["to"]] += 1
    return sorted(deg.values(), reverse=True)


def _structural_similarity(predicted, gold):
    """Name-agnostic topology similarity: mean of ratio-sims over node count,
    edge count, density, mean degree, plus |Pearson| of padded degree sequences.
    """
    pn, gn = len(predicted.get("elements", [])), len(gold.get("elements", []))
    pe, ge = len(predicted.get("flows", [])), len(gold.get("flows", []))

    def density(n, e):
        return e / (n * (n - 1)) if n > 1 else 0.0

    def mean_degree(n, e):
        return (2 * e) / n if n else 0.0

    sims = [
        _ratio_sim(pn, gn),
        _ratio_sim(pe, ge),
        _ratio_sim(density(pn, pe), density(gn, ge)),
        _ratio_sim(mean_degree(pn, pe), mean_degree(gn, ge)),
    ]
    dp, dg = _degree_sequence(predicted), _degree_sequence(gold)
    length = max(len(dp), len(dg))
    dp += [0] * (length - len(dp))
    dg += [0] * (length - len(dg))
    sims.append(abs(_pearson(dp, dg)))
    return round(sum(sims) / len(sims), 4)


def _type_distribution_similarity(pred_types, gold_types):
    """1 - Jensen-Shannon divergence (base 2) over element-type frequencies.
    Captures whether the trace has the right compositional mix of Fabric types.
    """
    keys = set(pred_types) | set(gold_types)
    if not keys:
        return 1.0
    p_total = sum(pred_types.values()) or 1
    q_total = sum(gold_types.values()) or 1
    P = {k: pred_types.get(k, 0) / p_total for k in keys}
    Q = {k: gold_types.get(k, 0) / q_total for k in keys}
    M = {k: 0.5 * (P[k] + Q[k]) for k in keys}

    def kl(a, b):
        return sum(a[k] * math.log2(a[k] / b[k]) for k in keys if a[k] > 0 and b[k] > 0)

    js = 0.5 * kl(P, M) + 0.5 * kl(Q, M)
    return round(max(0.0, 1.0 - js), 4)


_EMBED_MODEL = None
_EMBED_LOCK = threading.Lock()  # torch inference is not guaranteed thread-safe


def _get_embed_model():
    """Lazily load and cache the local sentence encoder (eval-only).

    Double-checked locking: under concurrent eval workers, an unguarded lazy
    init races and the partial load throws in some threads, which the caller's
    except-clause would silently turn into None scores.
    """
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        with _EMBED_LOCK:
            if _EMBED_MODEL is None:
                from sentence_transformers import SentenceTransformer

                _EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBED_MODEL


_SEMANTIC_KEYS = (
    "name_semantic_similarity",
    "name_type_semantic_similarity",
)


def _semantic_alignment(pred_elements, gold_elements):
    """Embedding-based meaning metrics under optimal (Hungarian) assignment.

    Element labels are embedded with all-MiniLM-L6-v2 and matched gold<->pred to
    maximise total cosine; semantic-similarity scores normalise by the larger
    side so missing/extra elements drag the score down.

    Returns Nones if sentence-transformers/scipy are unavailable — the metric is
    skipped rather than faked, and the live path never triggers the import.
    """
    try:
        from scipy.optimize import linear_sum_assignment

        model = _get_embed_model()
    except Exception:
        return {k: None for k in _SEMANTIC_KEYS}

    if not gold_elements:
        return {k: 1.0 for k in _SEMANTIC_KEYS}
    if not pred_elements:
        return {k: 0.0 for k in _SEMANTIC_KEYS}

    denom = max(len(gold_elements), len(pred_elements))

    def aligned_score(gold_strs, pred_strs):
        with _EMBED_LOCK:  # serialise torch inference across eval worker threads
            g_emb = model.encode(gold_strs, normalize_embeddings=True)
            p_emb = model.encode(pred_strs, normalize_embeddings=True)
        cos = g_emb @ p_emb.T  # normalised embeddings -> dot product is cosine
        rows, cols = linear_sum_assignment(-cos)
        return float(cos[rows, cols].sum()) / denom

    g_names = [el.get("name", "") for el in gold_elements]
    p_names = [el.get("name", "") for el in pred_elements]
    name_sim = aligned_score(g_names, p_names)

    g_nt = [f"{el.get('type', '')}: {el.get('name', '')}" for el in gold_elements]
    p_nt = [f"{el.get('type', '')}: {el.get('name', '')}" for el in pred_elements]
    name_type_sim = aligned_score(g_nt, p_nt)

    return {
        "name_semantic_similarity": round(max(0.0, name_sim), 4),
        "name_type_semantic_similarity": round(max(0.0, name_type_sim), 4),
    }


def reference_metrics(predicted, gold):
    """Fidelity of a predicted trace vs a gold trace from workflows.json.

    Reports each dimension on its own — count deltas (descriptive), gold type
    coverage, the two shape similarities, and the two meaning metrics. The
    axes are deliberately NOT collapsed into a single fidelity score.
    """
    gold_elements = gold.get("elements", [])
    gold_flows = gold.get("flows", [])

    if predicted is None or not isinstance(predicted, dict):
        # Failed generation has no graph to compare -> zero fidelity (distinct
        # from None, which means the semantic deps are not installed).
        return {
            "element_count_delta": -len(gold_elements),
            "flow_count_delta": -len(gold_flows),
            "gold_type_coverage": 0.0,
            "structural_similarity": 0.0,
            "type_distribution_similarity": 0.0,
            **{k: 0.0 for k in _SEMANTIC_KEYS},
        }

    pred_elements = predicted.get("elements", [])
    pred_flows = predicted.get("flows", [])

    pred_types = Counter(el["type"] for el in pred_elements)
    gold_types = Counter(el["type"] for el in gold_elements)

    gold_type_set, pred_type_set = set(gold_types), set(pred_types)
    coverage = (
        len(gold_type_set & pred_type_set) / len(gold_type_set)
        if gold_type_set
        else 1.0
    )

    return {
        "element_count_delta": len(pred_elements) - len(gold_elements),
        "flow_count_delta": len(pred_flows) - len(gold_flows),
        "gold_type_coverage": round(coverage, 4),
        "structural_similarity": _structural_similarity(predicted, gold),
        "type_distribution_similarity": _type_distribution_similarity(pred_types, gold_types),
        **_semantic_alignment(pred_elements, gold_elements),
    }
