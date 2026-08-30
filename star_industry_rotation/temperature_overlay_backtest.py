"""Apply ten fixed-industry temperature gates to the frozen Strategy 3 engine."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
EA = ROOT / "evening_accumulation"
BASE = EA / "baselines" / "baseline_3" / "strategy"
sys.path.insert(0, str(EA))

import research_strategy3 as base  # noqa: E402
from backtest import QFQ_DIR, load_panel  # noqa: E402
from temperature_variants import build_temperature  # noqa: E402


OUT = HERE / "outputs" / "temperature_overlay"
RULES = {
    "o01_avoid_frozen": "排除温度低于20的冰冻行业",
    "o02_above_30": "只允许温度不低于30",
    "o03_rising": "只允许10日温度斜率为正",
    "o04_recovery_or_hot": "低温复苏或行业已进入强势区",
    "o05_breadth_gate": "至少40%成分股站上60日均线",
    "o06_linkage_gate": "行业联动温度不低于25",
    "o07_leader_gate": "行业至少存在明确领先股",
    "o08_top_temperature": "只交易温度排名前20个行业",
    "o09_no_overheat_divergence": "排除高温转弱行业",
    "o10_temperature_rerank": "保留候选并按个股概率与行业温度联合排序",
}


def main():
    prices = load_panel(QFQ_DIR, "close", "2026-07-31")
    amount = load_panel(QFQ_DIR, "amount", "2026-07-31")
    mapping = pd.read_csv(HERE / "industry_map.csv")
    industry = mapping.set_index("symbol").industry.reindex(prices.columns)
    f, _ = build_temperature(prices, amount, industry)
    prep, prep_meta = base.prepare()
    original = base.select_candidates
    results, curves = [], {}

    def values(signal_date, symbol):
        ind = industry.get(symbol)
        if pd.isna(ind) or signal_date not in f["heat"].index or ind not in f["heat"].columns:
            return None
        return ind, {k: float(f[k].loc[signal_date, ind]) for k in ["heat", "delta", "breadth", "linkage", "leader"]}

    for rule in RULES:
        def gated(prep_, signal_date, held, modes, rule_=rule):
            candidates = original(prep_, signal_date, held, modes)
            scored = []
            ranks = f["heat"].loc[signal_date].rank(ascending=False, method="min") if signal_date in f["heat"].index else pd.Series(dtype=float)
            for item in candidates:
                iv = values(signal_date, item["symbol"])
                if iv is None:
                    continue
                ind, x = iv
                keep = True
                if rule_ == "o01_avoid_frozen": keep = x["heat"] >= 20
                elif rule_ == "o02_above_30": keep = x["heat"] >= 30
                elif rule_ == "o03_rising": keep = x["delta"] > 0
                elif rule_ == "o04_recovery_or_hot": keep = ((25 <= x["heat"] <= 60 and x["delta"] > 2) or x["heat"] > 60)
                elif rule_ == "o05_breadth_gate": keep = x["breadth"] >= 40
                elif rule_ == "o06_linkage_gate": keep = x["linkage"] >= 25
                elif rule_ == "o07_leader_gate": keep = x["leader"] >= 45
                elif rule_ == "o08_top_temperature": keep = ranks.get(ind, 999) <= 20
                elif rule_ == "o09_no_overheat_divergence": keep = not (x["heat"] >= 85 and x["delta"] < 0)
                if keep:
                    item = dict(item)
                    item["temperature"] = x["heat"]
                    item["temperature_score"] = item["probability"] + .0008 * x["heat"] + .0004 * x["delta"]
                    scored.append(item)
            if rule_ == "o10_temperature_rerank":
                scored.sort(key=lambda z: z["temperature_score"], reverse=True)
            return scored

        base.select_candidates = gated
        summary, curve, trades = base.simulate(prep, {"bear_probability", "downside_diversify"})
        oos, _, _ = base.simulate(prep, {"bear_probability", "downside_diversify"}, pd.Timestamp("2025-01-01"), base.END)
        results.append({"variant": rule, "description": RULES[rule], **summary,
                        "oos_total_return": oos["total_return"], "oos_cagr": oos["annualized_return"],
                        "oos_max_drawdown": oos["max_drawdown"]})
        curves[rule] = curve.set_index("date").equity / base.INITIAL_CASH
        trades.to_csv(OUT / f"trades_{rule}.csv", index=False, encoding="utf-8-sig")
        print(rule, summary["annualized_return"], summary["max_drawdown"], oos["annualized_return"])
    base.select_candidates = original
    ranking = pd.DataFrame(results).sort_values(["annualized_return", "max_drawdown"], ascending=[False, False])
    ranking.to_csv(OUT / "summary.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(curves).to_csv(OUT / "equity.csv", encoding="utf-8-sig")
    meta = {"base_modes": ["bear_probability", "downside_diversify"], "challenge_cagr": .465,
            "challenge_drawdown": -.2896, "preparation": prep_meta}
    (OUT / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ranking.to_string(index=False))


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    main()
