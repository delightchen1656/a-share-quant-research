"""Point-in-time factor efficacy diagnostics before further strategy search."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m2_simple_baselines import load_features  # noqa
OUT=STUDY/"reports"/"m3_factor_diagnostics"

def main():
    OUT.mkdir(parents=True,exist_ok=True); x=load_features()
    g=x.groupby("symbol",sort=False)
    x["future20"]=g.qfq_close.shift(-20)/g.qfq_close.shift(-1)-1
    x=x[x.eligible & x.future20.notna()].copy(); x["year"]=x.date.dt.year
    x["mom_skip5"]=x.ret60-x.ret5; x["mom_skip20"]=x.ret120-x.ret20
    factors=["ret5","ret20","ret60","ret120","mom_skip5","mom_skip20","vol20",
             "vol60","position60","liq_ratio","amount20"]
    rows=[]
    for factor in factors:
        valid=x[["date","year",factor,"future20"]].dropna()
        valid["rank"]=valid.groupby("date")[factor].rank(pct=True)
        daily_ic=valid.groupby("date").apply(
            lambda z:z["rank"].corr(z.future20.rank(pct=True)),include_groups=False)
        for year,z in valid.groupby("year"):
            top=z[z["rank"]>=.9].future20.mean(); bottom=z[z["rank"]<=.1].future20.mean()
            ic=daily_ic[daily_ic.index.year==year]
            rows.append({"factor":factor,"year":year,"rank_ic":ic.mean(),
                         "ic_positive_share":(ic>0).mean(),"top_decile_future20":top,
                         "bottom_decile_future20":bottom,"top_minus_bottom":top-bottom})
    r=pd.DataFrame(rows); r.to_csv(OUT/"factor_by_year.csv",index=False,encoding="utf-8-sig")
    summary=r.groupby("factor").agg(mean_rank_ic=("rank_ic","mean"),
        positive_years=("rank_ic",lambda z:int((z>0).sum())),
        mean_top_bottom=("top_minus_bottom","mean"),
        positive_spread_years=("top_minus_bottom",lambda z:int((z>0).sum())),
        worst_year_spread=("top_minus_bottom","min")).sort_values("mean_top_bottom",ascending=False)
    summary.to_csv(OUT/"factor_summary.csv",encoding="utf-8-sig")
    print(summary.to_string())

if __name__=="__main__":main()
