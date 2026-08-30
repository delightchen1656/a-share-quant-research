"""Build the standalone SuperMind file for Baseline 1-2 from Baseline 1-1."""
from pathlib import Path
import base64
import json
import zlib

import joblib


HERE = Path(__file__).resolve().parent
BASELINE_DIR = HERE.parent
PROJECT = HERE.parents[2]
SOURCE = PROJECT / "baselines" / "baseline_1" / "strategy" / "supermind_baseline_1.py"
MODEL = BASELINE_DIR / "model" / "stop_risk_model.joblib"
TARGET = HERE / "supermind_baseline_1_2_stop_filter_single.py"


def export_model(bundle):
    model = bundle["model"]
    trees = []
    for stage in model._predictors:
        nodes = stage[0].nodes
        trees.append([{
            "v": float(node["value"]), "f": int(node["feature_idx"]),
            "t": float(node["num_threshold"]), "m": bool(node["missing_go_to_left"]),
            "l": int(node["left"]), "r": int(node["right"]),
            "leaf": bool(node["is_leaf"]),
        } for node in nodes])
    payload = {
        "format": "portable_hist_gradient_boosting_v1",
        "features": list(bundle["features"]),
        "baseline": float(model._baseline_prediction.ravel()[0]),
        "trees": trees,
        "threshold": 0.50,
        "rank_penalty": 0.22,
        "training_end": bundle["training_end"],
        "label": bundle["label"],
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(zlib.compress(raw, 9)).decode("ascii")


def literal(name, encoded):
    chunks = [encoded[i:i + 100] for i in range(0, len(encoded), 100)]
    return name + " = (\n" + "\n".join('    "' + x + '"' for x in chunks) + "\n)\n\n"


text = SOURCE.read_text(encoding="utf-8")
encoded = export_model(joblib.load(MODEL))
insert_at = text.index("def _load_model():")
text = text[:insert_at] + literal("_EMBEDDED_STOP_MODEL_B64", encoded) + text[insert_at:]

helper = r'''
def _load_stop_model():
    raw = zlib.decompress(base64.b64decode(_EMBEDDED_STOP_MODEL_B64.encode("ascii")))
    model = json.loads(raw.decode("utf-8"))
    model["fast_trees"] = [
        (np.asarray([n["f"] for n in tree], dtype=np.int16),
         np.asarray([n["t"] for n in tree]),
         np.asarray([n["m"] for n in tree], dtype=bool),
         np.asarray([n["l"] for n in tree], dtype=np.int16),
         np.asarray([n["r"] for n in tree], dtype=np.int16),
         np.asarray([n["leaf"] for n in tree], dtype=bool),
         np.asarray([n["v"] for n in tree])) for tree in model["trees"]
    ]
    return model


'''
init_at = text.index("def init(context):")
text = text[:init_at] + helper + text[init_at:]
text = text.replace("    g.pending = []\n", "    g.stop_model = _load_stop_model()\n    g.pending = []\n", 1)
text = text.replace(
    'log.info("Baseline 1-1 Accumulation Rally initialized; daily frequency; cost=%s" % COST_SCENARIO)',
    'log.info("Baseline 1-2 Stop Filter initialized; daily frequency; cost=%s" % COST_SCENARIO)', 1)

old = '''    scored = []
    if feature_rows:
        probabilities = _batch_probabilities(g.model, [item[1] for item in feature_rows])
        scored = [(feature_rows[i][0], float(p)) for i, p in enumerate(probabilities)
                  if p >= g.model["threshold"]]
    scored.sort(key=lambda item: item[1], reverse=True)
    g.pending = scored[:g.model["top_per_day"]]
    g.buy_done_date = None
    log.info("STAR candidates: %s" % str(g.pending))
'''
new = '''    scored = []
    if feature_rows:
        values = [item[1] for item in feature_rows]
        probabilities = _batch_probabilities(g.model, values)
        stop_probabilities = _batch_probabilities(g.stop_model, values)
        for i in range(len(feature_rows)):
            probability = float(probabilities[i])
            stop_probability = float(stop_probabilities[i])
            if probability < g.model["threshold"] or stop_probability > 0.50:
                continue
            rank_score = probability - 0.22 * stop_probability
            scored.append((feature_rows[i][0], probability, rank_score, stop_probability))
    scored.sort(key=lambda item: item[2], reverse=True)
    g.pending = [(item[0], item[1]) for item in scored[:g.model["top_per_day"]]]
    g.buy_done_date = None
    log.info("BASELINE1-2 candidates=%s" % str(g.pending))
'''
if old not in text:
    raise RuntimeError("Baseline 1-1 selection block not found")
text = text.replace(old, new, 1)
TARGET.write_text(text, encoding="utf-8")
print(TARGET, TARGET.stat().st_size)
