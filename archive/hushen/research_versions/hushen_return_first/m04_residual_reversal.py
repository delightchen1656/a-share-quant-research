"""Market-beta and style-cohort neutral reversal candidates."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent; PROJECT=STUDY.parents[1]
sys.path.insert(0,str(HERE))
from m3_reversal_regime import build,simulate  # noqa
OUT=STUDY/"reports"/"m4_residual_reversal"

def prepare():
    x,state=build()
    idx=pd.read_parquet(PROJECT/"data_pipeline"/"data"/"indices"/"000905.SH.parquet")
    idx.date=pd.to_datetime(idx.date); close=pd.to_numeric(idx.close,errors="coerce")
    ix=pd.DataFrame({"date":idx.date,"idx1":close.pct_change(),"idx20":close.pct_change(20)})
    x=x.merge(ix,on="date",how="left").sort_values(["symbol","date"])
    g=x.groupby("symbol",sort=False)
    x["cross"]=x.ret1*x.idx1; x["idxsq"]=x.idx1*x.idx1
    mr=g.ret1.transform(lambda z:z.rolling(60).mean())
    mi=g.idx1.transform(lambda z:z.rolling(60).mean())
    mc=g.cross.transform(lambda z:z.rolling(60).mean())
    mi2=g.idxsq.transform(lambda z:z.rolling(60).mean())
    x["beta60"]=((mc-mr*mi)/(mi2-mi*mi).clip(lower=1e-8)).clip(-1,3)
    x["residual20"]=x.ret20-x.beta60*x.idx20
    e=x[x.eligible].copy(); d=e.groupby("date")
    hi=lambda c:d[c].rank(pct=True); lo=lambda c:1-hi(c)
    e["Q1_residual_reversal"]=.45*lo("residual20")+.25*lo("vol60")+.20*lo("amount20")+.10*lo("liq_ratio")
    e["Q2_lowbeta_residual"]=.40*lo("residual20")+.25*lo("beta60")+.20*lo("vol60")+.15*lo("amount20")
    e["Q3_trend_residual"]= (.40*lo("residual20")+.25*hi("ret120")+.20*lo("vol60")+.15*lo("amount20")).where(e.ret120>0)
    e["Q4_confirmed_residual"]=(.40*lo("residual20")+.25*hi("ret5")+.20*lo("vol60")+.15*lo("amount20")).where((e.residual20<0)&(e.ret5>0))
    # Neutralise reversal rank inside point-in-time beta x long-strength cohorts.
    e["beta_bucket"]=np.minimum((hi("beta60")*3).fillna(0).astype(int),2)
    e["strength_bucket"]=np.minimum((hi("ret120")*5).fillna(0).astype(int),4)
    within=e.groupby(["date","beta_bucket","strength_bucket"])
    e["within_residual_rank"]=1-within.residual20.rank(pct=True)
    e["Q5_cohort_neutral"]=.55*e.within_residual_rank+.25*lo("vol60")+.20*lo("amount20")
    cols=[c for c in e.columns if c.startswith("Q")]
    x=x.merge(e[["date","symbol"]+cols],on=["date","symbol"],how="left")
    return x,state,cols

def main():
    OUT.mkdir(parents=True,exist_ok=True); x,state,cols=prepare(); rows=[]
    configs=[(score,score,80,240,40) for score in cols]
    configs += [("Q3_trend_residual_50x40","Q3_trend_residual",50,200,40),
                ("Q3_trend_residual_100x40","Q3_trend_residual",100,300,40),
                ("Q3_trend_residual_50x60","Q3_trend_residual",50,300,60),
                ("Q3_trend_residual_80x60","Q3_trend_residual",80,320,60)]
    for name,score,top,buffer,rebalance in configs:
        print(name,flush=True); c,m=simulate(x,state,score,"none",top,buffer,rebalance)
        m.update({"strategy":name,"top_n":top,"buffer_n":buffer,"rebalance":rebalance})
        rows.append(m); c.to_parquet(OUT/f"{name}_curve.parquet",index=False)
    r=pd.DataFrame(rows).sort_values("annualized_return",ascending=False)
    r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig"); print(r.to_string(index=False))

if __name__=="__main__":main()
