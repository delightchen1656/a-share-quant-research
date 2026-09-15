"""Test structurally different entry confirmations inside the >=1 event pool."""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import pandas as pd


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_pool_ge1 import load_data, run  # noqa: E402

OUT = HERE / "outputs" / "positive_routes"


def build_routes(market: pd.DataFrame, scores: pd.DataFrame) -> dict[str, pd.DataFrame]:
    cols = ["date", "symbol", "q_ret1", "q_ret20", "q_ret22", "above_ma60", "amount20"]
    f = market[cols].drop_duplicates(["date", "symbol"])
    x = scores.merge(f, on=["date", "symbol"], how="left")
    x["model_rank"] = x.groupby("date").probability.rank(pct=True)
    x["mom_rank"] = x.groupby("date").q_ret20.rank(pct=True)
    x["liq_rank"] = x.groupby("date").amount20.rank(pct=True)
    # Market breadth is known after T close and gates orders on T+1.
    breadth = market.groupby("date").above_ma60.mean().rename("breadth")
    x = x.join(breadth, on="date")
    base = x.above_ma60.fillna(False) & x.q_ret20.notna() & x.q_ret1.notna()

    specs = {
        "R01_trend_breakout": base & x.q_ret20.between(.08, .40) & x.q_ret1.between(.005, .07),
        "R02_controlled_momentum": base & x.q_ret20.between(.03, .18) & x.q_ret1.between(-.015, .04),
        "R03_strong_pullback": base & x.q_ret20.between(.10, .40) & x.q_ret1.between(-.05, -.005),
        "R04_model_trend_confirm": base & x.model_rank.ge(.90) & x.q_ret20.between(.03, .35),
        "R05_model_early_stage": base & x.model_rank.ge(.85) & x.q_ret20.between(0, .15),
        "R06_liquid_momentum": base & x.liq_rank.ge(.60) & x.q_ret20.between(.05, .30),
        "R07_relative_strength": base & x.mom_rank.ge(.90) & x.q_ret20.le(.45),
        "R08_breadth_gated": base & x.breadth.ge(.48) & x.q_ret20.between(.04, .30),
        "R09_defensive_breadth": base & x.breadth.ge(.55) & x.model_rank.ge(.75) & x.q_ret20.between(0, .25),
        "R10_model_breakout_combo": base & x.model_rank.ge(.90) & x.mom_rank.ge(.75) & x.q_ret1.gt(0),
    }
    routes = {}
    for name, mask in specs.items():
        z = x.loc[mask, ["date", "trade_date", "symbol", "probability", "model_rank", "mom_rank"]].copy()
        if name in ("R01_trend_breakout", "R02_controlled_momentum", "R06_liquid_momentum", "R07_relative_strength", "R08_breadth_gated"):
            z["probability"] = x.loc[mask, "mom_rank"] + .25*x.loc[mask, "model_rank"]
        elif name == "R03_strong_pullback":
            z["probability"] = x.loc[mask, "mom_rank"] + .15*x.loc[mask, "model_rank"]
        else:
            z["probability"] = .65*x.loc[mask, "model_rank"] + .35*x.loc[mask, "mom_rank"]
        routes[name] = z
    return routes


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    market, scores = load_data()
    routes = build_routes(market, scores)
    configs = []
    for stop, tp1, tp2, hold, top in itertools.product((.06, .08), (.12, .18), (.25, .35), (15, 25), (1, 2)):
        if tp2 <= tp1: continue
        configs.append({"stop": stop, "tp1": tp1, "tp2": tp2, "max_hold": hold,
                        "top_daily": top, "trail": .08, "weight": .08, "max_positions": 10})
    rows = []
    for name, signal in routes.items():
        for cfg in configs:
            m, _, _ = run(market, signal, "2024-01-01", "2024-12-31", cfg)
            m.update(cfg); m["route"] = name
            m["feasible"] = m["max_drawdown"] >= -.35 and .30 <= m["average_exposure"] <= .80
            m["score"] = m["annual_return"] + .20*m["sharpe"]
            rows.append(m)
        print(name, "done", flush=True)
    design = pd.DataFrame(rows)
    design.to_csv(OUT/"route_parameter_search_2024.csv", index=False, encoding="utf-8-sig")
    candidates = design[design.feasible & design.annual_return.gt(0)]
    if candidates.empty:
        candidates = design[design.annual_return.gt(0)]
    if candidates.empty:
        candidates = design
    winners = candidates.sort_values("score", ascending=False).groupby("route", as_index=False).head(1).head(3)
    final = []
    for row in winners.itertuples():
        cfg = {k:getattr(row,k) for k in ("stop","tp1","tp2","max_hold","top_daily","trail","weight","max_positions")}
        cfg.update({"max_hold":int(cfg["max_hold"]),"top_daily":int(cfg["top_daily"]),"max_positions":int(cfg["max_positions"])})
        for period,start,end in (("design_2024","2024-01-01","2024-12-31"),
                                 ("holdout_2025_2026","2025-01-01","2026-07-31"),
                                 ("continuous","2024-01-01","2026-07-31")):
            m,eq,tr=run(market,routes[row.route],start,end,cfg)
            m.update({"route":row.route,"period":period,**cfg}); final.append(m)
            if period=="continuous":
                eq.to_csv(OUT/f"equity_{row.route}.csv",index=False,encoding="utf-8-sig")
                tr.to_csv(OUT/f"trades_{row.route}.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(final).to_csv(OUT/"winner_backtests.csv",index=False,encoding="utf-8-sig")
    (OUT/"route_definitions.json").write_text(json.dumps({k:len(v) for k,v in routes.items()},indent=2),encoding="utf-8")
    print(pd.DataFrame(final).to_string(index=False))


if __name__ == "__main__": main()
