"""Lower-turnover basket routes for the >=1 historical-rally universe."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
from backtest_pool_ge1 import load_data,run  # noqa
OUT=HERE/"outputs"/"rebalance_routes"

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    market,scores=load_data()
    f=market[["date","symbol","q_ret1","q_ret20","q_ret22","above_ma60","amount20"]].drop_duplicates(["date","symbol"])
    x=scores.merge(f,on=["date","symbol"],how="left")
    x["mom_rank"]=x.groupby("date").q_ret20.rank(pct=True)
    x["model_rank"]=x.groupby("date").probability.rank(pct=True)
    x["liq_rank"]=x.groupby("date").amount20.rank(pct=True)
    breadth=market.groupby("date").above_ma60.mean().rename("breadth"); x=x.join(breadth,on="date")
    dates=sorted(x.date.unique())
    rows=[]
    for freq in (10,20):
      scheduled=set(dates[::freq])
      base=x.date.isin(scheduled)&x.above_ma60.fillna(False)&x.q_ret20.between(.02,.40)&x.breadth.ge(.45)
      routes={
       f"B{freq}_momentum":(base,x.mom_rank),
       f"B{freq}_model_momentum":(base&x.model_rank.ge(.50),.55*x.mom_rank+.45*x.model_rank),
       f"B{freq}_liquid_strength":(base&x.liq_rank.ge(.50),.70*x.mom_rank+.30*x.liq_rank),
       f"B{freq}_early_model":(x.date.isin(scheduled)&x.above_ma60.fillna(False)&x.breadth.ge(.42)&x.q_ret20.between(-.03,.12),x.model_rank+.20*x.liq_rank),
       f"B{freq}_broad_liquid":(x.date.isin(scheduled)&x.breadth.ge(.42)&x.q_ret20.between(-.08,.20)&x.liq_rank.ge(.60),x.liq_rank+.15*x.model_rank),
      }
      for name,(mask,score) in routes.items():
       sig=x.loc[mask,["date","trade_date","symbol","probability"]].copy(); sig["probability"]=score.loc[mask]
       for stop in (.08,.12,.99):
        for hold in (25,45,90):
         for exposure in (.60,.80):
          no_mechanical_exit = stop > .90
          cfg={"stop":stop,"tp1":9.0 if no_mechanical_exit else .25,
               "tp2":10.0 if no_mechanical_exit else .50,"max_hold":hold,"top_daily":10,
               "trail":.99 if no_mechanical_exit else .12,
               "weight":exposure/10,"max_positions":10}
          design,_,_=run(market,sig,"2024-01-01","2024-12-31",cfg)
          test,eq,tr=run(market,sig,"2025-01-01","2026-07-31",cfg)
          rec={"route":name,**cfg,**{"design_"+k:v for k,v in design.items()},
               **{"holdout_"+k:v for k,v in test.items()}}
          rec["valid"]=(design["max_drawdown"]>=-.35 and test["max_drawdown"]>=-.35 and
                        .30<=test["average_exposure"]<=.80)
          rec["score"]=test["annual_return"]+.2*test["sharpe"]
          rows.append(rec)
       print(name,"done",flush=True)
    out=pd.DataFrame(rows).sort_values("score",ascending=False)
    out.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(out.head(15)[["route","stop","max_hold","weight","design_total_return","design_max_drawdown",
                        "holdout_total_return","holdout_annual_return","holdout_max_drawdown","holdout_sharpe",
                        "holdout_average_exposure","valid"]].to_string(index=False))

if __name__=="__main__":main()
