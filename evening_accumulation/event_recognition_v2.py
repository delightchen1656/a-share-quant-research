"""Precision-constrained abnormal-rally recognition.

Objective: maximize correct alert dates subject to validation precision >= 20%.
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features

ROOT = Path(__file__).resolve().parent
HORIZON = 20
TARGET = .30
MIN_PRECISION = .20


def make_label(ds):
    label = pd.Series(np.nan, index=ds.index, dtype=float)
    hit_date = pd.Series(pd.NaT, index=ds.index, dtype="datetime64[ns]")
    for _, g in ds.groupby("symbol", sort=False):
        g = g.sort_values("date"); idx = g.index.to_numpy(); c = g.close.to_numpy(); h = g.high.to_numpy()
        y = np.full(len(g), np.nan); hd = np.full(len(g), np.datetime64("NaT"), dtype="datetime64[ns]")
        dates = g.date.to_numpy(dtype="datetime64[ns]")
        for i in range(len(g) - HORIZON):
            hits = np.flatnonzero(h[i + 1:i + HORIZON + 1] >= c[i] * (1 + TARGET))
            y[i] = float(len(hits) > 0)
            if len(hits): hd[i] = dates[i + 1 + hits[0]]
        label.loc[idx] = y; hit_date.loc[idx] = hd
    return label, hit_date


def model():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=.04, max_leaf_nodes=15,
        l2_regularization=3, class_weight="balanced", random_state=42)


def choose_threshold(y, p):
    """Lowest score cutoff meeting precision constraint, thus maximizing true alerts."""
    order = np.argsort(-p); ys = y[order]; ps = p[order]
    tp = np.cumsum(ys); count = np.arange(1, len(ys) + 1); precision = tp / count
    # Only evaluate boundaries between distinct probabilities.
    boundaries = np.r_[ps[:-1] > ps[1:], True]
    valid = np.flatnonzero(boundaries & (precision >= MIN_PRECISION))
    if not len(valid): raise RuntimeError("2024 validation cannot reach 20% precision")
    best = valid[np.argmax(tp[valid])]
    return float(ps[best]), {"signals": int(count[best]), "correct": int(tp[best]),
                             "precision": float(precision[best]), "recall": float(tp[best] / ys.sum())}


def independent_events(rows):
    """Merge contiguous correct anchor dates for the same symbol into one rally event."""
    records = []
    positives = rows[rows.label.eq(1)].sort_values(["symbol", "date"])
    event_id = 0
    for symbol, g in positives.groupby("symbol"):
        pos = rows[rows.symbol.eq(symbol)].sort_values("date").reset_index().reset_index(names="bar_no")
        gp = pos[pos.label.eq(1)]
        groups = (gp.bar_no.diff().fillna(99) > 1).cumsum()
        for _, event in gp.groupby(groups):
            event_id += 1
            records.append({"event_id": event_id, "symbol": symbol,
                            "setup_start": event.date.min(), "setup_end": event.date.max(),
                            "target_date": event.hit_date.max(),
                            "recognized": bool(event.signal.any()),
                            "max_probability": float(event.probability.max())})
    return pd.DataFrame(records)


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _, qfq = load_panel(ROOT, "star")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["label"], ds["hit_date"] = make_label(ds)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["label"])
    fit = ds[ds.date <= "2023-12-01"]
    val = ds[(ds.date >= "2024-01-01") & (ds.date <= "2024-12-01")].copy()
    m0 = model(); m0.fit(fit[FEATURES], fit.label.astype(int))
    val_p = m0.predict_proba(val[FEATURES])[:, 1]
    threshold, val_stats = choose_threshold(val.label.astype(int).to_numpy(), val_p)

    train = ds[ds.date <= "2024-12-01"]
    test = ds[(ds.date >= "2025-01-01") & (ds.date <= "2026-07-01")].copy()
    m = model(); m.fit(train[FEATURES], train.label.astype(int))
    test["probability"] = m.predict_proba(test[FEATURES])[:, 1]
    test["signal"] = test.probability.ge(threshold)
    predicted = test[test.signal]; correct = predicted[predicted.label.eq(1)]
    events = independent_events(test)
    summary = {
        "definition": "from alert close, high reaches +30% within next 20 trading days",
        "objective": "maximize correct alert dates with validation precision >= 20%",
        "features": "previous 60 trading-day price/volume dynamics (18 derived features)",
        "train_start": str(train.date.min().date()), "train_end": str(train.date.max().date()),
        "test_start": str(test.date.min().date()), "test_end": str(test.date.max().date()),
        "threshold_selected_on_2024": threshold, "validation": val_stats,
        "test_eligible_dates": len(test), "test_actual_positive_dates": int(test.label.sum()),
        "test_base_rate": float(test.label.mean()), "test_signal_dates": len(predicted),
        "test_correct_dates": len(correct), "test_false_alert_dates": int(len(predicted) - len(correct)),
        "test_precision": float(predicted.label.mean()) if len(predicted) else None,
        "test_recall": float(len(correct) / max(test.label.sum(), 1)),
        "test_signal_coverage": float(len(predicted) / len(test)),
        "test_roc_auc": float(roc_auc_score(test.label.astype(int), test.probability)),
        "test_pr_auc": float(average_precision_score(test.label.astype(int), test.probability)),
        "independent_events": len(events), "recognized_events": int(events.recognized.sum()),
        "event_recall": float(events.recognized.mean()) if len(events) else None,
    }
    out = ROOT / "outputs" / "event_recognition_v2"; out.mkdir(parents=True, exist_ok=True)
    test[["date", "symbol", "close", "label", "hit_date", "probability", "signal"]].to_csv(
        out / "test_scores.csv", index=False, encoding="utf-8-sig")
    events.to_csv(out / "independent_events.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"model": m, "features": FEATURES, "threshold": threshold,
                 "horizon": HORIZON, "target": TARGET}, out / "event_model.joblib")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
