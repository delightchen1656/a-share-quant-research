"""Three-sleeve fixed frontier and drawdown-overlap diagnostics."""
from pathlib import Path
import itertools
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
OUT=STUDY/"reports"/"m9_three_sleeve_frontier"
FILES={
 "core":STUDY/"reports"/"m6_asymmetric_risk_state"/"blends"/"40日75_10日25_curve.parquet",
 "anti_max":STUDY/"reports"/"m7_public_strategy_reproductions"/"P1_anti_max_ivol_curve.parquet",
 "lowrisk_cluster":STUDY/"reports"/"m8_pit_style_clusters"/"C4_cluster_lowrisk_curve.parquet",
}

def load():
    out=None
    for name,path in FILES.items():
        z=pd.read_parquet(path).sort_values("date")
        r=z["return"] if "return" in z else z.net_nav.pct_change().fillna(0)
        q=pd.DataFrame({"date":z.date,name:r})
        out=q if out is None else out.merge(q,on="date")
    return out

def stats(z):
    nav=(1+z["return"]).cumprod(); days=max((z.date.iloc[-1]-z.date.iloc[0]).days,1); r=z["return"]
    return {"annualized_return":nav.iloc[-1]**(365.25/days)-1,"max_drawdown":(nav/nav.cummax()-1).min(),
            "sharpe":np.sqrt(252)*r.mean()/r.std(),"final_nav":nav.iloc[-1]}

def main():
    OUT.mkdir(parents=True,exist_ok=True); x=load(); assets=list(FILES)
    x[assets].corr().to_csv(OUT/"daily_correlation.csv",encoding="utf-8-sig")
    rows=[]
    grid=np.arange(0,1.0001,.05)
    for wc in grid:
        for wa in grid:
            wl=round(1-wc-wa,10)
            if wl < 0 or wl > 1: continue
            y=pd.DataFrame({"date":x.date,"return":wc*x.core+wa*x.anti_max+wl*x.lowrisk_cluster})
            for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),
                                     ("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
                m=stats(y[y.date.between(start,end)]);m.update({"core":wc,"anti_max":wa,"lowrisk_cluster":wl,"period":period});rows.append(m)
    r=pd.DataFrame(rows);r.to_csv(OUT/"grid_results.csv",index=False,encoding="utf-8-sig")
    full=r[r.period=="全周期"].copy(); full.to_csv(OUT/"full_frontier.csv",index=False,encoding="utf-8-sig")
    print("CORRELATION\n",x[assets].corr().to_string())
    print("\nTOP SHARPE\n",full.nlargest(15,"sharpe").to_string(index=False))

if __name__=="__main__":main()
