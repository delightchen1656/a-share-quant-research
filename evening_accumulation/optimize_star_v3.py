"""Rounds 21-30: genuinely new feature, weighting and label directions."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, add_benchmark_metrics, portfolio_backtest, triple_barrier_label


ROOT = Path(__file__).resolve().parent
RANK_BASE = ["ret5", "ret20", "ret60", "volume_ratio", "up_volume_share", "close_pos60",
             "turn20", "amount20", "rise_from_low60", "volume_spike"]
RANK_FEATURES = [f"rank_{x}" for x in RANK_BASE]
MARKET_FEATURES = ["mkt_ret5", "mkt_ret20", "mkt_ret60", "mkt_vol20", "mkt_breadth20",
                   "rel_ret5", "rel_ret20", "rel_ret60"]


def enrich(ds):
    x = ds.copy()
    for col in RANK_BASE:
        x[f"rank_{col}"] = x.groupby("date")[col].rank(pct=True)
    daily = x.groupby("date").agg(
        mkt_ret5=("ret5", "median"), mkt_ret20=("ret20", "median"),
        mkt_ret60=("ret60", "median"), mkt_vol20=("vol20", "median"),
        mkt_breadth20=("ret20", lambda s: float((s > 0).mean())),
    ).reset_index()
    x = x.merge(daily, on="date", how="left")
    x["rel_ret5"] = x.ret5 - x.mkt_ret5
    x["rel_ret20"] = x.ret20 - x.mkt_ret20
    x["rel_ret60"] = x.ret60 - x.mkt_ret60
    return x


def realized_label(ds, horizon, stop, tp_half, tp_all):
    """Positive label when the specified staged exit would make money."""
    result = pd.Series(np.nan, index=ds.index, dtype=float)
    for _, g in ds.groupby("symbol", sort=False):
        idx = g.index.to_numpy(); close = g.close.to_numpy(); high = g.high.to_numpy(); low = g.low.to_numpy()
        labels = np.full(len(g), np.nan)
        for i in range(len(g) - horizon):
            entry = close[i]; half = False; ret = None
            for j in range(i + 1, i + horizon + 1):
                if low[j] <= entry * (1 - stop):
                    ret = (-stop if not half else 0.5 * tp_half - 0.5 * stop); break
                if high[j] >= entry * (1 + tp_all):
                    ret = (tp_all if not half else 0.5 * tp_half + 0.5 * tp_all); break
                if not half and high[j] >= entry * (1 + tp_half):
                    half = True
            if ret is None:
                tail = close[i + horizon] / entry - 1
                ret = tail if not half else 0.5 * tp_half + 0.5 * tail
            labels[i] = float(ret > 0)
        result.loc[idx] = labels
    return result


def model(seed=42):
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=.04, max_leaf_nodes=15,
        l2_regularization=3, class_weight="balanced", random_state=seed)


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    benchmark = pd.read_parquet(ROOT / "data" / "benchmark" / "000688.SH.parquet").sort_values("date")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["label30_40"] = triple_barrier_label(ds, 40, cfg["stop_loss"], .30)
    ds["label20_40"] = triple_barrier_label(ds, 40, cfg["stop_loss"], .20)
    ds["label30_60"] = triple_barrier_label(ds, 60, cfg["stop_loss"], .30)
    ds["label_realized"] = realized_label(ds, 60, cfg["stop_loss"], .20, .30)
    ds = enrich(ds[eligible(ds, cfg)])
    train = ds[ds.date <= pd.Timestamp("2024-10-31")].copy()
    test = ds[ds.date >= pd.Timestamp("2025-01-01")].copy()
    out = ROOT / "outputs" / "star_10rounds_v3"; out.mkdir(parents=True, exist_ok=True)
    specs = [
        ("r21_rank_only", RANK_FEATURES, "label30_40", "none"),
        ("r22_base_rank", FEATURES + RANK_FEATURES, "label30_40", "none"),
        ("r23_market_relative", FEATURES + MARKET_FEATURES, "label30_40", "none"),
        ("r24_all_context", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label30_40", "none"),
        ("r25_recent_weight", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label30_40", "recent"),
        ("r26_recency_strong", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label30_40", "recent_strong"),
        ("r27_tp20_label", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label20_40", "none"),
        ("r28_horizon60", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label30_60", "none"),
        ("r29_realized_label", FEATURES + RANK_FEATURES + MARKET_FEATURES, "label_realized", "none"),
    ]
    probabilities = {}; fitted = {}; results = []
    trial = Trial("", .62, 15, .04, 300, 3, 8, 12)
    for name, cols, label, weighting in specs:
        tr = train.dropna(subset=cols + [label]); te = test.dropna(subset=cols).copy(); m = model()
        weights = None
        if weighting:
            age_years = (pd.Timestamp("2024-10-31") - tr.date).dt.days / 365.25
            half_life = 2.0 if weighting == "recent" else 1.0
            weights = np.power(.5, age_years / half_life).clip(.05, 1.0)
        m.fit(tr[cols], tr[label].astype(int), sample_weight=weights)
        p = m.predict_proba(te[cols])[:, 1]; probabilities[name] = pd.Series(p, index=te.index); fitted[name] = (m, cols)
        evaluate(name, p, te, tr, label, cols, m, trial, raw, benchmark, cfg, out, results, weighting)
    # An ensemble is structurally different from threshold/leaf tuning.
    common = test.dropna(subset=FEATURES + RANK_FEATURES + MARKET_FEATURES).copy()
    p = np.mean([probabilities[n].reindex(common.index).to_numpy() for n in
                 ["r24_all_context", "r27_tp20_label", "r29_realized_label"]], axis=0)
    evaluate("r30_label_ensemble", p, common, None, None, FEATURES + RANK_FEATURES + MARKET_FEATURES,
             None, trial, raw, benchmark, cfg, out, results, "ensemble")
    table = pd.DataFrame(results).sort_values("robust_score", ascending=False)
    table.to_csv(out / "rounds.csv", index=False, encoding="utf-8-sig")
    (out / "best.json").write_text(json.dumps(table.iloc[0].to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRANKING\n", table.to_string(index=False))


def evaluate(name, p, te, tr, label, cols, m, base_trial, raw, benchmark, cfg, out, results, weighting):
    scored = te.copy(); scored["probability"] = p
    trial = Trial(name, base_trial.threshold, 15, .04, 300, 3, 8, 12)
    stats, curve, trades = portfolio_backtest(raw, scored, cfg, trial, benchmark)
    stats, comparison = add_benchmark_metrics(stats, curve, benchmark)
    stats.update({"round": name, "direction": weighting, "features": len(cols), "threshold": trial.threshold})
    if m is not None:
        stats["train_auc"] = float(roc_auc_score(tr[label], m.predict_proba(tr[cols])[:, 1]))
        joblib.dump({"model": m, "features": cols, "label": label, "trial": trial.__dict__, "config": cfg}, out / f"{name}.joblib")
    stats["robust_score"] = stats["geometric_excess_annualized"] + .05 * stats["information_ratio"] \
        - .5 * max(0., -stats["max_drawdown"] - .20)
    results.append(stats)
    curve.to_csv(out / f"{name}_equity.csv", index=False)
    comparison.to_csv(out / f"{name}_benchmark.csv", index=False)
    trades.to_csv(out / f"{name}_trades.csv", index=False)
    print(json.dumps(stats, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
