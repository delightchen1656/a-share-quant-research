"""在SuperMind对齐撮合口径上进行结构性收益优化。

选择只使用2020-2023开发期与2024验证期；2025-2026/9仅在排名冻结后展示。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import supermind_aligned_backtest as bt


OUT = Path(__file__).resolve().parent / "outputs" / "return_optimization_round_1"

VARIANTS = [
    {"name": "baseline", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "bull_momentum", "bull": (.15,.45,.40), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "bull_balanced", "bull": (.30,.35,.35), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "bull_quality", "bull": (.15,.20,.65), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "bear_deep_reversal", "bull": (.25,.20,.55), "bear": (.55,.30,.15), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "bear_quality", "bull": (.25,.20,.55), "bear": (.30,.15,.55), "ma":120,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "fast_regime_ma80", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":80,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "slow_regime_ma160", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":160,
     "count":20, "buffer":40, "exposure":.95, "cap":1.5},
    {"name": "concentrated_15", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":120,
     "count":15, "buffer":30, "exposure":.95, "cap":1.5},
    {"name": "diversified_25", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":120,
     "count":25, "buffer":50, "exposure":.95, "cap":1.5},
    {"name": "full_exposure", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":40, "exposure":1.00, "cap":1.5},
    {"name": "wide_buffer", "bull": (.25,.20,.55), "bear": (.40,.25,.35), "ma":120,
     "count":20, "buffer":60, "exposure":.95, "cap":1.5},
]


def period(curve: pd.DataFrame, start: str, end: str) -> dict:
    x = curve[curve.date.between(start, end)].sort_values("date")
    first = float(x.equity.iloc[0])
    last = float(x.equity.iloc[-1])
    years = max((x.date.iloc[-1]-x.date.iloc[0]).days/365.25, 1/365.25)
    ret = x.equity.pct_change().dropna()
    dd = x.equity/x.equity.cummax()-1
    return {"annual": (last/first)**(1/years)-1, "return": last/first-1,
            "dd": float(dd.min()), "sharpe": float(np.sqrt(252)*ret.mean()/ret.std())}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    factors = bt.build_factor_cache()
    rank_sets = {}
    union = set()
    for v in VARIANTS:
        ranks = bt.ranked_months(factors, v["bull"], v["bear"], v["ma"])
        rank_sets[v["name"]] = ranks
        for x in ranks.values():
            union.update(x.head(v["buffer"]).symbol)
    panel = bt.load_daily_panel(union)
    rows = []
    curves = []
    trades = []
    for i, v in enumerate(VARIANTS, 1):
        print(f"variant [{i}/{len(VARIANTS)}] {v['name']}", flush=True)
        curve, trade = bt.simulate(rank_sets[v["name"]], bt.ACTIVE_VOLUME_LIMIT,
                                   v["count"], v["buffer"], v["exposure"], v["cap"], panel)
        dev = period(curve, "2020-01-02", "2023-12-31")
        val = period(curve, "2024-01-01", "2024-12-31")
        hold = period(curve, "2025-01-01", "2026-09-11")
        full = bt.metrics(curve, bt.INITIAL_CASH)
        selection_score = .5*dev["annual"] + .5*val["annual"]
        eligible = max(dev["dd"], val["dd"]) >= -.35 and full["max_drawdown"] >= -.35
        rows.append({"name":v["name"], "selection_score":selection_score,
                     "eligible_dd35":eligible,
                     "dev_annual":dev["annual"], "dev_dd":dev["dd"], "dev_sharpe":dev["sharpe"],
                     "val_annual":val["annual"], "val_dd":val["dd"], "val_sharpe":val["sharpe"],
                     "holdout_annual":hold["annual"], "holdout_dd":hold["dd"],
                     "holdout_sharpe":hold["sharpe"], "full_annual":full["annualized_return"],
                     "full_dd":full["max_drawdown"], "full_sharpe":full["sharpe"],
                     "final_equity":full["final_equity"], "avg_holdings":full["average_holdings"],
                     "max_holdings":full["max_holdings"], "parameters":json.dumps(v,ensure_ascii=False)})
        curve["name"] = v["name"]
        trade["name"] = v["name"]
        curves.append(curve)
        trades.append(trade)
    result = pd.DataFrame(rows).sort_values(["eligible_dd35","selection_score"], ascending=False)
    result.to_csv(OUT/"variant_results.csv", index=False, encoding="utf-8-sig")
    pd.concat(curves, ignore_index=True).to_parquet(OUT/"daily_curves.parquet", index=False)
    pd.concat(trades, ignore_index=True).to_parquet(OUT/"trades.parquet", index=False)
    winner = result[result.eligible_dd35].iloc[0]
    (OUT/"winner.json").write_text(winner.to_json(force_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 沪深基准1 收益优化第一轮", "",
             "选择期为2020—2023开发期和2024验证期各占50%；2025—2026/9不参与选择。",
             "最大回撤上限为35%，撮合采用正式5%成交量限制。", "",
             "|排名|方向|开发年化|2024年化|锁定观察年化|全期年化|全期回撤|Sharpe|期末资产|",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for rank, x in enumerate(result.itertuples(), 1):
        lines.append(f"|{rank}|{x.name}|{x.dev_annual:.2%}|{x.val_annual:.2%}|{x.holdout_annual:.2%}|"
                     f"{x.full_annual:.2%}|{x.full_dd:.2%}|{x.full_sharpe:.3f}|{x.final_equity/10000:.2f}万|")
    lines += ["", f"按预先规定选择口径胜出：**{winner['name']}**。",
              "锁定观察期只用于报告，不用于改变胜出方向。"]
    (OUT/"REPORT.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    print(result.to_string(index=False), flush=True)


if __name__ == "__main__":
    main()
