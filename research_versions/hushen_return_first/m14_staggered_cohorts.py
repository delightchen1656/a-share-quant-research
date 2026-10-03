"""Stagger Q3 entries into independent cohorts to reduce timing concentration."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m5_opportunity_quality_gates import quality_table  # noqa
from m10_position_risk_weighting import capped_normalize  # noqa
from m2_simple_baselines import metrics,ONE_WAY_COST  # noqa
OUT=STUDY/"reports"/"m14_staggered_cohorts"

def run(x,quality,cuts,cohorts,use_gate=True):
 z=x[x.date.between("2018-01-01","2026-08-31")];dates=sorted(z.date.unique());days={d:a.set_index("symbol") for d,a in z.groupby("date")}
 buckets=[[] for _ in range(cohorts)];update_every=max(1,40//cohorts);current={};pending=None;gross=net=1.;rows=[];exposure=1.
 for i,date in enumerate(dates):
  d=days[date];r=sum(w*float(d.at[s,"ret1"]) for s,w in current.items() if s in d.index and np.isfinite(d.at[s,"ret1"]));gross*=1+r;net*=1+r;turn=0
  if pending is not None:
   target={s:w for s,w in pending.items() if s in d.index and bool(d.at[s,"tradable"]) and not bool(d.at[s,"one_price_up"])}
   for s,w in current.items():
    if s not in target and s in d.index and (not bool(d.at[s,"tradable"]) or bool(d.at[s,"one_price_down"])):target[s]=w
   if sum(target.values())>1:target={s:w/sum(target.values()) for s,w in target.items()}
   turn=sum(abs(target.get(s,0)-current.get(s,0)) for s in set(target)|set(current));net*=max(0,1-turn*ONE_WAY_COST);current=target;pending=None
  rows.append({"date":date,"gross_nav":gross,"net_nav":net,"turnover":turn,"exposure":sum(current.values()),"positions":len(current)})
  if i>=119 and i%update_every==update_every-1:
   b=(i//update_every)%cohorts;occupied=set(s for j,bucket in enumerate(buckets) if j!=b for s in bucket)
   ranked=d[d.Q3_trend_residual.notna()&~d.index.isin(occupied)].sort_values("Q3_trend_residual",ascending=False)
   buckets[b]=list(ranked.head(80//cohorts).index)
   if use_gate and i%40>=40-update_every:
    q=quality.loc[date];danger=q.market_ret20<cuts["market_ret20"][.35] and q.residual_dispersion<cuts["residual_dispersion"][.35];exposure=.35 if danger else 1.
   target={}
   for bucket in buckets:
    if not bucket:continue
    raw=1/d.loc[bucket].ivol20.clip(lower=.004);w=capped_normalize(raw,exposure/cohorts,len(bucket),2.0);target.update(w.to_dict())
   pending=target
 c=pd.DataFrame(rows);c["net_return"]=c.net_nav.pct_change().fillna(0);return c

def main():
 OUT.mkdir(parents=True,exist_ok=True);x,_,_=prepare();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False);x["idio1"]=x.ret1-x.beta60*x.idx1;x["ivol20"]=g.idio1.transform(lambda s:s.rolling(20).std())
 quality,cuts=quality_table(x);quality=quality.reindex(pd.DatetimeIndex(sorted(x.date.unique()))).ffill();rows=[]
 for name,cohorts,gate in [("K1_单批40日",1,True),("K2_两批20日",2,True),("K3_四批10日",4,True),("K4_八批5日",8,True),("K5_四批无门控",4,False)]:
  print(name,flush=True);c=run(x,quality,cuts,cohorts,gate);c.to_parquet(OUT/f"{name}_curve.parquet",index=False)
  for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
   q=c[c.date.between(start,end)].copy();q["gross_nav"]=(1+q.gross_nav.pct_change().fillna(0)).cumprod();q["net_nav"]=(1+q.net_nav.pct_change().fillna(0)).cumprod();q["net_return"]=q.net_nav.pct_change().fillna(0);m=metrics(q);m.update({"strategy":name,"period":period});rows.append(m)
 r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())
if __name__=="__main__":main()
