"""Train point-in-time pool models for a 50% rise within the next 10 sessions."""
from __future__ import annotations

import json
import zlib
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
DATA = PROJECT / "data_pipeline" / "data"
FEATURE_DIR = DATA / "derived" / "features"
QFQ = DATA / "qfq"
EVENT_FILE = PROJECT / "studies" / "rapid_rally_10d50" / "outputs" / "event_details.csv"
OUT, MODELS = HERE / "outputs", HERE / "models"
FEATURES = ["ret5", "ret20", "ret60", "range20", "range60", "dd20", "vol20", "vol60",
            "volume_ratio", "volume_cv", "up_volume_share", "pv_corr", "close_pos60", "turn20",
            "amount20", "breakout_gap", "rise_from_low60", "volume_spike"]
POOLS = (1, 3, 5, 10)


def future_label(high: np.ndarray, close: np.ndarray) -> np.ndarray:
    y = np.full(len(close), np.nan)
    if len(close) > 10:
        windows = np.lib.stride_tricks.sliding_window_view(high[1:], 10)
        y[:len(windows)] = (windows.max(axis=1) / close[:len(windows)] - 1 >= .50).astype(float)
    return y


def load_symbol(path: Path, ends: dict[str, np.ndarray]) -> pd.DataFrame:
    x = pd.read_parquet(path, columns=["date", "symbol", "t1_buyable"] + FEATURES)
    x["date"] = pd.to_datetime(x.date)
    symbol = path.stem
    q = pd.read_parquet(QFQ / symbol[-2:] / f"{symbol}.parquet", columns=["date", "high", "close"])
    q["date"] = pd.to_datetime(q.date)
    x = x.merge(q, on="date", how="inner")
    x["label10_50"] = future_label(x.high.to_numpy(float), x.close.to_numpy(float))
    event_ends = ends.get(symbol, np.array([], dtype="datetime64[ns]"))
    x["past_event_count"] = np.searchsorted(event_ends, x.date.to_numpy(), side="right")
    return x


def choose_threshold(frame: pd.DataFrame, prob: np.ndarray) -> tuple[float, dict]:
    z = frame[["date", "label10_50"]].copy()
    z["prob"] = prob
    # Practical signal density: compare top 1/2/3 candidates per trading day.
    choices = []
    for per_day in (1, 2, 3):
        chosen = z.sort_values(["date", "prob"], ascending=[True, False]).groupby("date").head(per_day)
        threshold = float(chosen.prob.min())
        choices.append((float(chosen.label10_50.mean()), int(chosen.label10_50.sum()), per_day, threshold))
    precision, correct, per_day, threshold = max(choices, key=lambda a: (a[0], a[1]))
    return threshold, {"validation_top_per_day": per_day, "validation_signals": int((prob >= threshold).sum()),
                       "validation_precision": precision, "validation_correct_top_daily": correct}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True); MODELS.mkdir(parents=True, exist_ok=True)
    ev = pd.read_csv(EVENT_FILE, parse_dates=["end_date"])
    ends = {s: np.sort(g.end_date.to_numpy(dtype="datetime64[ns]")) for s, g in ev.groupby("symbol")}
    buckets = {p: {"train": [], "valid": [], "test": []} for p in POOLS}
    paths = list(FEATURE_DIR.rglob("*.parquet"))
    for n, path in enumerate(paths, 1):
        x = load_symbol(path, ends)
        base = x.t1_buyable.fillna(False) & x.label10_50.notna() & x[FEATURES].notna().all(axis=1)
        for pool in POOLS:
            eligible = base & x.past_event_count.ge(pool)
            train = x[eligible & x.date.le("2022-12-15")]
            if len(train):
                pos = train[train.label10_50.eq(1)]
                neg = train[train.label10_50.eq(0)]
                cap = min(len(neg), max(50, len(pos) * 15))
                if cap:
                    seed = (zlib.crc32(path.stem.encode()) + pool) & 0xffffffff
                    neg = neg.sample(cap, random_state=seed)
                buckets[pool]["train"].append(pd.concat([pos, neg]))
            for key, lo, hi in (("valid", "2023-01-01", "2023-12-15"),
                                ("test", "2024-01-01", "2026-07-31")):
                part = x[eligible & x.date.ge(lo) & x.date.le(hi)]
                if len(part): buckets[pool][key].append(part)
        if n % 400 == 0: print(f"loaded {n}/{len(paths)}", flush=True)

    report = []
    for pool in POOLS:
        train = pd.concat(buckets[pool]["train"], ignore_index=True) if buckets[pool]["train"] else pd.DataFrame()
        valid = pd.concat(buckets[pool]["valid"], ignore_index=True) if buckets[pool]["valid"] else pd.DataFrame()
        test = pd.concat(buckets[pool]["test"], ignore_index=True) if buckets[pool]["test"] else pd.DataFrame()
        if train.empty or train.label10_50.sum() < 20 or valid.label10_50.nunique() < 2:
            report.append({"pool": f">={pool}", "status": "insufficient", "train_samples": len(train),
                           "train_positives": int(train.label10_50.sum()) if len(train) else 0})
            continue
        model = lgb.LGBMClassifier(n_estimators=350, learning_rate=.035, num_leaves=15, max_depth=5,
                                   min_child_samples=80, subsample=.8, colsample_bytree=.8,
                                   reg_lambda=5, reg_alpha=1, class_weight="balanced", random_state=20260914,
                                   verbosity=-1, n_jobs=8)
        model.fit(train[FEATURES].astype("float32"), train.label10_50.astype(int))
        vp = model.predict_proba(valid[FEATURES].astype("float32"))[:, 1]
        threshold, chosen = choose_threshold(valid, vp)
        tp = model.predict_proba(test[FEATURES].astype("float32"))[:, 1] if len(test) else np.array([])
        scored = test[["date", "symbol", "label10_50", "past_event_count"]].copy()
        scored["probability"] = tp
        scored.to_parquet(OUT / f"scores_pool_ge{pool}_2024_2026.parquet", index=False)
        metrics = {"pool": f">={pool}", "status": "trained", "train_samples": len(train),
                   "train_positives": int(train.label10_50.sum()), "validation_samples": len(valid),
                   "validation_base_rate": float(valid.label10_50.mean()),
                   "validation_roc_auc": float(roc_auc_score(valid.label10_50, vp)),
                   "validation_pr_auc": float(average_precision_score(valid.label10_50, vp)),
                   "threshold": threshold, **chosen, "test_samples": len(test)}
        report.append(metrics)
        joblib.dump({"model": model, "features": FEATURES, "pool_min_events": pool,
                     "threshold": threshold, "metrics": metrics}, MODELS / f"pool_ge{pool}.joblib", compress=3)
        print(json.dumps(metrics, ensure_ascii=False), flush=True)
    pd.DataFrame(report).to_csv(OUT / "model_comparison.csv", index=False, encoding="utf-8-sig")
    (OUT / "model_comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
