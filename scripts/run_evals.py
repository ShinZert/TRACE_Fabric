"""
Offline eval harness for the Fabric trace pipeline.

Runs each fixture in prompts/workflows.json through llm_service.generate_trace
N times (default 3) and writes per-run metrics, an aggregated summary, and the
raw generated trace JSON (traces/<slug>__run<idx>.json) to
evals/results/<UTC-timestamp>/. The shared metric module
(services.telemetry) is the single source of truth for what "good" means —
the live event logger uses the same primitives.

Held-out evaluation: the 3 examples in prompts/few_shot_examples.json are
sent with every LLM request, so any fixture that also appears there is
contaminated — the model sees its gold answer in the prompt. Those fixtures
are excluded by default and every row carries a `held_out` flag. Use
--include-seen to run them anyway (e.g. to quantify the contamination gap).

Usage:
    python scripts/run_evals.py                          # held-out fixtures, N=3, 6 parallel
    python scripts/run_evals.py --n 5                    # 5 runs each
    python scripts/run_evals.py --concurrency 1          # sequential (debugging)
    python scripts/run_evals.py --fixtures "NHS,Beam"    # substring filter
    python scripts/run_evals.py --limit 3                # first 3 fixtures only
    python scripts/run_evals.py --include-seen           # also run few-shot fixtures
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from config import OPENAI_MODEL  # noqa: E402
from services.llm_service import generate_trace  # noqa: E402
from services.telemetry import generation_metrics, reference_metrics  # noqa: E402


FIXTURES_PATH = REPO_ROOT / "prompts" / "workflows.json"
FEW_SHOT_PATH = REPO_ROOT / "prompts" / "few_shot_examples.json"
RESULTS_ROOT = REPO_ROOT / "evals" / "results"


# Columns that flatten cleanly into a CSV row. Dict-valued metrics
# (element_type_counts, errors) are JSON-serialised when written.
PER_RUN_COLUMNS = [
    "process_name",
    "run_idx",
    "held_out",
    "model",
    "parsed_ok",
    "schema_pass",
    "semantic_pass",
    "errors",
    "finish_reason",
    "api_error",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "num_elements",
    "num_flows",
    "element_type_counts",
    "num_final_outcomes",
    "branching_factor",
    "max_path_length",
    "has_cycle",
    "element_count_delta",
    "flow_count_delta",
    "gold_type_coverage",
    "structural_similarity",
    "type_distribution_similarity",
    "name_semantic_similarity",
    "name_type_semantic_similarity",
]

NUMERIC_COLUMNS_FOR_AGG = [
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "latency_ms",
    "num_elements",
    "num_flows",
    "num_final_outcomes",
    "branching_factor",
    "max_path_length",
    "element_count_delta",
    "flow_count_delta",
    "gold_type_coverage",
    "structural_similarity",
    "type_distribution_similarity",
    "name_semantic_similarity",
    "name_type_semantic_similarity",
]

BOOL_COLUMNS_FOR_AGG = ["parsed_ok", "schema_pass", "semantic_pass", "has_cycle"]


def load_seen_keys(path: Path) -> tuple[set[str], set[str]]:
    """Process names + user messages of the few-shot examples sent with every request."""
    if not path.exists():
        return set(), set()
    examples = json.loads(path.read_text(encoding="utf-8"))
    names = {ex["assistant"].get("process_name", "") for ex in examples}
    users = {ex["user"] for ex in examples}
    return names, users


def load_fixtures(path: Path, filter_substr: str | None, limit: int | None, include_seen: bool = False):
    """Load fixtures, flag few-shot contamination, and (by default) drop seen ones.

    Order matters: substring filter -> seen exclusion -> limit, so --limit N
    always yields N runnable fixtures.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    seen_names, seen_users = load_seen_keys(FEW_SHOT_PATH)
    for w in data:
        w["held_out"] = (
            w["assistant"]["process_name"] not in seen_names
            and w["user"] not in seen_users
        )
    if filter_substr:
        wanted = [s.strip().lower() for s in filter_substr.split(",") if s.strip()]
        data = [
            w
            for w in data
            if any(sub in w["assistant"]["process_name"].lower() for sub in wanted)
        ]
    if not include_seen:
        seen = [w for w in data if not w["held_out"]]
        data = [w for w in data if w["held_out"]]
        if seen:
            print(f"Excluding {len(seen)} fixture(s) that are also few-shot examples (use --include-seen to run them):")
            for w in seen:
                print("  x", w["assistant"]["process_name"])
    if limit is not None:
        data = data[:limit]
    return data


