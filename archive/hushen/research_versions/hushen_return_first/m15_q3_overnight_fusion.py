"""Fuse stable overnight/path information inside the Q3 candidate universe."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m5_opportunity_quality_gates import quality_table  # noqa
from m10_position_risk_weighting import run  # noqa
from m2_simple_baselines import metrics  # noqa
OUT=STUDY/"reports"/"m15_q3_overnight_fusion"

def main():
 OUT.mkdir(parents=True,exist_ok=True);x,_,_=prepare();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
 x["idio1"]=x.ret1-x.beta60*x.idx1;x["ivol20"]=g.idio1.transform(lambda s:s.rolling(20).std());x["max20"]=g.ret1.transform(lambda s:s.rolling(20).max())
 x["overnight1"]=x.open/x.preclose-1;x["range1"]=(x.high-x.low)/x.preclose.replace(0,np.nan);x["overnight20"]=g.overnight1.transform(lambda s:s.rolling(20).sum());x["range20"]=g.range1.transform(lambda s:s.rolling(20).mean());x["min20"]=g.ret1.transform(lambda s:s.rolling(20).min())
 e=x[x.Q3_trend_residual.notna()].copy();d=e.groupby("date");hi=lambda c:d[c].rank(pct=True);lo=lambda c:1-hi(c);base=hi("Q3_trend_residual");night=hi("overnight20");stable=.5*hi("min20")+.5*lo("range20");anti=lo("max20")
 e["F0_base"]=base;e["F1_night25"]=.75*base+.25*night;e["F2_night50"]=.50*base+.50*night;e["F3_stable25"]=.75*base+.25*stable;e["F4_night_stable"]=.60*base+.25*night+.15*stable;e["F5_night_antilottery"]=.60*base+.25*night+.15*anti
 cols=[c for c in e if c.startswith("F")];x=x.merge(e[["date","symbol"]+cols],on=["date","symbol"],how="left");quality,cuts=quality_table(x);quality=quality.reindex(pd.DatetimeIndex(sorted(x.date.unique()))).ffill();rows=[]
 original=x.Q3_trend_residual.copy()
 for score in cols:
  print(score,flush=True);x["Q3_trend_residual"]=x[score];c=run(x,quality,cuts,"inv_ivol");c.to_parquet(OUT/f"{score}_curve.parquet",index=False)
  for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
   z=c[c.date.between(start,end)].copy();z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod();z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod();z["net_return"]=z.net_nav.pct_change().fillna(0);m=metrics(z);m.update({"strategy":score,"period":period});rows.append(m)
 x["Q3_trend_residual"]=original;r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())
if __name__=="__main__":main()
