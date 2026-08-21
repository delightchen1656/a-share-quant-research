"""Independent annual-reset tests for the current optimized 30-day baseline."""
import json
from pathlib import Path

import joblib
import pandas as pd

from src.data import load_panel
from src.model import FEATURES, eligible, features
from optimize_star import Trial, portfolio_backtest

ROOT = Path(__file__).resolve().parent
PARAMS = {"threshold": .689688, "stop_loss": .07, "take_profit_half": .24,
          "take_profit_all": .34, "max_holding_days": 30}


def main():
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8")); cfg.update(PARAMS)
    cfg["initial_cash"] = 1_000_000
    raw, qfq = load_panel(ROOT, "star")
    bundle = joblib.load(ROOT / "outputs/event_recognition_v2/event_model.joblib")
    ds = features(qfq, cfg); ds = ds[eligible(ds, cfg)].dropna(subset=FEATURES)
    ds["probability"] = bundle["model"].predict_proba(ds[FEATURES])[:, 1]
    trial = Trial("optimized_30d_baseline", PARAMS["threshold"], 15, .04, 300, 3, 8, 14)
    out = ROOT / "outputs/baseline30_yearly"; out.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in range(2020, 2026):
        stats, curve, trades = portfolio_backtest(raw, ds, cfg, trial, None,
                                                   f"{year}-01-01", f"{year}-12-31")
        rows.append({"year": year, **stats})
        curve.to_csv(out / f"{year}_equity.csv", index=False)
        trades.to_csv(out / f"{year}_trades.csv", index=False, encoding="utf-8-sig")
    # 2026 H1: June 30 is the NAV cutoff; July is reserved for event-label verification.
    stats, curve, trades = portfolio_backtest(raw, ds, cfg, trial, None, "2026-01-01", "2026-06-30")
    rows.append({"year": "2026H1", **stats})
    curve.to_csv(out / "2026H1_equity.csv", index=False)
    trades.to_csv(out / "2026H1_trades.csv", index=False, encoding="utf-8-sig")
    table = pd.DataFrame(rows)
    table.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    (out / "summary.json").write_text(table.to_json(orient="records", force_ascii=False, indent=2), encoding="utf-8")
    print(table[["year", "final_equity", "total_return", "annualized_return", "max_drawdown", "trades", "signals", "peak_positions"]].to_string(index=False))


if __name__ == "__main__": main()
