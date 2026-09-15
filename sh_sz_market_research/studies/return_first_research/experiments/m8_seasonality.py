"""Point-in-time A-share calendar-month seasonality reproductions."""
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent; STUDY = HERE.parent
sys.path.insert(0, str(HERE))
from m3_reversal_regime import build, simulate  # noqa
from m2_simple_baselines import metrics  # noqa

OUT = STUDY / "reports" / "m8_seasonality"


def add_scores():
    x, state = build(); x = x.sort_values(["symbol", "date"])
    x["year"] = x.date.dt.year; x["month"] = x.date.dt.month
    monthly = (x.groupby(["symbol", "year", "month"], as_index=False)
               .agg(month_close=("qfq_close", "last"), month_date=("date", "max")))
    monthly = monthly.sort_values(["symbol", "year", "month"])
    monthly["month_return"] = monthly.groupby("symbol").month_close.pct_change(fill_method=None)
    # For a given calendar month, use only returns from that same month in prior years.
    sm = monthly.groupby(["symbol", "month"], sort=False).month_return
    monthly["season_mean"] = sm.transform(lambda s: s.shift(1).expanding().mean())
    monthly["season_count"] = sm.transform(lambda s: s.shift(1).expanding().count())
    monthly["season_hit"] = sm.transform(lambda s: s.shift(1).expanding().apply(lambda z: (z > 0).mean()))
    x = x.merge(monthly[["symbol", "year", "month", "season_mean", "season_count", "season_hit"]],
                on=["symbol", "year", "month"], how="left")
    e = x[x.eligible & (x.season_count >= 2)].copy(); d = e.groupby("date")
    hi = lambda c: d[c].rank(pct=True); lo = lambda c: 1-hi(c)
    e["S1_same_month"] = .65*hi("season_mean") + .20*hi("season_hit") + .15*lo("vol60")
    e["S2_season_lowrisk"] = .45*hi("season_mean") + .20*hi("season_hit") + .20*lo("vol60") + .15*lo("amount20")
    e["S3_season_reversal"] = (.40*hi("season_mean") + .30*lo("ret20")
        + .20*lo("vol60") + .10*lo("amount20")).where(e.ret120 > 0)
    cols = ["S1_same_month", "S2_season_lowrisk", "S3_season_reversal"]
    return x.merge(e[["date", "symbol"]+cols], on=["date", "symbol"], how="left"), state, cols


def period_rows(c):
    rows=[]
    for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),
                             ("验证期2024","2024-01-01","2024-12-31"),
                             ("验证期2025-2026-08","2025-01-01","2026-08-31"),
                             ("全周期","2018-01-01","2026-08-31")]:
        z=c[c.date.between(start,end)].copy(); z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod()
        z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod(); z["net_return"]=z.net_nav.pct_change().fillna(0)
        m=metrics(z); m["period"]=period; rows.append(m)
    return rows


def main():
    OUT.mkdir(parents=True,exist_ok=True); x,state,cols=add_scores(); rows=[]
    for score in cols:
        print(score,flush=True); c,_=simulate(x,state,score,"none",80,240,20)
        c.to_parquet(OUT/f"{score}_curve.parquet",index=False)
        for m in period_rows(c): m["strategy"]=score; rows.append(m)
    r=pd.DataFrame(rows); r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(r[r.period=="全周期"].sort_values("annualized_return",ascending=False).to_string(index=False))
    print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())


if __name__=="__main__": main()