def run_one(user_message: str, gold: dict) -> dict:
    """Single LLM call. Returns the merged generation + reference metrics row."""
    result = generate_trace(
        user_message=user_message,
        conversation_history=[],
        current_trace=None,
        image_base64=None,
    )
    trace = result.get("json")
    gen = generation_metrics(
        trace,
        usage=result.get("usage"),
        latency_ms=result.get("latency_ms", 0),
        parse_error=result.get("error") if trace is None else None,
    )
    ref = reference_metrics(trace, gold)
    return {
        **gen,
        **ref,
        "finish_reason": result.get("finish_reason"),
        "api_error": result.get("error") if trace is None else None,
        # Raw generated trace, kept for the per-run JSON dump. Not a CSV column
        # (write_runs_csv only emits PER_RUN_COLUMNS), so it's ignored there.
        "trace": trace,
    }


def run_task(fixture: dict, run_idx: int) -> dict:
    """run_one plus the fixture's identifying fields — the unit of parallel work."""
    row = run_one(fixture["user"], fixture["assistant"])
    row["process_name"] = fixture["assistant"]["process_name"]
    row["run_idx"] = run_idx
    row["held_out"] = fixture["held_out"]
    row["model"] = OPENAI_MODEL
    return row


def _scalar(v):
    """Reduce JSON-y values to a string that survives a CSV round-trip."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


def _slug(name: str) -> str:
    """Filesystem-safe slug from a process name (collapses runs of non-alnum)."""
    out = "".join(c.lower() if c.isalnum() else "_" for c in name or "")
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_") or "trace"


def write_traces(rows: list[dict], traces_dir: Path) -> None:
    """Dump each run's generated trace as a bare Fabric trace JSON.

    Each file is the raw trace ({process_name, elements, flows}) with no
    wrapper, so it imports directly into Weaver and re-syncs cleanly — the
    backend schema sets additionalProperties:false, so any extra top-level
    key would be rejected on /api/sync. The verdict (parsed/schema/semantic
    pass + errors) lives in runs.csv, keyed by the same process_name +
    run_idx as the filename, so nothing is lost.

    One file per run: <process-slug>__run<idx>.json. Failed / parse-error
    runs (trace is None) get a small stub recording the error instead of a
    trace — there is no graph to import for those.
    """
    traces_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        fname = f"{_slug(row.get('process_name'))}__run{row.get('run_idx', 0)}.json"
        trace = row.get("trace")
        payload = trace if trace is not None else {
            "_note": "no trace — run failed before producing valid JSON",
            "process_name": row.get("process_name"),
            "run_idx": row.get("run_idx"),
            "errors": row.get("errors"),
        }
        (traces_dir / fname).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )


def write_runs_csv(rows: list[dict], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=PER_RUN_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: _scalar(row.get(col)) for col in PER_RUN_COLUMNS})


def _safe_stats(values: list[float | int | None]):
    cleaned = [v for v in values if v is not None]
    if not cleaned:
        return {"mean": None, "median": None, "stdev": None, "n": 0}
    return {
        "mean": round(statistics.fmean(cleaned), 4),
        "median": round(statistics.median(cleaned), 4),
        "stdev": round(statistics.pstdev(cleaned), 4) if len(cleaned) > 1 else 0.0,
        "n": len(cleaned),
    }


def aggregate_per_fixture(rows: list[dict]) -> list[dict]:
    by_fixture: dict[str, list[dict]] = {}
    for r in rows:
        by_fixture.setdefault(r["process_name"], []).append(r)
    out = []
    for name, runs in by_fixture.items():
        record: dict = {"process_name": name, "n_runs": len(runs)}
        for col in NUMERIC_COLUMNS_FOR_AGG:
            stats = _safe_stats([r.get(col) for r in runs])
            record[f"{col}_mean"] = stats["mean"]
            record[f"{col}_median"] = stats["median"]
            record[f"{col}_stdev"] = stats["stdev"]
        for col in BOOL_COLUMNS_FOR_AGG:
            true_count = sum(1 for r in runs if r.get(col))
            record[f"{col}_rate"] = round(true_count / len(runs), 4)
        out.append(record)
    return out


def write_summary_csv(per_fixture: list[dict], path: Path) -> None:
    if not per_fixture:
        path.write_text("", encoding="utf-8")
        return
    columns = list(per_fixture[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in per_fixture:
            writer.writerow({c: _scalar(row.get(c)) for c in columns})


def _rates(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"parsed_ok": 0.0, "schema_pass": 0.0, "semantic_pass": 0.0}
    return {
        "parsed_ok": round(sum(1 for r in rows if r.get("parsed_ok")) / n, 4),
        "schema_pass": round(sum(1 for r in rows if r.get("schema_pass")) / n, 4),
        "semantic_pass": round(sum(1 for r in rows if r.get("semantic_pass")) / n, 4),
    }


def write_summary_json(rows: list[dict], per_fixture: list[dict], path: Path, wall_seconds: float) -> None:
    held_out_rows = [r for r in rows if r.get("held_out")]
    seen_rows = [r for r in rows if not r.get("held_out")]
    total_prompt = sum(r.get("prompt_tokens", 0) or 0 for r in rows)
    total_completion = sum(r.get("completion_tokens", 0) or 0 for r in rows)
    summary = {
        "model": OPENAI_MODEL,
        "total_runs": len(rows),
        "fixtures": len(per_fixture),
        "held_out_runs": len(held_out_rows),
        "seen_runs": len(seen_rows),
        "seen_fixtures": sorted({r["process_name"] for r in seen_rows}),
        "wall_seconds": round(wall_seconds, 2),
        "rates": _rates(rows),
        "rates_held_out": _rates(held_out_rows),
        "totals": {
            "prompt_tokens": total_prompt,
            "completion_tokens": total_completion,
            "total_tokens": total_prompt + total_completion,
        },
    }
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=3, help="Runs per fixture (default 3)")
    parser.add_argument("--fixtures", type=str, default=None, help="Comma-separated substrings to filter fixtures by process_name")
    parser.add_argument("--limit", type=int, default=None, help="Take only the first N fixtures (after --fixtures filter)")
    parser.add_argument("--concurrency", type=int, default=6, help="Parallel LLM calls in flight (default 6; set 1 for sequential)")
    parser.add_argument("--dry-run", action="store_true", help="List fixtures and exit without calling the LLM")
    parser.add_argument(
        "--include-seen",
        action="store_true",
        help="Also run fixtures that appear in few_shot_examples.json (contaminated - the model sees their gold answer in the prompt)",
    )
    args = parser.parse_args()

    fixtures = load_fixtures(FIXTURES_PATH, args.fixtures, args.limit, include_seen=args.include_seen)
    if not fixtures:
        print("No fixtures matched filter.", file=sys.stderr)
        return 1
    print(f"Model: {OPENAI_MODEL}")
    print(f"Running {len(fixtures)} fixture(s) x N={args.n} = {len(fixtures) * args.n} LLM calls")
    for w in fixtures:
        tag = "" if w["held_out"] else "  [SEEN - in few-shot prompt]"
        print("  -", w["assistant"]["process_name"] + tag)
    if args.dry_run:
        return 0

    run_dir = RESULTS_ROOT / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing to {run_dir.relative_to(REPO_ROOT)}")

    tasks = [(w, i) for w in fixtures for i in range(args.n)]
    rows: list[dict] = []
    started = time.perf_counter()
    workers = max(1, args.concurrency)
    print(f"Concurrency: {workers} parallel call(s) in flight")
    if workers > 1:
        # Warm the embedding model once so worker threads don't race its lazy load.
        try:
            from services.telemetry import _get_embed_model
            _get_embed_model()
        except Exception:
            pass  # semantic metrics will report None if the deps are missing
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_task, w, i): (w["assistant"]["process_name"], i) for w, i in tasks}
        for fut in as_completed(futures):
            name, i = futures[fut]
            row = fut.result()
            rows.append(row)
            ok = "ok" if row["semantic_pass"] else "FAIL"
            print(f"  [{len(rows)}/{len(tasks)}] {name} run {i}: {ok} tokens={row['total_tokens']}")

    # Deterministic output order regardless of completion order.
    rows.sort(key=lambda r: (r["process_name"], r["run_idx"]))
    wall = time.perf_counter() - started
    write_runs_csv(rows, run_dir / "runs.csv")
    per_fixture = aggregate_per_fixture(rows)
    write_summary_csv(per_fixture, run_dir / "summary.csv")
    write_summary_json(rows, per_fixture, run_dir / "summary.json", wall)
    write_traces(rows, run_dir / "traces")
    print(f"Done in {wall:.1f}s. See {run_dir.relative_to(REPO_ROOT)}/summary.json for headline numbers.")
    print(f"Per-run trace JSON in {run_dir.relative_to(REPO_ROOT)}/traces/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
