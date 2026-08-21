"""Export the sklearn HistGradientBoosting model to a portable JSON tree ensemble."""
import json
import base64
import zlib
from pathlib import Path

import joblib
import pandas as pd


HERE = Path(__file__).resolve().parent
# Export the precision-constrained event model used by the standard tier.
bundle = joblib.load(HERE.parent / "outputs" / "event_recognition_v2" / "event_model.joblib")
model = bundle["model"]
trees = []
for stage in model._predictors:
    nodes = stage[0].nodes
    trees.append([
        {
            "v": float(node["value"]),
            "f": int(node["feature_idx"]),
            "t": float(node["num_threshold"]),
            "m": bool(node["missing_go_to_left"]),
            "l": int(node["left"]),
            "r": int(node["right"]),
            "leaf": bool(node["is_leaf"]),
        }
        for node in nodes
    ])
payload = {
    "format": "portable_hist_gradient_boosting_v1",
    "features": bundle["features"],
    "baseline": float(model._baseline_prediction.ravel()[0]),
    "trees": trees,
    "threshold": 0.689688,
    "top_per_day": 8,
    "max_positions": 14,
    "universe": pd.read_csv(HERE.parent / "data" / "metadata" / "classified_manifest.csv")
        .query("exchange == 'SH' and board == 'star'")["symbol"].sort_values().tolist(),
}
model_text = json.dumps(payload, separators=(",", ":"))
(HERE / "event_standard_model.json").write_text(model_text, encoding="utf-8")
source = (HERE / "supermind_star_r09.py").read_text(encoding="utf-8")
source = source.replace("STAR r09", "STAR event standard").replace("local r09", "local event-standard")
source = source.replace("Upload this file and star_r09_model.json to the same SuperMind project folder.",
                        "The single-file build embeds the model and needs no project attachment.")
encoded = base64.b64encode(zlib.compress(model_text.encode("utf-8"), level=9)).decode("ascii")
chunks = [encoded[i:i + 100] for i in range(0, len(encoded), 100)]
embedded = "_EMBEDDED_MODEL_B64 = (\n" + "\n".join('    "' + chunk + '"' for chunk in chunks) + "\n)"
single = source.replace('_EMBEDDED_MODEL_B64 = ""', embedded)
(HERE / "supermind_event_standard.py").write_text(source, encoding="utf-8")
(HERE / "supermind_event_standard_single.py").write_text(single, encoding="utf-8")
(HERE / "supermind_event_baseline30_strict_single.py").write_text(single, encoding="utf-8")
print(HERE / "event_standard_model.json")
print(HERE / "supermind_event_standard_single.py")
print(HERE / "supermind_event_baseline30_strict_single.py")
