"""Year-by-year reset and continuous-capital tests for the three event tiers."""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, portfolio_backtest

ROOT = Path(__file__).resolve().parent
TIERS = {
    "standard": {"threshold": .739688, "max_positions": 14},
    "conservative": {"threshold": .824097, "max_positions": 11},
    "ultra": {"threshold": .879210, "max_positions": 9},
}


def run_period(raw, scored, cfg, name, params, start, end):
    local = dict(cfg); local["initial_cash"] = 1_000_000
    trial = Trial(name, params["threshold"], 15, .04, 300, 3, 8, params["max_positions"])
    stats, curve, trades = portfolio_backtest(raw, scored, local, trial, None, start, end)
    if not stats:
        stats = {"annualized_return": 0., "total_return": 0., "max_drawdown": 0.,
                 "final_equity": 1_000_000., "trades": 0, "signals": 0, "peak_positions": 0}
        curve = pd.DataFrame(columns=["date", "equity"]); trades = pd.DataFrame()
    return stats, curve, trades


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs" / "event_recognition_v2" / "event_model.joblib")
    ds = features(qfq, cfg); ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES)
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    out = ROOT / "outputs" / "event_yearly_backtests"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for tier, params in TIERS.items():
        for year in range(2015, 2026):
            stats, curve, trades = run_period(raw, ds, cfg, tier, params, f"{year}-01-01", f"{year}-12-31")
            row = {"tier": tier, "mode": "annual_reset", "year": year, **stats}
            rows.append(row)
            curve.to_csv(out / f"{tier}_{year}_equity.csv", index=False)
            trades.to_csv(out / f"{tier}_{year}_trades.csv", index=False, encoding="utf-8-sig")
        stats, curve, trades = run_period(raw, ds, cfg, tier, params, "2015-01-01", "2025-12-31")
        rows.append({"tier": tier, "mode": "continuous", "year": "2015-2025", **stats})
        curve.to_csv(out / f"{tier}_continuous_equity.csv", index=False)
        trades.to_csv(out / f"{tier}_continuous_trades.csv", index=False, encoding="utf-8-sig")
    table = pd.DataFrame(rows)
    table.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(table.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    print(table[["tier", "mode", "year", "final_equity", "total_return", "max_drawdown", "trades", "signals"]].to_string(index=False))


if __name__ == "__main__": main()
