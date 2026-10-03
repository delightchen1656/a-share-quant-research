"""Point-in-time style clusters built only from trailing price/volume features."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m3_reversal_regime import simulate  # noqa
from m2_simple_baselines import metrics  # noqa
OUT=STUDY/"reports"/"m8_pit_style_clusters"

def build_scores():
    x,state,_=prepare(); x=x.sort_values(["date","symbol"])
    dates=sorted(x[x.date.between("2018-01-01","2026-08-31")].date.unique())
    schedule=set(dates[39::40]); parts=[]
    for date,d in x[x.date.isin(schedule)&x.eligible].groupby("date"):
        q=d.copy(); q["log_amount"]=np.log(q.amount20.clip(lower=1))
        features=["beta60","vol60","ret120","ret20","log_amount"]
        z=q[features].replace([np.inf,-np.inf],np.nan).dropna()
        if len(z)<100: continue
        standard=(z-z.mean())/z.std().replace(0,1)
        labels=KMeans(n_clusters=12,random_state=20260914,n_init=5).fit_predict(standard)
        q=q.loc[z.index].copy(); q["cluster"]=labels
        cg=q.groupby("cluster").agg(cluster_ret20=("ret20","median"),cluster_ret60=("ret60","median"),
            cluster_residual=("residual20","median"),cluster_vol=("vol60","median"),cluster_breadth=("ret20",lambda s:(s>0).mean()))
        q=q.join(cg,on="cluster"); gd=q.groupby("date")
        hi=lambda c:gd[c].rank(pct=True); lo=lambda c:1-hi(c)
        within=q.groupby("cluster")
        within_lowvol=1-within.vol60.rank(pct=True); within_reversal=1-within.residual20.rank(pct=True)
        q["C1_cluster_momentum"]=(.55*hi("cluster_ret60")+.25*hi("cluster_breadth")+.20*within_lowvol).where(q.cluster_ret60>0)
        q["C2_cluster_reversal"]=(.55*lo("cluster_residual")+.25*within_reversal+.20*within_lowvol).where(q.ret120>0)
        q["C3_cluster_leader_pullback"]=(.45*hi("cluster_ret60")+.35*within_reversal+.20*within_lowvol).where((q.cluster_ret60>0)&(q.residual20<0))
        q["C4_cluster_lowrisk"]=(.45*lo("cluster_vol")+.30*lo("cluster_residual")+.25*within_lowvol).where(q.ret120>0)
        parts.append(q[["date","symbol","C1_cluster_momentum","C2_cluster_reversal","C3_cluster_leader_pullback","C4_cluster_lowrisk"]])
    scores=pd.concat(parts,ignore_index=True); return x.merge(scores,on=["date","symbol"],how="left"),state,list(scores.columns[2:])

def main():
    OUT.mkdir(parents=True,exist_ok=True); x,state,cols=build_scores(); rows=[]
    for score in cols:
        print(score,flush=True); c,_=simulate(x,state,score,"none",80,240,40); c.to_parquet(OUT/f"{score}_curve.parquet",index=False)
        for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),
                                 ("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
            z=c[c.date.between(start,end)].copy(); z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod()
            z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod(); z["net_return"]=z.net_nav.pct_change().fillna(0)
            m=metrics(z); m.update({"strategy":score,"period":period}); rows.append(m)
    r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(r[r.period=="全周期"].sort_values("annualized_return",ascending=False).to_string(index=False))
    print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())

if __name__=="__main__":main()
