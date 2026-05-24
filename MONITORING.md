# Monitoring & Evals

Two separate measurement paths share the metric module `services/telemetry.py`:

1. **Live monitoring** — append-only JSONL log written from the running Flask app. Always on.
2. **Offline evals** — `scripts/run_evals.py` over the 20 fixtures in `prompts/workflows.json`. Run on demand.

## Live monitoring

Each significant request emits one JSON line to `${LOG_DIR}/weaver.jsonl`. Default `LOG_DIR=./data`; the docker-compose service mounts the host's `./data` directory to `/data` inside the container, so logs survive `docker compose down`. Rotation is 10 MB × 10 files.

Common fields on every record: `ts` (UTC ISO 8601), `event` (name), `session` (12-hex anonymous per-session ID — SHA-256 of a UUID stored in the Flask session; not reversible to a cookie).

| `event`              | When                                | Notable fields                                                                                                                                                                                              |
| -------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `chat_summarize`     | `/api/chat` Flow B (summary turn)   | `message_len`, `has_image`, `summary_len`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `latency_ms`, `api_error`                                                                                   |
| `chat_generation`    | `/api/chat` Flow A or C (trace gen) | `flow` (`edit`/`confirm`), `message_len`, `finish_reason`, `api_error`, full generation_metrics: validity (`parsed_ok`/`schema_pass`/`semantic_pass`/`errors`), tokens (`prompt_tokens`/`completion_tokens`/`total_tokens`/`latency_ms`), structural (`num_elements`/`num_flows`/`element_type_counts`/`branching_factor`/`max_path_length`/`has_cycle`) |
| `sync`               | `/api/sync`                         | `status` (`ok`/`rejected`), `schema_errors` or `semantic_warnings`, structural metrics of the synced trace                                                                                                  |
| `export`             | `/api/export`                       | `status` (`ok`/`empty`), `process_name`, structural metrics — effectively the "submission" event                                                                                                            |
| `upload`             | `/api/upload`                       | `status`, `bytes`, `mime`, `error` (if rejected)                                                                                                                                                            |
| `reset`              | `/api/reset`                        | `had_trace`, `conversation_len`                                                                                                                                                                             |

Token counts (`prompt_tokens` / `completion_tokens` / `total_tokens`) are logged raw — convert to USD at analysis time using the pricing in force at that moment.

**Pulling logs off the droplet:**

```bash
scp droplet:/opt/trace-fabric/data/weaver.jsonl ./
# or in pandas
python -c "import pandas as pd; df = pd.read_json('weaver.jsonl', lines=True); print(df.event.value_counts())"
```

## Offline evals

`scripts/run_evals.py` runs each of the 20 fixtures in `prompts/workflows.json` through `llm_service.generate_trace` N times and writes timestamped CSV + JSON to `evals/results/<UTC>/`.

```bash
python scripts/run_evals.py                          # all 20, N=3 (60 LLM calls)
python scripts/run_evals.py --n 5                    # N=5 (100 calls)
python scripts/run_evals.py --fixtures "NHS,Beam"    # substring filter
python scripts/run_evals.py --limit 3 --n 1          # smoke test (3 calls)
python scripts/run_evals.py --dry-run                # list fixtures, no LLM calls
```

Outputs:

- `runs.csv` — one row per LLM call. Generation metrics + reference metrics (vs the gold trace in `workflows.json`).
- `summary.csv` — one row per fixture. Mean / median / stdev across the N runs for every numeric metric, and pass-rate for boolean metrics.
- `summary.json` — overall pass rates and totals (tokens, cost, wall-clock) for the run.

Reference metrics (offline-only):

- `element_count_delta` / `flow_count_delta` — predicted minus gold.
- `element_type_jaccard_multiset` — multiset Jaccard on element types. 1.0 = identical type distribution.
- `gold_type_coverage` — fraction of gold element types present in the prediction.
- `final_outcome_recall` — fraction of gold `finalOutcome` names matched by token overlap (threshold 0.5) in the prediction.

The eval harness and the live logger share `services/telemetry.py`, so "what counts as a good trace" is defined in exactly one place.
