"""
Offline eval harness for the Fabric trace pipeline.

Runs each fixture in prompts/workflows.json through llm_service.generate_trace
N times (default 3) and writes per-run metrics + an aggregated summary to
evals/results/<UTC-timestamp>/. The shared metric module
(services.telemetry) is the single source of truth for what "good" means —
the live event logger uses the same primitives.

Usage:
    python scripts/run_evals.py                          # all fixtures, N=3
    python scripts/run_evals.py --n 5                    # 5 runs each
    python scripts/run_evals.py --fixtures "NHS,Beam"    # substring filter
    python scripts/run_evals.py --limit 3                # first 3 fixtures only
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from services.llm_service import generate_trace  # noqa: E402
from services.telemetry import generation_metrics, reference_metrics  # noqa: E402


FIXTURES_PATH = REPO_ROOT / "prompts" / "workflows.json"
RESULTS_ROOT = REPO_ROOT / "evals" / "results"


# Columns that flatten cleanly into a CSV row. Dict-valued metrics
# (element_type_counts, errors) are JSON-serialised when written.
PER_RUN_COLUMNS = [
    "process_name",
    "run_idx",
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
    "element_type_jaccard_multiset",
    "gold_type_coverage",
    "final_outcome_recall",
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
    "element_type_jaccard_multiset",
    "gold_type_coverage",
    "final_outcome_recall",
]

BOOL_COLUMNS_FOR_AGG = ["parsed_ok", "schema_pass", "semantic_pass", "has_cycle"]


def load_fixtures(path: Path, filter_substr: str | None, limit: int | None):
    data = json.loads(path.read_text(encoding="utf-8"))
    if filter_substr:
        wanted = [s.strip().lower() for s in filter_substr.split(",") if s.strip()]
        data = [
            w
            for w in data
            if any(sub in w["assistant"]["process_name"].lower() for sub in wanted)
        ]
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
    }


def _scalar(v):
    """Reduce JSON-y values to a string that survives a CSV round-trip."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v


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


def write_summary_json(rows: list[dict], per_fixture: list[dict], path: Path, wall_seconds: float) -> None:
    total_runs = len(rows)
    schema_pass = sum(1 for r in rows if r.get("schema_pass"))
    semantic_pass = sum(1 for r in rows if r.get("semantic_pass"))
    parsed = sum(1 for r in rows if r.get("parsed_ok"))
    total_prompt = sum(r.get("prompt_tokens", 0) or 0 for r in rows)
    total_completion = sum(r.get("completion_tokens", 0) or 0 for r in rows)
    summary = {
        "total_runs": total_runs,
        "fixtures": len(per_fixture),
        "wall_seconds": round(wall_seconds, 2),
        "rates": {
            "parsed_ok": round(parsed / total_runs, 4) if total_runs else 0.0,
            "schema_pass": round(schema_pass / total_runs, 4) if total_runs else 0.0,
            "semantic_pass": round(semantic_pass / total_runs, 4) if total_runs else 0.0,
        },
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
    parser.add_argument("--dry-run", action="store_true", help="List fixtures and exit without calling the LLM")
    args = parser.parse_args()

    fixtures = load_fixtures(FIXTURES_PATH, args.fixtures, args.limit)
    if not fixtures:
        print("No fixtures matched filter.", file=sys.stderr)
        return 1
    print(f"Running {len(fixtures)} fixture(s) x N={args.n} = {len(fixtures) * args.n} LLM calls")
    for w in fixtures:
        print("  -", w["assistant"]["process_name"])
    if args.dry_run:
        return 0

    run_dir = RESULTS_ROOT / datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Writing to {run_dir.relative_to(REPO_ROOT)}")

    rows: list[dict] = []
    started = time.perf_counter()
    for w in fixtures:
        name = w["assistant"]["process_name"]
        gold = w["assistant"]
        prompt = w["user"]
        for i in range(args.n):
            t0 = time.perf_counter()
            row = run_one(prompt, gold)
            row["process_name"] = name
            row["run_idx"] = i
            rows.append(row)
            dur = time.perf_counter() - t0
            ok = "ok" if row["semantic_pass"] else "FAIL"
            print(f"  [{name} run {i}] {ok} {dur:.1f}s tokens={row['total_tokens']}")

    wall = time.perf_counter() - started
    write_runs_csv(rows, run_dir / "runs.csv")
    per_fixture = aggregate_per_fixture(rows)
    write_summary_csv(per_fixture, run_dir / "summary.csv")
    write_summary_json(rows, per_fixture, run_dir / "summary.json", wall)
    print(f"Done in {wall:.1f}s. See {run_dir.relative_to(REPO_ROOT)}/summary.json for headline numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
