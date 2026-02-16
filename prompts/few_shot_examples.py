import json
import os

_path = os.path.join(os.path.dirname(__file__), "few_shot_examples.json")
with open(_path, "r") as f:
    _raw = json.load(f)

FEW_SHOT_EXAMPLES = []
for ex in _raw:
    FEW_SHOT_EXAMPLES.append({"role": "user", "content": ex["user"]})
    FEW_SHOT_EXAMPLES.append({"role": "assistant", "content": json.dumps(ex["assistant"])})
