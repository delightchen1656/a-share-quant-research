"""Pure intraday and signed-volume reversal routes from factor diagnostics."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m3_reversal_regime import build,simulate  # noqa
from m2_simple_baselines import metrics  # noqa
OUT=STUDY/"reports"/"m16_intraday_flow_reversal"
def main():
 OUT.mkdir(parents=True,exist_ok=True);x,state=build();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
 x["intraday1"]=x.close/x.open-1;x["overnight1"]=x.open/x.preclose-1;x["amount_change"]=g.amount.pct_change(fill_method=None).clip(-5,5);x["signed_amount"]=x.ret1*x.amount_change
 x["intraday20"]=g.intraday1.transform(lambda s:s.rolling(20).sum());x["overnight20"]=g.overnight1.transform(lambda s:s.rolling(20).sum());x["signed_amount20"]=g.signed_amount.transform(lambda s:s.rolling(20).mean())
 e=x[x.eligible].copy();d=e.groupby("date");hi=lambda c:d[c].rank(pct=True);lo=lambda c:1-hi(c)
 e["D1_intraday_reversal"]=lo("intraday20");e["D2_flow_reversal"]=lo("signed_amount20");e["D3_intraday_flow"]=.55*lo("intraday20")+.45*lo("signed_amount20");e["D4_decomposition"]=.45*lo("intraday20")+.35*lo("signed_amount20")+.20*hi("overnight20");e["D5_trend_decomposition"]=(.40*lo("intraday20")+.25*lo("signed_amount20")+.20*hi("overnight20")+.15*hi("ret120")).where(e.ret120>0)
 cols=[c for c in e if c.startswith("D")];x=x.merge(e[["date","symbol"]+cols],on=["date","symbol"],how="left");rows=[]
 for score in cols:
  print(score,flush=True);c,_=simulate(x,state,score,"none",80,240,40);c.to_parquet(OUT/f"{score}_curve.parquet",index=False)
  for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
   z=c[c.date.between(start,end)].copy();z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod();z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod();z["net_return"]=z.net_nav.pct_change().fillna(0);m=metrics(z);m.update({"strategy":score,"period":period});rows.append(m)
 r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())
if __name__=="__main__":main()
