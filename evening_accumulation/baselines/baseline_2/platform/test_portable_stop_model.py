"""Verify the embedded portable stop model against the frozen sklearn model."""
import base64
import json
import zlib

import joblib
import numpy as np

import build_supermind_baseline_1_2 as builder


bundle = joblib.load(builder.MODEL)
payload = json.loads(zlib.decompress(base64.b64decode(builder.export_model(bundle))).decode("utf-8"))
rng = np.random.default_rng(7)
features = rng.normal(size=(200, len(bundle["features"])))
expected = bundle["model"].predict_proba(features)[:, 1]
actual = []
for row in features:
    raw = payload["baseline"]
    for tree in payload["trees"]:
        index = 0
        while not tree[index]["leaf"]:
            node = tree[index]
            value = row[node["f"]]
            go_left = (np.isnan(value) and node["m"]) or (not np.isnan(value) and value <= node["t"])
            index = node["l"] if go_left else node["r"]
        raw += tree[index]["v"]
    actual.append(1.0 / (1.0 + np.exp(-raw)))
maximum = float(np.max(np.abs(expected - np.asarray(actual))))
print("max_probability_diff", maximum)
if maximum > 1e-12:
    raise SystemExit(1)
