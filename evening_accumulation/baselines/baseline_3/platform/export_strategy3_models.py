"""Export Strategy 2 stop-risk and Strategy 3 quarterly bear models to portable JSON/B64."""
import base64
import json
import zlib
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from src.data import load_panel


ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
END = pd.Timestamp("2026-07-31")
FEATURES = [
    "mret5", "mret20", "mret60", "mvol20", "breadth1", "breadth20",
    "dispersion", "downside_share", "common_risk", "avg_dd20",
]


def portable(model):
    trees = []
    for stage in model._predictors:
        nodes = stage[0].nodes
        trees.append([{
            "v": float(n["value"]), "f": int(n["feature_idx"]),
            "t": float(n["num_threshold"]), "m": bool(n["missing_go_to_left"]),
            "l": int(n["left"]), "r": int(n["right"]), "leaf": bool(n["is_leaf"]),
        } for n in nodes])
    return {
        "baseline": float(model._baseline_prediction.ravel()[0]),
        "trees": trees,
    }


def encode(payload, name):
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    (HERE / (name + ".json")).write_text(text, encoding="utf-8")
    b64 = base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")
    (HERE / (name + ".b64")).write_text(b64, encoding="ascii")
    return len(text), len(b64)


def export_stop():
    bundle = joblib.load(ROOT / "baselines" / "baseline_2" / "model" / "stop_risk_model.joblib")
    payload = portable(bundle["model"])
    payload.update({
        "format": "portable_hist_gradient_boosting_v1",
        "features": bundle["features"], "threshold": 0.50, "rank_penalty": 0.22,
        "training_end": bundle["training_end"], "label": bundle["label"],
    })
    return encode(payload, "strategy3_stop_risk_model")


def export_bear():
    _, qfq = load_panel(ROOT, "star")
    qfq = qfq[qfq.date <= END]
    px = qfq.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = px.pct_change(fill_method=None)
    mret = rets.mean(axis=1)
    nav = (1.0 + mret.fillna(0.0)).cumprod()
    frame = pd.DataFrame(index=px.index)
    frame["mret5"] = nav.pct_change(5); frame["mret20"] = nav.pct_change(20)
    frame["mret60"] = nav.pct_change(60); frame["mvol20"] = mret.rolling(20).std()
    frame["breadth1"] = (rets > 0).mean(axis=1).rolling(5).mean()
    frame["breadth20"] = (px / px.shift(20) - 1 > 0).mean(axis=1)
    frame["dispersion"] = rets.std(axis=1).rolling(5).mean()
    frame["downside_share"] = (rets < -0.03).mean(axis=1).rolling(5).mean()
    cross_var = rets.var(axis=1).rolling(20).mean()
    frame["common_risk"] = (mret.rolling(20).var() / cross_var.replace(0, np.nan)).clip(0, 1)
    frame["avg_dd20"] = (px / px.rolling(20).max() - 1).mean(axis=1)
    fmin = pd.concat([nav.shift(-i) / nav - 1 for i in range(1, 21)], axis=1).min(axis=1)
    frame["bear"] = (fmin <= -0.10).astype(float); frame.loc[frame.index[-20:], "bear"] = np.nan
    frame = frame.replace([np.inf, -np.inf], np.nan)
    models = []
    for quarter in pd.period_range("2021Q1", "2026Q3", freq="Q"):
        start = quarter.start_time.normalize(); end = min(quarter.end_time.normalize(), END)
        prior = frame.index[frame.index < start]
        if len(prior) <= 20: continue
        purge_end = prior[-21]
        train = frame[(frame.index <= purge_end) & frame.bear.notna()].dropna(subset=FEATURES)
        if len(train) < 180 or train.bear.nunique() < 2: continue
        model = HistGradientBoostingClassifier(
            max_iter=80, learning_rate=0.04, max_leaf_nodes=7,
            l2_regularization=5.0, class_weight="balanced", random_state=91,
        )
        model.fit(train[FEATURES], train.bear.astype(int))
        item = portable(model)
        item.update({"quarter": str(quarter), "start": str(start.date()), "end": str(end.date()),
                     "train_end": str(purge_end.date()), "train_rows": int(len(train))})
        models.append(item)
    payload = {
        "format": "portable_quarterly_bear_models_v1", "features": FEATURES,
        "target": "next20_equal_weight_star_drawdown_le_minus10pct",
        "models": models, "valid_through": "2026-09-30",
        "caps": {"p40": 0.09, "p55": 0.075, "p70": 0.055, "normal": 0.10},
    }
    return encode(payload, "strategy3_bear_models"), len(models)


if __name__ == "__main__":
    print("stop", export_stop())
    print("bear", export_bear())
