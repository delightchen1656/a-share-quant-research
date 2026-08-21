"""Rounds 31-40: model families, calibration, return ranking and walk-forward."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import (ExtraTreesClassifier, ExtraTreesRegressor,
                              HistGradientBoostingClassifier, HistGradientBoostingRegressor,
                              RandomForestClassifier)
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, add_benchmark_metrics, portfolio_backtest, triple_barrier_label

ROOT = Path(__file__).resolve().parent


def trade_return_label(ds, horizon=60, stop=.06, tp1=.20, tp2=.30):
    result = pd.Series(np.nan, index=ds.index, dtype=float)
    for _, g in ds.groupby("symbol", sort=False):
        idx = g.index.to_numpy(); c = g.close.to_numpy(); h = g.high.to_numpy(); lo = g.low.to_numpy()
        y = np.full(len(g), np.nan)
        for i in range(len(g) - horizon):
            half = False; value = None
            for j in range(i + 1, i + horizon + 1):
                if lo[j] <= c[i] * (1 - stop):
                    value = -stop if not half else .5 * tp1 - .5 * stop; break
                if h[j] >= c[i] * (1 + tp2):
                    value = tp2 if not half else .5 * tp1 + .5 * tp2; break
                if not half and h[j] >= c[i] * (1 + tp1): half = True
            if value is None:
                tail = np.clip(c[i + horizon] / c[i] - 1, -.30, .50)
                value = tail if not half else .5 * tp1 + .5 * tail
            y[i] = value
        result.loc[idx] = y
    return result


def hgbc(seed=42):
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=.04, max_leaf_nodes=15,
        l2_regularization=3, class_weight="balanced", random_state=seed)


def evaluate(name, score, te, threshold, raw, benchmark, cfg, out, results, model=None, note=""):
    scored = te.copy(); scored["probability"] = score
    trial = Trial(name, threshold, 15, .04, 300, 3, 8, 12)
    stats, curve, trades = portfolio_backtest(raw, scored, cfg, trial, benchmark)
    stats, comparison = add_benchmark_metrics(stats, curve, benchmark)
    stats.update({"round": name, "direction": note, "threshold": threshold})
    stats["robust_score"] = stats["geometric_excess_annualized"] + .05 * stats["information_ratio"] \
        - .5 * max(0., -stats["max_drawdown"] - .20)
    results.append(stats)
    curve.to_csv(out / f"{name}_equity.csv", index=False)
    comparison.to_csv(out / f"{name}_benchmark.csv", index=False)
    trades.to_csv(out / f"{name}_trades.csv", index=False)
    if model is not None: joblib.dump(model, out / f"{name}.joblib")
    print(json.dumps(stats, ensure_ascii=False), flush=True)


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    benchmark = pd.read_parquet(ROOT / "data" / "benchmark" / "000688.SH.parquet").sort_values("date")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["barrier"] = triple_barrier_label(ds, 40, .06, .30)
    ds["trade_return"] = trade_return_label(ds)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES)
    train = ds[(ds.date <= "2024-10-31") & ds.barrier.notna()]
    fit = train[train.date <= "2023-12-31"]; cal = train[train.date >= "2024-03-01"]
    test = ds[ds.date >= "2025-01-01"].copy()
    out = ROOT / "outputs" / "star_10rounds_v4"; out.mkdir(parents=True, exist_ok=True)
    results = []; class_scores = {}

    models = [
        ("r31_extra_trees", ExtraTreesClassifier(n_estimators=180, min_samples_leaf=20, max_features=.7,
            class_weight="balanced", n_jobs=-1, random_state=42), "ExtraTrees"),
        ("r32_random_forest", RandomForestClassifier(n_estimators=180, min_samples_leaf=20, max_features=.7,
            class_weight="balanced_subsample", n_jobs=-1, random_state=42), "RandomForest"),
        ("r33_logistic", make_pipeline(StandardScaler(), LogisticRegression(C=.2, class_weight="balanced",
            max_iter=500, random_state=42)), "standardized logistic"),
    ]
    for name, m, note in models:
        m.fit(train[FEATURES], train.barrier.astype(int)); p = m.predict_proba(test[FEATURES])[:, 1]
        class_scores[name] = p
        evaluate(name, p, test, .62, raw, benchmark, cfg, out, results,
                 {"model": m, "features": FEATURES, "config": cfg}, note)

    # Calibration uses a separated 2024 block; .05 is an economic probability floor, not a threshold grid.
    base = hgbc(); base.fit(fit[FEATURES], fit.barrier.astype(int))
    cp = base.predict_proba(cal[FEATURES])[:, 1]; tp = base.predict_proba(test[FEATURES])[:, 1]
    platt = LogisticRegression(C=1).fit(cp.reshape(-1, 1), cal.barrier.astype(int))
    p_platt = platt.predict_proba(tp.reshape(-1, 1))[:, 1]
    evaluate("r34_platt", p_platt, test, .05, raw, benchmark, cfg, out, results,
             {"model": base, "calibrator": platt, "features": FEATURES}, "Platt calibrated")
    iso = IsotonicRegression(out_of_bounds="clip").fit(cp, cal.barrier.astype(int))
    p_iso = iso.predict(tp)
    evaluate("r35_isotonic", p_iso, test, .05, raw, benchmark, cfg, out, results,
             {"model": base, "calibrator": iso, "features": FEATURES}, "isotonic calibrated")

    rtrain = train.dropna(subset=["trade_return"])
    reg1 = HistGradientBoostingRegressor(max_iter=300, learning_rate=.04, max_leaf_nodes=15,
                                         l2_regularization=3, loss="absolute_error", random_state=42)
    reg1.fit(rtrain[FEATURES], rtrain.trade_return); er1 = reg1.predict(test[FEATURES])
    evaluate("r36_hgb_expected_return", er1, test, 0., raw, benchmark, cfg, out, results,
             {"model": reg1, "features": FEATURES}, "direct expected return")
    reg2 = ExtraTreesRegressor(n_estimators=180, min_samples_leaf=20, max_features=.7, n_jobs=-1, random_state=42)
    reg2.fit(rtrain[FEATURES], rtrain.trade_return); er2 = reg2.predict(test[FEATURES])
    evaluate("r37_et_expected_return", er2, test, 0., raw, benchmark, cfg, out, results,
             {"model": reg2, "features": FEATURES}, "ExtraTrees expected return")

    base_all = hgbc(); base_all.fit(train[FEATURES], train.barrier.astype(int)); bp = base_all.predict_proba(test[FEATURES])[:, 1]
    joint = bp * np.maximum(er1, 0)
    evaluate("r38_probability_x_return", joint, test, .002, raw, benchmark, cfg, out, results, None,
             "probability times expected return")
    agreement = (bp + class_scores["r31_extra_trees"] + class_scores["r33_logistic"]) / 3
    evaluate("r39_model_consensus", agreement, test, .62, raw, benchmark, cfg, out, results, None,
             "three-family consensus")

    # Expanding quarterly walk-forward; every fit is purged 90 calendar days before its prediction quarter.
    wf = pd.Series(np.nan, index=test.index)
    for start in pd.date_range("2025-01-01", "2026-07-01", freq="QS"):
        end = start + pd.offsets.QuarterEnd(0)
        block = test[(test.date >= start) & (test.date <= end)]
        cutoff = start - pd.Timedelta(days=90)
        tr = ds[(ds.date < cutoff) & ds.barrier.notna()]
        m = hgbc(); m.fit(tr[FEATURES], tr.barrier.astype(int))
        wf.loc[block.index] = m.predict_proba(block[FEATURES])[:, 1]
    valid = wf.notna()
    evaluate("r40_quarterly_walkforward", wf[valid].to_numpy(), test.loc[valid], .62,
             raw, benchmark, cfg, out, results, None, "quarterly expanding walk-forward")

    table = pd.DataFrame(results).sort_values("robust_score", ascending=False)
    table.to_csv(out / "rounds.csv", index=False, encoding="utf-8-sig")
    (out / "best.json").write_text(json.dumps(table.iloc[0].to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRANKING\n", table.to_string(index=False))


if __name__ == "__main__": main()
