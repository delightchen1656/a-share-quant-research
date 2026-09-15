"""Ten non-forecast technical routes; selection uses 2024 annualized results only."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np, pandas as pd
HERE=Path(__file__).resolve().parent; sys.path.insert(0,str(HERE))
from backtest_pool_ge1 import load_data,run  # noqa
FEATURES=HERE/"outputs"/"trend_models"/"trend_scores_2024_2026.parquet"
OUT=HERE/"outputs"/"alternative_10_routes"

def pct_rank(x,col,asc=True): return x.groupby("date")[col].rank(pct=True,ascending=asc)

def main():
 OUT.mkdir(parents=True,exist_ok=True); market,old=load_data()
 x=pd.read_parquet(FEATURES); x.date=pd.to_datetime(x.date)
 cal=np.array(sorted(market.date.unique()),dtype="datetime64[ns]"); idx=np.searchsorted(cal,x.date.to_numpy(dtype="datetime64[ns]"),side="right")
 good=idx<len(cal); x=x.loc[good].copy(); x["trade_date"]=cal[idx[good]]
 for c in ("ret5","ret20","ret60","vol20","vol60","volume_ratio","up_volume_share","pv_corr","close_pos60","turn20","amount20","breakout_gap","volume_spike","dd20","range20"):
  x[c+"_rank"]=pct_rank(x,c)
 x["ramom"]=x.ret60/(x.vol60*np.sqrt(60)+1e-6); x["ramom_rank"]=pct_rank(x,"ramom")
 x["contraction"]=x.vol20/(x.vol60+1e-6); x["contraction_rank"]=pct_rank(x,"contraction",asc=False)
 x["accumulation"]=.45*x.up_volume_share_rank+.30*(1-x.volume_ratio.sub(1).abs().groupby(x.date).rank(pct=True))+.25*(1-x.pv_corr_rank)
 routes={
 "A1_低波动正动量":(x.ret60.gt(0)&x.vol20_rank.le(.35),.60*(1-x.vol20_rank)+.40*x.ret60_rank),
 "A2_风险调整动量":(x.ret60.gt(0)&x.ramom_rank.ge(.65),x.ramom_rank),
 "A3_趋势内回踩":(x.ret60.gt(.05)&x.ret5.between(-.10,-.005)&x.close_pos60.between(.35,.80),.55*x.ret60_rank+.45*(1-x.ret5_rank)),
 "A4_超跌反转":(x.dd20.le(-.12)&x.ret5.lt(0),.50*(1-x.dd20_rank)+.30*x.volume_spike_rank+.20*x.amount20_rank),
 "A5_波动收缩":(x.ret60.gt(0)&x.contraction_rank.ge(.65),.50*x.contraction_rank+.30*x.ret60_rank+.20*x.close_pos60_rank),
 "A6_量价蓄势":(x.ret20.between(-.05,.15)&x.accumulation.ge(.55),x.accumulation),
 "A7_放量突破":(x.breakout_gap.gt(0)&x.volume_spike.ge(1.20),.45*x.breakout_gap_rank+.35*x.volume_spike_rank+.20*x.amount20_rank),
 "A8_临界突破":(x.close_pos60.ge(.80)&x.ret20.between(0,.30),.45*x.close_pos60_rank+.35*x.ret20_rank+.20*x.volume_ratio_rank),
 "A9_低换手强势":(x.ret60.gt(0)&x.turn20_rank.le(.50),.50*x.ramom_rank+.30*(1-x.turn20_rank)+.20*x.amount20_rank),
 "A10_低波动量价组合":(x.ret60.gt(0)&x.vol20_rank.le(.50)&x.up_volume_share.ge(.50),.40*x.ramom_rank+.35*(1-x.vol20_rank)+.25*x.up_volume_share_rank),
 }
 dates=sorted(x.date.unique()); trials=[]; chosen=[]
 configs=[]
 for freq in (10,20):
  for stop in (.12,.99):
   configs.append((freq,{"stop":stop,"tp1":9.,"tp2":10.,"max_hold":45 if freq==20 else 30,"top_daily":10,"trail":.99,"weight":.07,"max_positions":10}))
 for n,(name,(mask,score)) in enumerate(routes.items(),1):
  route_trials=[]
  for freq,cfg in configs:
   scheduled=set(dates[::freq]); use=mask&x.date.isin(scheduled)
   sig=x.loc[use,["date","trade_date","symbol"]].copy(); sig["probability"]=score.loc[use]
   m,_,_=run(market,sig,"2024-01-01","2024-12-31",cfg)
   rec={"round":n,"name":name,"freq":freq,**cfg,**{"design_"+k:v for k,v in m.items()}}
   rec["design_feasible"]=m["max_drawdown"]>=-.35 and .30<=m["average_exposure"]<=.80
   route_trials.append((rec,sig,cfg))
  eligible=[v for v in route_trials if v[0]["design_feasible"]] or route_trials
  best=max(eligible,key=lambda v:(v[0]["design_annual_return"],v[0]["design_sharpe"]))
  rec,sig,cfg=best; test,_,_=run(market,sig,"2025-01-01","2026-07-31",cfg); cont,eq,tr=run(market,sig,"2024-01-01","2026-07-31",cfg)
  rec.update({"holdout_"+k:v for k,v in test.items()}); rec.update({"continuous_"+k:v for k,v in cont.items()}); chosen.append(rec)
  trials.extend(v[0] for v in route_trials)
  eq.to_csv(OUT/f"equity_A{n}.csv",index=False,encoding="utf-8-sig"); tr.to_csv(OUT/f"trades_A{n}.csv",index=False,encoding="utf-8-sig")
  print(f"route {n}/10 {name} done",flush=True)
 pd.DataFrame(trials).to_csv(OUT/"design_search.csv",index=False,encoding="utf-8-sig")
 result=pd.DataFrame(chosen); result.to_csv(OUT/"results_annualized.csv",index=False,encoding="utf-8-sig")
 print(result[["round","name","design_annual_return","design_max_drawdown","holdout_annual_return","holdout_max_drawdown","continuous_annual_return","continuous_max_drawdown","continuous_sharpe","continuous_average_exposure"]].to_string(index=False))
if __name__=="__main__":main()
