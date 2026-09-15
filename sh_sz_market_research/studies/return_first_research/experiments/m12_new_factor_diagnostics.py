"""Diagnostics for independent price-path, overnight and liquidity factors."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m2_simple_baselines import load_features  # noqa
OUT=STUDY/"reports"/"m12_new_factor_diagnostics"

def main():
    OUT.mkdir(parents=True,exist_ok=True);x=load_features().sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
    x["overnight1"]=x.open/x.preclose-1;x["intraday1"]=x.close/x.open-1
    x["range1"]=(x.high-x.low)/x.preclose.replace(0,np.nan);x["amihud1"]=x.ret1.abs()/x.amount.clip(lower=1)
    x["amount_change"]=g.amount.pct_change(fill_method=None).clip(-5,5);x["signed_amount"]=x.ret1*x.amount_change
    x["overnight20"]=g.overnight1.transform(lambda s:s.rolling(20).sum())
    x["intraday20"]=g.intraday1.transform(lambda s:s.rolling(20).sum())
    x["range20"]=g.range1.transform(lambda s:s.rolling(20).mean())
    x["amihud20"]=g.amihud1.transform(lambda s:s.rolling(20).mean())
    x["skew20"]=g.ret1.transform(lambda s:s.rolling(20).skew())
    x["min20"]=g.ret1.transform(lambda s:s.rolling(20).min())
    x["downvol20"]=g.ret1.transform(lambda s:s.where(s<0,0).rolling(20).std())
    x["vol_ratio"]=x.vol20/x.vol60
    x["signed_amount20"]=g.signed_amount.transform(lambda s:s.rolling(20).mean())
    x["future20"]=g.qfq_close.shift(-20)/g.qfq_close.shift(-1)-1
    factors=["overnight1","intraday1","overnight20","intraday20","range20","amihud20","skew20","min20","downvol20","vol_ratio","signed_amount20"]
    e=x[x.eligible].dropna(subset=["future20"]);rows=[]
    for f in factors:
        for year,d in e.dropna(subset=[f]).groupby(e.date.dt.year):
            daily=d.groupby("date").apply(lambda q:q[f].corr(q.future20,method="spearman"),include_groups=False)
            ranks=d.groupby("date")[f].rank(pct=True);spread=d.future20[ranks>=.8].mean()-d.future20[ranks<=.2].mean()
            rows.append({"factor":f,"year":int(year),"rank_ic":daily.mean(),"top_bottom_spread":spread,"days":daily.notna().sum()})
    r=pd.DataFrame(rows);r.to_csv(OUT/"yearly_factor_diagnostics.csv",index=False,encoding="utf-8-sig")
    s=r.groupby("factor").agg(mean_ic=("rank_ic","mean"),min_ic=("rank_ic","min"),positive_years=("rank_ic",lambda z:(z>0).sum()),mean_spread=("top_bottom_spread","mean"))
    s.sort_values("mean_ic",ascending=False).to_csv(OUT/"summary.csv",encoding="utf-8-sig");print(s.sort_values("mean_ic",ascending=False).to_string())

if __name__=="__main__":main()
