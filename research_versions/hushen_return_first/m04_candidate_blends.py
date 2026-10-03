"""Static capital sleeves across independently maintained candidate books."""
from pathlib import Path
import itertools
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
SRC=STUDY/"reports"/"m4_residual_reversal"; OUT=STUDY/"reports"/"m4_candidate_blends"
FILES={"Q3_80x40":"Q3_trend_residual_curve.parquet",
       "Q3_100x40":"Q3_trend_residual_100x40_curve.parquet",
       "Q3_50x60":"Q3_trend_residual_50x60_curve.parquet",
       "Q3_80x60":"Q3_trend_residual_80x60_curve.parquet"}
PERIODS=[("2018-2023","2018-01-01","2023-12-31"),("2024","2024-01-01","2024-12-31"),
         ("2025-2026-08","2025-01-01","2026-08-31"),("full","2018-01-01","2026-08-31")]

def stats(date,r):
    nav=(1+r).cumprod(); days=max((date.iloc[-1]-date.iloc[0]).days,1)
    return {"annualized_return":nav.iloc[-1]**(365.25/days)-1,
            "max_drawdown":(nav/nav.cummax()-1).min(),
            "sharpe":np.sqrt(252)*r.mean()/r.std() if r.std() else 0,"final_nav":nav.iloc[-1]}

def main():
    OUT.mkdir(parents=True,exist_ok=True); series={}
    date=None
    for name,file in FILES.items():
        x=pd.read_parquet(SRC/file); x.date=pd.to_datetime(x.date); date=x.date
        series[name]=x.net_nav.pct_change().fillna(0)
    combos=[]
    for a,b in itertools.combinations(series,2):
        for wa in (.25,.50,.75): combos.append((f"{a}_{wa:.2f}+{b}_{1-wa:.2f}",wa*series[a]+(1-wa)*series[b]))
    rows=[]
    for name,r in combos:
        for period,start,end in PERIODS:
            mask=date.between(start,end); m=stats(date[mask].reset_index(drop=True),r[mask].reset_index(drop=True))
            m.update({"blend":name,"period":period}); rows.append(m)
    result=pd.DataFrame(rows); result.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(result[result.period=="full"].sort_values(["annualized_return","max_drawdown"],ascending=[False,False]).head(15).to_string(index=False))

if __name__=="__main__":main()
