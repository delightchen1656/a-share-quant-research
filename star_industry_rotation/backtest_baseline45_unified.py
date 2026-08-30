"""Unified local backtests for Baseline 2-1 and 2-2 using Baseline 1-3 conventions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EA = ROOT / "evening_accumulation"
sys.path.insert(0, str(EA))

import research_strategy3 as base  # noqa: E402
from backtest import QFQ_DIR, load_panel  # noqa: E402
from temperature_variants import build_temperature  # noqa: E402


OUT = HERE / "outputs" / "baseline45_local"
VERSIONS = {
    "baseline2-1": "基准2-1：温度进攻",
    "baseline2-2": "基准2-2：升温防守",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prices = load_panel(QFQ_DIR, "close", "2026-07-31")
    amount = load_panel(QFQ_DIR, "amount", "2026-07-31")
    mapping = pd.read_csv(HERE / "industry_map.csv")
    industry = mapping.set_index("symbol").industry.reindex(prices.columns)
    temp, _ = build_temperature(prices, amount, industry)
    prep = joblib.load(HERE / "outputs" / "six_optimized" / "prepared_candidates.joblib")
    original = base.select_candidates
    modes = {"bear_probability", "downside_diversify"}

    def install(version):
        def gated(prep_, signal_date, held, active_modes):
            candidates = original(prep_, signal_date, held, active_modes)
            bear = float(prep_.market_by_date.get(signal_date, {}).get("bear_probability", 0))
            kept = []
            for item in candidates:
                symbol = item["symbol"]
                ind = industry.get(symbol)
                if pd.isna(ind) or signal_date not in temp["heat"].index or ind not in temp["heat"].columns:
                    continue
                heat = float(temp["heat"].loc[signal_date, ind])
                delta = float(temp["delta"].loc[signal_date, ind])
                breadth = float(temp["breadth"].loc[signal_date, ind])
                if version == "baseline2-1":
                    keep = not (heat >= 85 and delta < 0)
                    keep = keep and not (bear >= 0.70 and delta < -5)
                else:
                    keep = delta > 0 or (heat >= 65 and delta > -4 and breadth >= 55)
                if keep:
                    kept.append(dict(item))
            return kept
        base.select_candidates = gated

    full_rows, yearly_rows, start_rows = [], [], []
    for version, name in VERSIONS.items():
        install(version)
        result, curve, trades = base.simulate(prep, modes)
        full_rows.append({"variant": version, "name": name, **result})
        curve.to_csv(OUT / f"equity_{version}_full_100w.csv", index=False, encoding="utf-8-sig")
        trades.to_csv(OUT / f"trades_{version}_full_100w.csv", index=False, encoding="utf-8-sig")
        for year in range(2020, 2027):
            start = pd.Timestamp(f"{year}-01-01")
            year_end = pd.Timestamp(f"{year}-12-31") if year < 2026 else base.END
            annual, _, _ = base.simulate(prep, modes, start, year_end, initial_cash=1_000_000.0)
            yearly_rows.append({"variant": version, "name": name, "year": year, **annual})
            continuous, _, _ = base.simulate(prep, modes, start, base.END, initial_cash=1_000_000.0)
            start_rows.append({"variant": version, "name": name, "start_year": year, **continuous})
        print(version, result["annualized_return"], result["max_drawdown"])
    base.select_candidates = original
    pd.DataFrame(full_rows).to_csv(OUT / "full_period_100w.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(yearly_rows).to_csv(OUT / "independent_yearly_100w.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(start_rows).to_csv(OUT / "start_year_to_20260731_100w.csv", index=False, encoding="utf-8-sig")
    (OUT / "metadata.json").write_text(json.dumps({
        "initial_cash": 1_000_000, "end": "2026-07-31",
        "base": "baseline1-3", "versions": VERSIONS,
        "execution": "research_strategy3 daily realistic simulator",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
