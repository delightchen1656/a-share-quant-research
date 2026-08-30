"""Six frozen temperature-overlay optimizations and 10m start-date tests."""
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

OUT = HERE / "outputs" / "six_optimized"
RULES = {
    "r01_overheat_bear_guard": "收益线1：高温转弱+极端熊市保护",
    "r02_rerank_with_guard": "收益线2：温度概率排序+高温转弱保护",
    "r03_linkage_breadth_guard": "收益线3：行业联动+高温转弱保护",
    "d01_rising_relaxed": "回撤线1：升温为主、强势行业小幅降温仍可入场",
    "d02_breadth_relaxed": "回撤线2：宽度为主、强龙头升温可替代确认",
    "d03_recovery_relaxed": "回撤线3：保留复苏门槛并用温度概率排序",
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prices = load_panel(QFQ_DIR, "close", "2026-07-31")
    amount = load_panel(QFQ_DIR, "amount", "2026-07-31")
    mapping = pd.read_csv(HERE / "industry_map.csv")
    industry = mapping.set_index("symbol").industry.reindex(prices.columns)
    f, _ = build_temperature(prices, amount, industry)
    cache = OUT / "prepared_candidates.joblib"
    if cache.exists():
        prep = joblib.load(cache)
        prep_meta = {"source": "prepared_candidates.joblib"}
    else:
        prep, prep_meta = base.prepare()
        joblib.dump(prep, cache, compress=3)
    original = base.select_candidates

    def industry_values(signal_date, symbol):
        ind = industry.get(symbol)
        if pd.isna(ind) or signal_date not in f["heat"].index or ind not in f["heat"].columns:
            return None
        return ind, {k: float(f[k].loc[signal_date, ind]) for k in
                     ["heat", "delta", "breadth", "volume", "linkage", "leader"]}

    def install(rule):
        def gated(prep_, signal_date, held, modes):
            candidates = original(prep_, signal_date, held, modes)
            bear = float(prep_.market_by_date.get(signal_date, {}).get("bear_probability", 0))
            kept = []
            for item in candidates:
                iv = industry_values(signal_date, item["symbol"])
                if iv is None:
                    continue
                _, x = iv
                if rule == "r01_overheat_bear_guard":
                    keep = not (x["heat"] >= 85 and x["delta"] < 0)
                    keep &= not (bear >= .70 and x["delta"] < -5)
                elif rule == "r02_rerank_with_guard":
                    keep = not (x["heat"] >= 85 and x["delta"] < 0)
                elif rule == "r03_linkage_breadth_guard":
                    keep = x["linkage"] >= 25 and not (x["heat"] >= 85 and x["delta"] < 0)
                elif rule == "d01_rising_relaxed":
                    keep = x["delta"] > 0 or (x["heat"] >= 65 and x["delta"] > -4 and x["breadth"] >= 55)
                elif rule == "d02_breadth_relaxed":
                    keep = x["breadth"] >= 40 or (x["leader"] >= 65 and x["delta"] > 0)
                else:
                    keep = ((25 <= x["heat"] <= 60 and x["delta"] > 2) or x["heat"] > 60)
                if keep:
                    z = dict(item)
                    z["temperature_score"] = z["probability"] + .0008 * x["heat"] + .0004 * x["delta"]
                    kept.append(z)
            if rule in {"r02_rerank_with_guard", "d03_recovery_relaxed"}:
                kept.sort(key=lambda z: z["temperature_score"], reverse=True)
            return kept
        base.select_candidates = gated

    full_rows, start_rows, curves = [], [], {}
    modes = {"bear_probability", "downside_diversify"}
    for rule, description in RULES.items():
        install(rule)
        summary, curve, trades = base.simulate(prep, modes)
        full_rows.append({"variant": rule, "description": description, **summary})
        curves[rule] = curve.set_index("date").equity / base.INITIAL_CASH
        trades.to_csv(OUT / f"trades_{rule}_100w.csv", index=False, encoding="utf-8-sig")
        for year in [2020, 2023, 2026]:
            start = pd.Timestamp(f"{year}-01-01")
            result, c, tr = base.simulate(prep, modes, start, base.END, initial_cash=10_000_000.0)
            start_rows.append({"variant": rule, "description": description, "start_year": year, **result})
            c.to_csv(OUT / f"equity_{rule}_{year}_1000w.csv", index=False, encoding="utf-8-sig")
            tr.to_csv(OUT / f"trades_{rule}_{year}_1000w.csv", index=False, encoding="utf-8-sig")
        print(rule, summary["annualized_return"], summary["max_drawdown"])
    base.select_candidates = original
    full = pd.DataFrame(full_rows).sort_values(["annualized_return", "max_drawdown"], ascending=[False, False])
    starts = pd.DataFrame(start_rows).sort_values(["start_year", "annualized_return"], ascending=[True, False])
    full.to_csv(OUT / "full_period_100w.csv", index=False, encoding="utf-8-sig")
    starts.to_csv(OUT / "start_year_1000w.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(curves).to_csv(OUT / "full_period_equity.csv", encoding="utf-8-sig")
    meta = {"rules": RULES, "base_modes": sorted(modes), "challenge_cagr": .4654,
            "challenge_drawdown": -.2896, "prepared_meta": prep_meta}
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(full.to_string(index=False)); print(starts.to_string(index=False))


if __name__ == "__main__":
    main()
