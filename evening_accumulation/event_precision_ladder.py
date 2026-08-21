"""Build conservative alert tiers using validation-only precision constraints."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features
from event_recognition_v2 import make_label, model

ROOT = Path(__file__).resolve().parent
TARGETS = [.20, .25, .30, .35, .40, .50, .60, .70, .80, .90, .95]


def cutoff_for_precision(y, p, target):
    order = np.argsort(-p); ys = y[order]; ps = p[order]
    tp = np.cumsum(ys); n = np.arange(1, len(ys) + 1); precision = tp / n
    boundaries = np.r_[ps[:-1] > ps[1:], True]
    valid = np.flatnonzero(boundaries & (precision >= target))
    if not len(valid): return None
    # Maximum correct alerts while satisfying the requested precision.
    i = valid[np.argmax(tp[valid])]
    return float(ps[i]), int(n[i]), int(tp[i]), float(precision[i])


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _, qfq = load_panel(ROOT, "star")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["label"], ds["hit_date"] = make_label(ds)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["label"])
    fit = ds[ds.date <= "2023-12-01"]
    val = ds[(ds.date >= "2024-01-01") & (ds.date <= "2024-12-01")].copy()
    train = ds[ds.date <= "2024-12-01"]
    test = ds[(ds.date >= "2025-01-01") & (ds.date <= "2026-07-01")].copy()
    vm = model(); vm.fit(fit[FEATURES], fit.label.astype(int)); vp = vm.predict_proba(val[FEATURES])[:, 1]
    tm = model(); tm.fit(train[FEATURES], train.label.astype(int)); test["probability"] = tm.predict_proba(test[FEATURES])[:, 1]
    rows = []
    for target in TARGETS:
        selected = cutoff_for_precision(val.label.astype(int).to_numpy(), vp, target)
        if selected is None:
            rows.append({"target_precision": target, "available": False}); continue
        threshold, vn, vtp, vprecision = selected
        pred = test[test.probability >= threshold]; correct = int(pred.label.sum())
        rows.append({"target_precision": target, "available": True, "threshold": threshold,
                     "validation_signals": vn, "validation_correct": vtp, "validation_precision": vprecision,
                     "test_signals": len(pred), "test_correct": correct, "test_false": len(pred) - correct,
                     "test_precision": correct / max(len(pred), 1),
                     "test_recall": correct / test.label.sum(), "test_coverage": len(pred) / len(test)})
    result = pd.DataFrame(rows)
    out = ROOT / "outputs" / "event_recognition_v2"; out.mkdir(parents=True, exist_ok=True)
    result.to_csv(out / "precision_ladder.csv", index=False, encoding="utf-8-sig")
    meta = {"selection_rule": "threshold selected only on 2024; maximize correct validation alerts subject to precision floor",
            "test_roc_auc": float(roc_auc_score(test.label.astype(int), test.probability)),
            "test_pr_auc": float(average_precision_score(test.label.astype(int), test.probability)),
            "tiers": rows}
    (out / "precision_ladder.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(result.to_string(index=False))


if __name__ == "__main__": main()
