"""Year, period, drawdown and return-concentration review for candidate R8."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
SOURCE=STUDY/"reports"/"m3_reversal_regime"/"R8_低波反转分散40_curve.parquet"
OUT=STUDY/"reports"/"r8_candidate_review"

def stats(z):
    r=z.net_nav.pct_change().fillna(0); days=max((z.date.iloc[-1]-z.date.iloc[0]).days,1)
    total=(1+r).prod()-1
    return {"start":z.date.iloc[0],"end":z.date.iloc[-1],"total_return":total,
            "annualized_return":(1+total)**(365.25/days)-1,
            "max_drawdown":((1+r).cumprod()/(1+r).cumprod().cummax()-1).min(),
            "sharpe":np.sqrt(252)*r.mean()/r.std() if r.std() else 0,
            "average_exposure":z.exposure.mean(),"turnover":z.turnover.sum(),
            "positive_day_share":(r>0).mean()}

def main():
    OUT.mkdir(parents=True,exist_ok=True); c=pd.read_parquet(SOURCE); c.date=pd.to_datetime(c.date)
    rows=[]
    for y,z in c.groupby(c.date.dt.year):
        m=stats(z); m["period"]=str(y); rows.append(m)
    for name,start,end in [("2018-2023","2018-01-01","2023-12-31"),("2024","2024-01-01","2024-12-31"),
                           ("2025-2026-08-31","2025-01-01","2026-08-31")]:
        m=stats(c[c.date.between(start,end)]); m["period"]=name; rows.append(m)
    result=pd.DataFrame(rows); result.to_csv(OUT/"period_metrics.csv",index=False,encoding="utf-8-sig")
    r=c.net_nav.pct_change().fillna(0); years=max((c.date.iloc[-1]-c.date.iloc[0]).days/365.25,1/252)
    concentration=[]
    for n in (0,5,10,20):
        q=r.copy()
        if n:q.loc[q.nlargest(n).index]=0
        nav=(1+q).prod(); concentration.append({"removed_best_days":n,"final_nav":nav,
            "annualized_return":nav**(1/years)-1,"removed_return_sum":r.nlargest(n).sum() if n else 0})
    pd.DataFrame(concentration).to_csv(OUT/"best_day_concentration.csv",index=False,encoding="utf-8-sig")
    print(result[["period","annualized_return","max_drawdown","sharpe","average_exposure","turnover"]].to_string(index=False))
    print(pd.DataFrame(concentration).to_string(index=False))

if __name__=="__main__":main()
