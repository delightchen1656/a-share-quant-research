"""Rounds 11-20: optimize STAR strategy for benchmark-relative robustness."""
import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import precision_score, roc_auc_score

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, add_benchmark_metrics, portfolio_backtest, triple_barrier_label


ROOT = Path(__file__).resolve().parent
TRIALS_V2 = [
    Trial("r11_ma20", .62, 15, .04, 300, 3.0, 8, 12, "above_ma20"),
    Trial("r12_ma60", .62, 15, .04, 300, 3.0, 8, 12, "above_ma60"),
    Trial("r13_trend", .62, 15, .04, 300, 3.0, 8, 12, "trend"),
    Trial("r14_dd10", .62, 15, .04, 300, 3.0, 8, 12, "dd10"),
    Trial("r15_low_vol", .62, 15, .04, 300, 3.0, 8, 12, "low_vol"),
    Trial("r16_reg_alpha", .64, 15, .03, 400, 8.0, 8, 12, "none"),
    Trial("r17_ma20_broad", .60, 15, .04, 300, 3.0, 10, 12, "above_ma20"),
    Trial("r18_ma60_small", .63, 7, .04, 350, 4.0, 8, 10, "above_ma60"),
    Trial("r19_trend_broad", .60, 15, .03, 400, 6.0, 10, 12, "trend"),
    Trial("r20_ma20_precision", .66, 7, .03, 400, 6.0, 6, 10, "above_ma20"),
]


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    benchmark = pd.read_parquet(ROOT / "data" / "benchmark" / "000688.SH.parquet").sort_values("date")
    ds = features(qfq, cfg).sort_values(["symbol", "date"]).reset_index(drop=True)
    ds["barrier_label"] = triple_barrier_label(ds, cfg["label_horizon_days"], cfg["stop_loss"], cfg["take_profit_all"])
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES + ["barrier_label"])
    train = ds[ds.date <= pd.Timestamp("2024-10-31")]
    test = ds[ds.date >= pd.Timestamp("2025-01-01")].copy()
    out = ROOT / "outputs" / "star_10rounds_v2"; out.mkdir(parents=True, exist_ok=True)
    results = []
    for trial in TRIALS_V2:
        model = HistGradientBoostingClassifier(max_iter=trial.max_iter, learning_rate=trial.learning_rate,
            max_leaf_nodes=trial.max_leaf_nodes, l2_regularization=trial.l2, class_weight="balanced", random_state=42)
        model.fit(train[FEATURES], train.barrier_label.astype(int))
        train_p = model.predict_proba(train[FEATURES])[:, 1]
        test["probability"] = model.predict_proba(test[FEATURES])[:, 1]
        stats, curve, trades = portfolio_backtest(raw, test, cfg, trial, benchmark)
        stats, comparison = add_benchmark_metrics(stats, curve, benchmark)
        stats.update({"round": trial.name, "regime": trial.regime, "threshold": trial.threshold,
                      "top_per_day": trial.top_per_day, "max_positions": trial.max_positions,
                      "train_auc": float(roc_auc_score(train.barrier_label, train_p)),
                      "train_precision": float(precision_score(train.barrier_label, train_p >= trial.threshold, zero_division=0))})
        # Ranking emphasizes geometric excess and information ratio, with a drawdown penalty above 20%.
        stats["robust_score"] = stats["geometric_excess_annualized"] + 0.05 * stats["information_ratio"] \
            - 0.5 * max(0.0, -stats["max_drawdown"] - 0.20)
        results.append(stats)
        curve.to_csv(out / f"{trial.name}_equity.csv", index=False)
        comparison.to_csv(out / f"{trial.name}_benchmark.csv", index=False)
        trades.to_csv(out / f"{trial.name}_trades.csv", index=False)
        joblib.dump({"model": model, "features": FEATURES, "trial": trial.__dict__, "config": cfg}, out / f"{trial.name}.joblib")
        print(json.dumps(stats, ensure_ascii=False), flush=True)
    table = pd.DataFrame(results).sort_values("robust_score", ascending=False)
    table.to_csv(out / "rounds.csv", index=False, encoding="utf-8-sig")
    (out / "best.json").write_text(json.dumps(table.iloc[0].to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("\nRANKING\n", table.to_string(index=False))


if __name__ == "__main__":
    main()
