"""Public-research inspired, low-turnover Sharpe routes on the >=1 rally pool.

No route is tuned on the 2025-2026 holdout.  Signals use T close and trade at
T+1 open through the existing realistic A-share execution engine.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from backtest_pool_ge1 import load_data, run  # noqa: E402

FEATURES = HERE / "outputs" / "trend_models" / "trend_scores_2024_2026.parquet"
OUT = HERE / "outputs" / "public_sharpe_routes"


def rank(x, col, ascending=True):
    return x.groupby("date")[col].rank(pct=True, ascending=ascending)


def make_signal(x, mask, score, schedule, sizing, exposure):
    use = mask & x.date.isin(schedule)
    s = x.loc[use, ["date", "trade_date", "symbol", "vol60"]].copy()
    s["probability"] = score.loc[use]
    s = s.sort_values(["date", "probability"], ascending=[True, False])
    s = s.groupby("date", group_keys=False).head(12)
    if sizing == "inverse_vol":
        s["raw_weight"] = 1.0 / s.vol60.clip(lower=.008)
        # Cap any one name at twice equal-risk weight before normalisation.
        s["raw_weight"] = s.groupby("date").raw_weight.transform(
            lambda z: z.clip(upper=z.median() * 2.0)
        )
        s["target_weight"] = s.raw_weight / s.groupby("date").raw_weight.transform("sum")
        s["target_weight"] *= s.date.map(exposure)
    else:
        s["target_weight"] = s.date.map(exposure) / s.groupby("date").symbol.transform("count")
    return s[["date", "trade_date", "symbol", "probability", "target_weight"]]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    market, _ = load_data()
    x = pd.read_parquet(FEATURES)
    x.date = pd.to_datetime(x.date)
    cal = np.array(sorted(market.date.unique()), dtype="datetime64[ns]")
    ix = np.searchsorted(cal, x.date.to_numpy(dtype="datetime64[ns]"), side="right")
    good = ix < len(cal)
    x = x.loc[good].copy()
    x["trade_date"] = cal[ix[good]]

    for c in ("ret5", "ret20", "ret60", "vol20", "vol60", "up_volume_share",
              "amount20", "turn20", "dd20", "close_pos60", "pv_corr"):
        x[c + "_rank"] = rank(x, c)
    x["mom_skip20"] = x.ret60 - x.ret20
    x["mom_skip_rank"] = rank(x, "mom_skip20")
    x["ramom"] = x.mom_skip20 / (x.vol60 * np.sqrt(60) + 1e-6)
    x["ramom_rank"] = rank(x, "ramom")
    x["downside_quality"] = .55 * (1 - x.vol60_rank) + .45 * (1 - x.dd20_rank)

    # Point-in-time equal-weight market state; no future observations.
    daily = x.groupby("date").agg(breadth=("ret60", lambda z: float((z > 0).mean())),
                                   market_ret=("ret5", "median")).sort_index()
    daily["stress"] = (daily.breadth < .40) | (daily.market_ret < -.05)
    full = pd.Series(.70, index=daily.index)
    vol_target = pd.Series(np.where(daily.stress, .35, .70), index=daily.index)

    routes = {
        "P1_跳月动量逆波动": (x.mom_skip20.gt(0) & x.vol60_rank.le(.65),
                             .70*x.mom_skip_rank + .30*(1-x.vol60_rank), "inverse_vol", full),
        "P2_跳月动量短反转": (x.mom_skip20.gt(0) & x.ret5.between(-.08, .04),
                             .55*x.mom_skip_rank + .25*(1-x.ret5_rank) + .20*(1-x.vol60_rank), "inverse_vol", full),
        "P3_低波量价逆波动": (x.ret60.gt(0) & x.vol20_rank.le(.50) & x.up_volume_share.ge(.50),
                             .40*x.ramom_rank + .35*(1-x.vol20_rank) + .25*x.up_volume_share_rank, "inverse_vol", full),
        "P4_下行质量动量": (x.mom_skip20.gt(0) & x.downside_quality.ge(.55),
                           .45*x.mom_skip_rank + .35*x.downside_quality + .20*x.amount20_rank, "inverse_vol", full),
        "P5_拥挤惩罚": (x.mom_skip20.gt(0) & x.turn20_rank.le(.70) & x.pv_corr_rank.le(.75),
                       .45*x.ramom_rank + .25*(1-x.turn20_rank) + .20*(1-x.pv_corr_rank)+.10*x.amount20_rank, "inverse_vol", full),
        "P6_压力降仓低波量价": (x.ret60.gt(0) & x.vol20_rank.le(.50) & x.up_volume_share.ge(.50),
                               .40*x.ramom_rank + .35*(1-x.vol20_rank) + .25*x.up_volume_share_rank, "inverse_vol", vol_target),
        "P7_压力降仓下行质量": (x.mom_skip20.gt(0) & x.downside_quality.ge(.55),
                               .45*x.mom_skip_rank + .35*x.downside_quality + .20*x.amount20_rank, "inverse_vol", vol_target),
        "P8_低波52日高位": (x.ret60.gt(0) & x.vol60_rank.le(.45) & x.close_pos60.ge(.65),
                           .45*x.close_pos60_rank + .35*(1-x.vol60_rank)+.20*x.up_volume_share_rank, "inverse_vol", full),
    }
    dates = sorted(x.date.unique())
    schedule = set(dates[::20])
    cfg = {"stop": .12, "tp1": 9., "tp2": 10., "max_hold": 45,
           "top_daily": 12, "trail": .99, "weight": .07, "max_positions": 12}
    rows = []
    for i, (name, (mask, score, sizing, exposure)) in enumerate(routes.items(), 1):
        sig = make_signal(x, mask, score, schedule, sizing, exposure)
        row = {"route": name}
        for label, start, end in (("design", "2024-01-01", "2024-12-31"),
                                  ("holdout", "2025-01-01", "2026-07-31"),
                                  ("continuous", "2024-01-01", "2026-07-31")):
            m, eq, tr = run(market, sig, start, end, cfg)
            row.update({label + "_" + k: v for k, v in m.items()})
            if label == "continuous":
                eq.to_csv(OUT/f"equity_P{i}.csv", index=False, encoding="utf-8-sig")
                tr.to_csv(OUT/f"trades_P{i}.csv", index=False, encoding="utf-8-sig")
        rows.append(row)
        print(f"{i}/8 {name} complete", flush=True)
    result = pd.DataFrame(rows).sort_values(["holdout_sharpe", "holdout_annual_return"], ascending=False)
    result.to_csv(OUT/"results.csv", index=False, encoding="utf-8-sig")
    cols = ["route", "design_annual_return", "design_sharpe", "design_max_drawdown",
            "holdout_annual_return", "holdout_sharpe", "holdout_max_drawdown",
            "continuous_annual_return", "continuous_sharpe", "continuous_max_drawdown",
            "continuous_average_exposure"]
    print(result[cols].to_string(index=False))


if __name__ == "__main__":
    main()
