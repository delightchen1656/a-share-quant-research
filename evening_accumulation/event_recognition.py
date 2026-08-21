"""Pure event-recognition test: learn 60-day setups before independent +30% rallies."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features

ROOT = Path(__file__).resolve().parent
HORIZON = 40
TARGET = .30
COOLDOWN = 60


def label_and_event(ds):
    """Label anchors whose later high reaches +30%; merge overlapping anchors into events."""
    labels = pd.Series(np.nan, index=ds.index, dtype=float)
    event_ids = pd.Series(pd.NA, index=ds.index, dtype="Int64")
    events = []; next_event = 1
    for symbol, g in ds.groupby("symbol", sort=False):
        g = g.sort_values("date"); idx = g.index.to_numpy(); c = g.close.to_numpy(); h = g.high.to_numpy()
        y = np.full(len(g), np.nan); hit_day = np.full(len(g), -1, dtype=int)
        for i in range(len(g) - HORIZON):
            hits = np.flatnonzero(h[i + 1:i + HORIZON + 1] >= c[i] * (1 + TARGET))
            y[i] = float(len(hits) > 0)
            if len(hits): hit_day[i] = i + 1 + hits[0]
        labels.loc[idx] = y
        positive = np.flatnonzero(y == 1)
        if not len(positive): continue
        # Consecutive qualifying anchors usually describe the same later rally.
        groups = np.split(positive, np.flatnonzero(np.diff(positive) > 1) + 1)
        last_peak = -COOLDOWN
        for anchors in groups:
            peak = int(max(hit_day[anchors]))
            if peak - last_peak < COOLDOWN: continue
            eid = next_event; next_event += 1; last_peak = peak
            event_ids.loc[idx[anchors]] = eid
            events.append({"event_id": eid, "symbol": symbol,
                           "setup_start": g.iloc[int(anchors[0])].date,
                           "last_signal_date": g.iloc[int(anchors[-1])].date,
                           "target_date": g.iloc[peak].date,
                           "anchor_days": len(anchors)})
    return labels, event_ids, pd.DataFrame(events)


def new_model():
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=.04, max_leaf_nodes=15,
        l2_regularization=3, class_weight="balanced", random_state=42)


def choose_threshold(y, p):
    """Choose on 2024 only: maximize F1, requiring at least 10% precision."""
    precision, recall, thresholds = precision_recall_curve(y, p)
    f1 = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    f1[precision[:-1] < .10] = -1
    i = int(np.nanargmax(f1))
    return float(thresholds[i]), float(precision[i]), float(recall[i]), float(f1[i])


def metrics(rows, threshold):
    y = rows.event_label.astype(int).to_numpy(); p = rows.probability.to_numpy(); pred = p >= threshold
    tp = int((pred & (y == 1)).sum()); fp = int((pred & (y == 0)).sum()); fn = int((~pred & (y == 1)).sum())
    return {"samples": len(rows), "positive_anchor_days": int(y.sum()), "signals": int(pred.sum()),
            "true_positive_days": tp, "false_positive_days": fp,
            "day_precision": tp / max(tp + fp, 1), "day_recall": tp / max(tp + fn, 1),
            "roc_auc": float(roc_auc_score(y, p)), "pr_auc": float(average_precision_score(y, p))}


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    _, qfq = load_panel(ROOT, "star")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["event_label"], ds["event_id"], events = label_and_event(ds)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["event_label"])

    # 2024 is threshold validation; labels are purged so their outcome remains inside each period.
    fit = ds[ds.date <= "2023-11-20"]
    validation = ds[(ds.date >= "2024-01-01") & (ds.date <= "2024-11-20")].copy()
    m0 = new_model(); m0.fit(fit[FEATURES], fit.event_label.astype(int))
    validation["probability"] = m0.predict_proba(validation[FEATURES])[:, 1]
    threshold, val_precision, val_recall, val_f1 = choose_threshold(validation.event_label.astype(int), validation.probability)

    train = ds[ds.date <= "2024-11-20"]
    test = ds[(ds.date >= "2025-01-01") & (ds.date <= "2026-06-01")].copy()
    model = new_model(); model.fit(train[FEATURES], train.event_label.astype(int))
    test["probability"] = model.predict_proba(test[FEATURES])[:, 1]
    summary = metrics(test, threshold)
    summary.update({"definition": "future 40 trading-day high >= anchor close * 1.30; overlapping anchors merged; 60-day event cooldown",
                    "feature_window_days": 60, "train_start": str(train.date.min().date()),
                    "train_end": str(train.date.max().date()), "test_start": str(test.date.min().date()),
                    "test_end": str(test.date.max().date()), "threshold_from_2024": threshold,
                    "validation_precision": val_precision, "validation_recall": val_recall, "validation_f1": val_f1})

    test_events = events[(events.setup_start >= pd.Timestamp("2025-01-01")) &
                         (events.target_date <= pd.Timestamp("2026-07-31"))].copy()
    event_scores = test.dropna(subset=["event_id"]).groupby("event_id").probability.max()
    test_events["max_probability"] = test_events.event_id.map(event_scores)
    test_events["recognized"] = test_events.max_probability.ge(threshold)
    summary["independent_rally_events"] = len(test_events)
    summary["recognized_events"] = int(test_events.recognized.sum())
    summary["missed_events"] = int((~test_events.recognized).sum())
    summary["event_recall"] = float(test_events.recognized.mean()) if len(test_events) else None

    out = ROOT / "outputs" / "event_recognition"; out.mkdir(parents=True, exist_ok=True)
    test[["date", "symbol", "event_label", "event_id", "probability"]].to_csv(
        out / "test_daily_scores.csv", index=False, encoding="utf-8-sig")
    test_events.to_csv(out / "test_events.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    joblib.dump({"model": model, "features": FEATURES, "threshold": threshold,
                 "definition": summary["definition"]}, out / "event_model.joblib")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
