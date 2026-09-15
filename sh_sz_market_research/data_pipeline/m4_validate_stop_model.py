"""Leakage-free 2024 validation of the M4 stop-first model architecture."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from sklearn.metrics import average_precision_score, precision_score, recall_score, roc_auc_score

from m4_train_models import FEATURES, fit_model, load_rows


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "m4_models"


def main():
    frozen_path = OUT / "frozen_parameters.json"
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    pool = frozen["chosen_pool"]
    cap = {"pool_a": 260, "pool_b": 420, "pool_c": 520}[pool]
    fit = load_rows(pool, None, "2023-11-30", cap, "stop_first22")
    valid = load_rows(pool, "2024-01-01", "2024-11-29", 10000, "stop_first22")
    model = fit_model(fit, "stop_first22", 172, max_iter=160)
    y = valid.stop_first22.astype(int).to_numpy()
    p = model.predict_proba(valid[FEATURES].astype("float32"))[:, 1]
    pred = p > .50
    metrics = {
        "fit_end": "2023-11-30", "validation": ["2024-01-01", "2024-11-29"],
        "fit_samples": int(len(fit)), "validation_samples": int(len(valid)),
        "validation_positive_rate": float(y.mean()), "roc_auc": float(roc_auc_score(y, p)),
        "pr_auc": float(average_precision_score(y, p)),
        "precision_at_0.50": float(precision_score(y, pred, zero_division=0)),
        "recall_at_0.50": float(recall_score(y, pred, zero_division=0)),
        "filtered_fraction": float(pred.mean()),
    }
    frozen["stop_model_leakage_free_validation"] = metrics
    frozen_path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "stop_model_validation.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
