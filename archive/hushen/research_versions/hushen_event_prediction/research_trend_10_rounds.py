"""Ten sequential low-turnover trend structures, with 2025+ untouched by design."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
from backtest_pool_ge1 import load_data,run  # noqa
TREND=HERE/"outputs"/"trend_models"/"trend_scores_2024_2026.parquet"
OUT=HERE/"outputs"/"trend_10_rounds"

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 market,old=load_data(); sc=pd.read_parquet(TREND); sc.date=pd.to_datetime(sc.date)
 extra=market[["date","symbol","q_ret1","q_ret20","above_ma60","amount20"]].drop_duplicates(["date","symbol"])
 x=sc.merge(extra,on=["date","symbol"],how="left")
 cal=np.array(sorted(market.date.unique()),dtype="datetime64[ns]"); idx=np.searchsorted(cal,x.date.to_numpy(dtype="datetime64[ns]"),side="right")
 good=idx<len(cal); x=x.loc[good].copy(); x["trade_date"]=cal[idx[good]]
 x["ensemble"]=.25*x.pred_f20+.40*x.pred_f40+.35*x.pred_f60
 x["risk_score"]=x.ensemble+0.65*x.pred_mae20
 x["mom_rank"]=x.groupby("date").q_ret20.rank(pct=True); x["liq_rank"]=x.groupby("date").amount20.rank(pct=True)
 breadth=market.groupby("date").above_ma60.mean().rename("breadth"); x=x.join(breadth,on="date")
 dates=sorted(x.date.unique())
 rounds=[
  ("R1_20日趋势",10,25,.60,x.pred_f20,x.pred_f20.gt(0)),
  ("R2_40日趋势",20,45,.60,x.pred_f40,x.pred_f40.gt(0)),
  ("R3_60日趋势",20,65,.60,x.pred_f60,x.pred_f60.gt(0)),
  ("R4_三周期融合",20,55,.60,x.ensemble,x.ensemble.gt(0)),
  ("R5_不利波动修正",20,55,.60,x.risk_score,x.risk_score.gt(0)),
  ("R6_趋势动量确认",20,55,.60,.75*x.ensemble+.25*x.mom_rank,(x.ensemble.gt(0)&x.q_ret20.between(0,.35))),
  ("R7_流动性风险调整",20,55,.60,.70*x.risk_score+.20*x.mom_rank+.10*x.liq_rank,(x.risk_score.gt(0)&x.liq_rank.ge(.35))),
  ("R8_市场宽度门控",20,55,.60,x.risk_score+.15*x.mom_rank,(x.risk_score.gt(0)&x.breadth.ge(.45))),
  ("R9_强市场提高仓位",10,45,.80,x.risk_score+.20*x.mom_rank,(x.risk_score.gt(0)&x.breadth.ge(.52)&x.q_ret20.between(-.02,.40))),
  ("R10_多周期共振",20,60,.70,x.risk_score+.15*x.mom_rank,(x.pred_f20.gt(0)&x.pred_f40.gt(0)&x.pred_f60.gt(0)&x.breadth.ge(.45))),
 ]
 results=[]
 for n,(name,freq,hold,target,score,mask) in enumerate(rounds,1):
  scheduled=set(dates[::freq]); use=mask&x.date.isin(scheduled)
  sig=x.loc[use,["date","trade_date","symbol"]].copy(); sig["probability"]=score.loc[use]
  cfg={"stop":.15,"tp1":9.0,"tp2":10.0,"max_hold":hold,"top_daily":10,"trail":.99,
       "weight":target/10,"max_positions":10}
  for period,start,end in (("design_2024","2024-01-01","2024-12-31"),("holdout_2025_2026","2025-01-01","2026-07-31"),("continuous","2024-01-01","2026-07-31")):
   m,eq,tr=run(market,sig,start,end,cfg); m.update({"round":n,"name":name,"period":period,**cfg}); results.append(m)
   if period=="continuous":
    eq.to_csv(OUT/f"equity_R{n}.csv",index=False,encoding="utf-8-sig"); tr.to_csv(OUT/f"trades_R{n}.csv",index=False,encoding="utf-8-sig")
  print(f"round {n}/10 {name} done",flush=True)
 out=pd.DataFrame(results); out.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
 pivot=out.pivot(index=["round","name"],columns="period",values=["annual_return","max_drawdown","sharpe","average_exposure","final_asset"])
 pivot.to_csv(OUT/"comparison.csv",encoding="utf-8-sig"); print(pivot.to_string())
if __name__=="__main__":main()
