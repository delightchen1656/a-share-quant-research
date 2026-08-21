"""Backtest the standard/conservative/ultra-conservative event signal tiers."""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, add_benchmark_metrics, portfolio_backtest

ROOT = Path(__file__).resolve().parent
TIERS = {
    "standard_30": 0.739688,
    "conservative_70": 0.824097,
    "ultra_95": 0.879210,
}


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    benchmark = pd.read_parquet(ROOT / "data" / "benchmark" / "000688.SH.parquet").sort_values("date")
    bundle = joblib.load(ROOT / "outputs" / "event_recognition_v2" / "event_model.joblib")
    ds = features(qfq, cfg)
    ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES)
    # Match the untouched event-recognition test window; later bars remain available for exits.
    scored = ds[(ds.date >= "2025-01-01") & (ds.date <= "2026-07-01")].copy()
    scored["probability"] = bundle["model"].predict_proba(scored[FEATURES])[:, 1]
    out = ROOT / "outputs" / "event_tier_backtests"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, threshold in TIERS.items():
        discovery = Trial(name + "_discovery", threshold, 15, .04, 300, 3, 8, 999)
        discovery_stats, _, _ = portfolio_backtest(raw, scored, cfg, discovery, benchmark)
        dynamic_limit = int(discovery_stats["peak_positions"]) + 1
        trial = Trial(name, threshold, 15, .04, 300, 3, 8, dynamic_limit)
        stats, curve, trades = portfolio_backtest(raw, scored, cfg, trial, benchmark)
        stats, comparison = add_benchmark_metrics(stats, curve, benchmark)
        stats.update({"tier": name, "threshold": threshold,
                      "raw_signal_dates": int((scored.probability >= threshold).sum()),
                      "discovered_peak_positions": int(discovery_stats["peak_positions"]),
                      "configured_max_positions": dynamic_limit})
        stats.update({
            "closed_trades": int(len(trades)),
            "stop_exits": int(trades.reason.eq("STOP").sum()) if len(trades) else 0,
            "tp20_triggered_trades": int(trades.tp20_triggered.sum()) if len(trades) else 0,
            "tp30_exits": int(trades.reason.eq("TP30").sum()) if len(trades) else 0,
            "time_exits": int(trades.reason.eq("TIME").sum()) if len(trades) else 0,
        })
        rows.append(stats)
        curve.to_csv(out / f"{name}_equity.csv", index=False)
        comparison.to_csv(out / f"{name}_benchmark.csv", index=False)
        trades.to_csv(out / f"{name}_trades.csv", index=False, encoding="utf-8-sig")
        print(json.dumps(stats, ensure_ascii=False), flush=True)
    table = pd.DataFrame(rows).sort_values("annualized_return", ascending=False)
    table.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n", table.to_string(index=False))


if __name__ == "__main__": main()
