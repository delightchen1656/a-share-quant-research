"""Lagged equity-state overlays on the best inv-IVOL Q3-G7 curve."""
from pathlib import Path
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent;OUT=STUDY/"reports"/"m17_equity_state_sweep";COST=.003
SOURCE=STUDY/"reports"/"m10_position_risk_weighting"/"inv_ivol_curve.parquet"
def calc(r,alloc):
 change=alloc.diff().abs().fillna(0);y=r*alloc-COST*change;nav=(1+y).cumprod();return y,nav
def stats(date,r):
 nav=(1+r).cumprod();days=max((date.iloc[-1]-date.iloc[0]).days,1);return nav.iloc[-1]**(365.25/days)-1,(nav/nav.cummax()-1).min(),np.sqrt(252)*r.mean()/r.std()
def main():
 OUT.mkdir(parents=True,exist_ok=True);x=pd.read_parquet(SOURCE).sort_values("date");r=x.net_nav.pct_change().fillna(0);nav=(1+r).cumprod();rows=[]
 signals={}
 for look in (10,20,40,60,120):
  signals[f"ret{look}"]=nav.pct_change(look).shift(1)>0
  signals[f"ma{look}"]=(nav>nav.rolling(look).mean()).shift(1)
 vol=r.rolling(20).std()*np.sqrt(252)
 for target in (.10,.12,.15,.18):signals[f"vol{int(target*100)}"]=(target/vol.clip(lower=.05)).clip(.25,1).shift(1)
 dd=(nav/nav.cummax()-1).shift(1)
 signals["dd5"]=pd.Series(np.where(dd<-.10,.25,np.where(dd<-.05,.60,1.)),index=x.index)
 signals["dd8"]=pd.Series(np.where(dd<-.15,.25,np.where(dd<-.08,.60,1.)),index=x.index)
 for name,sig in signals.items():
  for floor in ((.2,.4,.6) if sig.dtype==bool else (None,)):
   raw=sig.map({True:1.,False:floor}) if floor is not None else sig
   for review in (5,10,20,40):
    flag=pd.Series(False,index=x.index);flag.iloc[119::review]=True;alloc=raw.where(flag).ffill().fillna(1.);ret,_=calc(r,alloc);label=f"{name}_f{floor}_r{review}"
    for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
     mask=x.date.between(start,end);ann,ddm,sh=stats(x.date[mask],ret[mask]);rows.append({"strategy":label,"period":period,"annualized_return":ann,"max_drawdown":ddm,"sharpe":sh,"average_exposure":alloc[mask].mean()})
 out=pd.DataFrame(rows);out.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");full=out[out.period=="全周期"].sort_values("sharpe",ascending=False);print(full.head(30).to_string(index=False))
if __name__=="__main__":main()
