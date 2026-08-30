"""Static and numerical checks for the Strategy 3 SuperMind single-file build."""
import ast
import json
from pathlib import Path

import joblib
import numpy as np


ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
TARGET = HERE / "supermind_strategy3_bear_downside_v1_single.py"


def portable_probability(model, row):
    raw = float(model["baseline"])
    for tree in model["trees"]:
        i = 0
        while not tree[i]["leaf"]:
            node = tree[i]; x = row[node["f"]]
            left = node["m"] if np.isnan(x) else x <= node["t"]
            i = node["l"] if left else node["r"]
        raw += tree[i]["v"]
    return 1.0 / (1.0 + np.exp(-raw))


def main():
    source = TARGET.read_text(encoding="utf-8")
    ast.parse(source)
    forbidden = {
        "import os": "import os" in source,
        "open_call": "open(" in source,
        "getattr_call": "getattr(" in source,
        "embedded_stop_empty": '_EMBEDDED_STOP_MODEL_B64 = ""' in source,
        "embedded_bear_empty": '_EMBEDDED_BEAR_MODELS_B64 = ""' in source,
    }
    if any(forbidden.values()):
        raise AssertionError(forbidden)

    bundle = joblib.load(ROOT / "baselines" / "baseline_2" / "model" / "stop_risk_model.joblib")
    portable = json.loads((HERE / "strategy3_stop_risk_model.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(73)
    rows = rng.normal(size=(256, len(bundle["features"])))
    expected = bundle["model"].predict_proba(rows)[:, 1]
    actual = np.asarray([portable_probability(portable, row) for row in rows])
    maximum_difference = float(np.max(np.abs(expected - actual)))
    if maximum_difference > 1e-12:
        raise AssertionError("stop-model difference %.16g" % maximum_difference)

    bear = json.loads((HERE / "strategy3_bear_models.json").read_text(encoding="utf-8"))
    if len(bear["models"]) != 23 or bear["valid_through"] != "2026-09-30":
        raise AssertionError("unexpected bear bundle")
    report = {
        "syntax": "ok", "forbidden_scan": forbidden,
        "stop_model_max_probability_difference": maximum_difference,
        "bear_model_count": len(bear["models"]),
        "bear_valid_through": bear["valid_through"],
        "single_file_bytes": TARGET.stat().st_size,
    }
    (HERE / "strategy3_supermind_test.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
