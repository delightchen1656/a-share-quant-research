"""China A-share localized versions of public low-turnover Sharpe ideas.

Design rules are fixed before reading the 2025-2026/7 holdout results.
The candidate universe remains the point-in-time >=1 historical 10d+50% pool.
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
OUT = HERE / "outputs" / "cn_local_sharpe_routes"


def rank(x, col):
    return x.groupby("date")[col].rank(pct=True)


def signal(x, mask, score, schedule, exposure, inverse_vol=False):
    z = x.loc[mask & x.date.isin(schedule),
              ["date", "trade_date", "symbol", "vol60"]].copy()
    z["probability"] = score.loc[z.index]
    z = z.sort_values(["date", "probability"], ascending=[True, False])
    z = z.groupby("date", group_keys=False).head(12)
    n = z.groupby("date").symbol.transform("count")
    if inverse_vol:
        z["rw"] = 1 / z.vol60.clip(lower=.008)
        z["rw"] = z.groupby("date").rw.transform(lambda q: q.clip(upper=q.median()*1.5))
        z["target_weight"] = z.rw / z.groupby("date").rw.transform("sum")
    else:
        z["target_weight"] = 1 / n
    z["target_weight"] *= z.date.map(exposure)
    return z[["date", "trade_date", "symbol", "probability", "target_weight"]]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    market, _ = load_data()
    x = pd.read_parquet(FEATURES); x.date = pd.to_datetime(x.date)
    cal = np.array(sorted(market.date.unique()), dtype="datetime64[ns]")
    ix = np.searchsorted(cal, x.date.to_numpy(dtype="datetime64[ns]"), side="right")
    ok = ix < len(cal); x = x.loc[ok].copy(); x["trade_date"] = cal[ix[ok]]
    cols = ("ret5","ret20","ret60","vol20","vol60","volume_ratio","up_volume_share",
            "pv_corr","close_pos60","turn20","amount20","breakout_gap","volume_spike","dd20")
    for c in cols: x[c+"_rank"] = rank(x,c)
    x["mom20_skip5"] = x.ret20-x.ret5
    x["mom20_skip5_rank"] = rank(x,"mom20_skip5")
    x["ramom20"] = x.mom20_skip5/(x.vol20*np.sqrt(20)+1e-6)
    x["ramom20_rank"] = rank(x,"ramom20")

    # A-share state: breadth is more useful than a single cap-weighted index when
    # the traded universe is composed of volatile main-board names.
    state = x.groupby("date").agg(breadth20=("ret20",lambda q:(q>0).mean()),
                                  breadth60=("ret60",lambda q:(q>0).mean()),
                                  median5=("ret5","median"))
    normal = pd.Series(.70,index=state.index)
    adaptive = pd.Series(np.select(
        [((state.breadth20<.32)&(state.median5<-.03)), state.breadth20<.43],
        [.35,.52], default=.70), index=state.index)

    # Local trading filters: do not chase near-limit bursts; demand adequate
    # liquidity; avoid the least liquid/highest-turnover tails and falling knives.
    liquid = x.amount20_rank.ge(.25) & x.turn20_rank.between(.10,.85)
    not_chasing = x.ret5.lt(.10) & x.volume_spike.lt(2.5) & x.breakout_gap.lt(.075)
    base = x.ret60.gt(0) & x.vol20_rank.le(.50) & x.up_volume_share.ge(.50)
    score_base = .40*x.ramom20_rank+.30*(1-x.vol20_rank)+.20*x.up_volume_share_rank+.10*x.amount20_rank
    routes = {
      "L1_本土低波量价": (base & liquid, score_base, normal, False),
      "L2_不追急涨": (base & liquid & not_chasing, score_base+.10*(1-x.ret5_rank), normal, False),
      "L3_短跳月动量": (liquid & not_chasing & x.mom20_skip5.gt(0) & x.ret60.gt(0),
                       .55*x.ramom20_rank+.25*(1-x.vol20_rank)+.20*x.up_volume_share_rank, normal, False),
      "L4_趋势回踩": (liquid & x.ret60.gt(.03) & x.ret5.between(-.08,.01) & x.close_pos60.between(.35,.85),
                     .45*x.ret60_rank+.30*(1-x.ret5_rank)+.25*(1-x.vol20_rank), normal, False),
      "L5_波动收缩蓄势": (liquid & not_chasing & x.ret60.gt(0) & (x.vol20<x.vol60) & x.up_volume_share.ge(.48),
                         .35*x.ramom20_rank+.30*(1-x.vol20_rank)+.20*x.up_volume_share_rank+.15*(1-x.pv_corr_rank), normal, False),
      "L6_宽度自适应": (base & liquid & not_chasing, score_base, adaptive, False),
      "L7_宽度自适应逆波动": (base & liquid & not_chasing, score_base, adaptive, True),
      "L8_中等换手强势": (not_chasing & x.ret20.gt(0) & x.ret60.gt(0) & x.turn20_rank.between(.25,.65),
                         .45*x.ramom20_rank+.25*x.up_volume_share_rank+.20*x.amount20_rank+.10*(1-x.vol20_rank), adaptive, False),
    }
    dates = sorted(x.date.unique()); schedule=set(dates[::20])
    cfg={"stop":.12,"tp1":9.,"tp2":10.,"max_hold":45,"top_daily":12,
         "trail":.99,"weight":.07,"max_positions":12}
    out=[]
    for i,(name,(mask,score,expo,iv)) in enumerate(routes.items(),1):
        sig=signal(x,mask,score,schedule,expo,iv); row={"route":name}
        for label,start,end in (("design","2024-01-01","2024-12-31"),
                                ("holdout","2025-01-01","2026-07-31"),
                                ("continuous","2024-01-01","2026-07-31")):
            m,eq,tr=run(market,sig,start,end,cfg)
            row.update({label+"_"+k:v for k,v in m.items()})
            if label=="continuous":
                eq.to_csv(OUT/f"equity_L{i}.csv",index=False,encoding="utf-8-sig")
                tr.to_csv(OUT/f"trades_L{i}.csv",index=False,encoding="utf-8-sig")
        out.append(row); print(f"{i}/8 {name} complete",flush=True)
    r=pd.DataFrame(out).sort_values(["holdout_sharpe","holdout_annual_return"],ascending=False)
    r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    cols=["route","design_annual_return","design_sharpe","design_max_drawdown",
          "holdout_annual_return","holdout_sharpe","holdout_max_drawdown",
          "continuous_annual_return","continuous_sharpe","continuous_max_drawdown",
          "continuous_average_exposure"]
    print(r[cols].to_string(index=False))

if __name__=="__main__": main()
