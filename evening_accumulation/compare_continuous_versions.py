"""Continuous 2015-2025 comparison for original 60d, optimized 60d and optimized 30d."""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, portfolio_backtest

ROOT = Path(__file__).resolve().parent
VERSIONS = {
    "original_60d": {"threshold": .739688, "stop_loss": .06, "take_profit_half": .20,
                     "take_profit_all": .30, "max_holding_days": 60},
    "optimized_60d": {"threshold": .699688, "stop_loss": .06, "take_profit_half": .25,
                      "take_profit_all": .30, "max_holding_days": 60},
    "optimized_30d": {"threshold": .689688, "stop_loss": .07, "take_profit_half": .24,
                      "take_profit_all": .34, "max_holding_days": 30},
}


def main():
    cfg0 = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs/event_recognition_v2/event_model.joblib")
    ds = features(qfq, cfg0); ds = ds[eligible(ds, cfg0)].dropna(subset=FEATURES)
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    out = ROOT / "outputs/continuous_version_comparison"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, params in VERSIONS.items():
        cfg = dict(cfg0); cfg.update(params); cfg["initial_cash"] = 1_000_000
        trial = Trial(name, params["threshold"], 15, .04, 300, 3, 8, 14)
        stats, curve, trades = portfolio_backtest(raw, ds, cfg, trial, None, "2015-01-01", "2025-12-31")
        row = {"version": name, **params, **stats}; rows.append(row)
        curve.to_csv(out / f"{name}_equity.csv", index=False)
        trades.to_csv(out / f"{name}_trades.csv", index=False, encoding="utf-8-sig")
    table = pd.DataFrame(rows)
    table.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(table.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    print(table[["version", "final_equity", "total_return", "annualized_return", "max_drawdown", "trades", "signals", "peak_positions"]].to_string(index=False))


if __name__ == "__main__": main()
