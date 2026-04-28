"""
Live OpenAI smoke test — run rarely, gated behind RUN_LIVE_OPENAI=1.

Asserts only structural invariants (parses, validates, has start + terminal).
Don't assert on specific node names or counts — the prompt evolves and
brittle assertions fight you. Run before releases or after touching
prompts/system_prompt.py / prompts/few_shot_examples.json.

    RUN_LIVE_OPENAI=1 OPENAI_API_KEY=sk-... pytest -m live
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_OPENAI") != "1",
    reason="set RUN_LIVE_OPENAI=1 to run live OpenAI smoke tests",
)


@pytest.mark.live
def test_live_generate_trace_smoke():
    from services.llm_service import generate_trace
    from services.schema_validator import validate_schema

    result = generate_trace(
        user_message=(
            "A user submits a form. An AI model reviews it. A human reviewer "
            "either accepts, modifies, or rejects the AI's suggestion. "
            "Then the process ends."
        ),
        conversation_history=[],
    )
    assert result["error"] is None, result["error"]

    trace = result["json"]
    assert trace is not None, f"Could not parse JSON. Raw: {result['raw_response'][:500]}"

    schema_ok, schema_errs = validate_schema(trace)
    assert schema_ok, f"Schema errors: {schema_errs}"

    types = {el["type"] for el in trace["elements"]}
    assert "finalOutcome" in types, "trace has no finalOutcome (terminal) node"
