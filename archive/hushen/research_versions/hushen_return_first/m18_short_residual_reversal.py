"""Short-horizon idiosyncratic reversal with low-IVOL control."""
from pathlib import Path
import sys
import pandas as pd
HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m3_reversal_regime import simulate  # noqa
from m2_simple_baselines import metrics  # noqa
OUT=STUDY/"reports"/"m18_short_residual_reversal"
def main():
 OUT.mkdir(parents=True,exist_ok=True);x,state,_=prepare();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
 ix=x[["date","idx1"]].drop_duplicates("date").sort_values("date");ix["idx5"]=(1+ix.idx1).rolling(5).apply(lambda z:z.prod(),raw=True)-1;ix["idx10"]=(1+ix.idx1).rolling(10).apply(lambda z:z.prod(),raw=True)-1;x=x.merge(ix[["date","idx5","idx10"]],on="date",how="left")
 x["res5"]=x.ret5-x.beta60*x.idx5;x["ret10"]=g.qfq_close.pct_change(10,fill_method=None);x["res10"]=x.ret10-x.beta60*x.idx10;x["idio1"]=x.ret1-x.beta60*x.idx1;x["ivol20"]=x.groupby("symbol",sort=False).idio1.transform(lambda s:s.rolling(20).std())
 e=x[x.eligible].copy();d=e.groupby("date");hi=lambda c:d[c].rank(pct=True);lo=lambda c:1-hi(c)
 e["R5_short"]=(.50*lo("res5")+.25*lo("ivol20")+.15*hi("ret120")+.10*lo("amount20")).where(e.ret120>0)
 e["R10_short"]=(.50*lo("res10")+.25*lo("ivol20")+.15*hi("ret120")+.10*lo("amount20")).where(e.ret120>0)
 e["R5_confirm"]=(.40*lo("res5")+.25*hi("ret20")+.20*lo("ivol20")+.15*lo("amount20")).where((e.ret120>0)&(e.ret20<0))
 cols=["R5_short","R10_short","R5_confirm"];x=x.merge(e[["date","symbol"]+cols],on=["date","symbol"],how="left");rows=[]
 configs=[("R5_10日","R5_short",80,240,10),("R5_20日","R5_short",80,240,20),("R10_20日","R10_short",80,240,20),("R10_40日","R10_short",80,240,40),("R5确认20日","R5_confirm",80,240,20)]
 for name,score,top,buf,reb in configs:
  print(name,flush=True);c,_=simulate(x,state,score,"none",top,buf,reb);c.to_parquet(OUT/f"{name}_curve.parquet",index=False)
  for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
   z=c[c.date.between(start,end)].copy();z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod();z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod();z["net_return"]=z.net_nav.pct_change().fillna(0);m=metrics(z);m.update({"strategy":name,"period":period});rows.append(m)
 r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())
if __name__=="__main__":main()
