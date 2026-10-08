"""Tradable post-limit-hit continuation/reversal event study."""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m2_simple_baselines import load_features  # noqa
OUT=STUDY/"reports"/"m3_limit_event_study"
ROUND_TRIP_COST=.006

def main():
    OUT.mkdir(parents=True,exist_ok=True); x=load_features(); g=x.groupby("symbol",sort=False)
    rows=[]
    for hold in (2,3,5,10,20):
        entry=g.qfq_close.shift(-1); exit_=g.qfq_close.shift(-(hold+1))
        x[f"f{hold}"]=exit_/entry-1-ROUND_TRIP_COST
    next_tradable=g.tradable.shift(-1).fillna(False)
    next_locked=g.one_price_up.shift(-1).fillna(True)
    accessible=next_tradable & ~next_locked
    events={
      "close_limit_any":x.pctChg.ge(9.5),
      "close_limit_opened":x.pctChg.ge(9.5)&~x.one_price_up,
      "intraday_limit_not_close":x.high.ge(x.preclose*1.095)&x.pctChg.lt(9.5),
      "limit_after_positive20":x.pctChg.ge(9.5)&x.ret20.gt(0),
      "limit_after_negative20":x.pctChg.ge(9.5)&x.ret20.le(0),
    }
    for name,mask in events.items():
        use=x[mask&accessible]
        for hold in (2,3,5,10,20):
            z=use[f"f{hold}"].dropna()
            for period,start,end in [("2018-2023","2018-01-01","2023-12-31"),
                                     ("2024","2024-01-01","2024-12-31"),
                                     ("2025-2026-08","2025-01-01","2026-08-31")]:
                q=use[use.date.between(start,end)][f"f{hold}"].dropna()
                rows.append({"event":name,"hold_days":hold,"period":period,"events":len(q),
                             "mean_net_return":q.mean(),"median_net_return":q.median(),
                             "win_rate":(q>0).mean()})
    r=pd.DataFrame(rows); r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    pivot=r.pivot_table(index=["event","hold_days"],columns="period",values="mean_net_return")
    pivot["minimum_period_mean"]=pivot.min(axis=1); pivot=pivot.sort_values("minimum_period_mean",ascending=False)
    pivot.to_csv(OUT/"mean_return_comparison.csv",encoding="utf-8-sig"); print(pivot.head(20).to_string())

if __name__=="__main__":main()
