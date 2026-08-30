"""Export the trained market-risk model to portable compressed JSON."""
import base64
import json
import zlib
from pathlib import Path

import joblib


HERE = Path(__file__).resolve().parent
bundle = joblib.load(HERE.parent / "outputs" / "risk_overlay_balanced" / "risk_model.joblib")
model = bundle["model"]
trees = []
for stage in model._predictors:
    nodes = stage[0].nodes
    trees.append([
        {"v": float(node["value"]), "f": int(node["feature_idx"]),
         "t": float(node["num_threshold"]), "m": bool(node["missing_go_to_left"]),
         "l": int(node["left"]), "r": int(node["right"]),
         "leaf": bool(node["is_leaf"])}
        for node in nodes
    ])
metrics = bundle["metrics"]
payload = {
    "format": "portable_hist_gradient_boosting_v1",
    "features": bundle["features"],
    "baseline": float(model._baseline_prediction.ravel()[0]),
    "trees": trees,
    "threshold": float(metrics["threshold"]),
    "caution_threshold": float(metrics["caution_threshold"]),
    "extreme_threshold": float(metrics["extreme_threshold"]),
    "caps": {"normal": 0.90, "caution": 0.75, "risk": 0.50, "extreme": 0.20},
    "training": metrics,
}
text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
(HERE / "market_risk_model.json").write_text(text, encoding="utf-8")
encoded = base64.b64encode(zlib.compress(text.encode("utf-8"), level=9)).decode("ascii")
(HERE / "market_risk_model.b64").write_text(encoded, encoding="ascii")
print(HERE / "market_risk_model.json", len(text), len(encoded))
