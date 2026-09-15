"""M2 signal-screen baselines for return-first main-board research.

This stage uses T close signals and T+1 close rebalance, qfq close returns for
economic PnL, explicit turnover cost, and raw daily fields for tradability and
one-price limit checks. Exact cash/share execution belongs to M5.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
PROJECT = STUDY.parents[1]
CACHE = PROJECT / "data_pipeline" / "data" / "derived" / "backtest_market_by_year"
OUT = STUDY / "reports" / "m2_simple_baselines"
START, END = pd.Timestamp("2018-01-01"), pd.Timestamp("2026-08-31")
ONE_WAY_COST = .003  # fee + spread/slippage stress approximation at signal-screen stage
TOP_N, REBALANCE = 30, 10


def load_features() -> pd.DataFrame:
    cols = ["date", "symbol", "open", "high", "low", "close", "preclose",
            "volume", "amount", "tradestatus", "pctChg", "isST", "qfq_close"]
    x = pd.concat([pd.read_parquet(CACHE / f"{y}.parquet", columns=cols)
                   for y in range(2018, 2027)], ignore_index=True)
    x.date = pd.to_datetime(x.date)
    x = x[x.date.between(START, END)].sort_values(["symbol", "date"])
    nums = ["open", "high", "low", "close", "preclose", "volume", "amount",
            "pctChg", "qfq_close"]
    for c in nums: x[c] = pd.to_numeric(x[c], errors="coerce")
    g = x.groupby("symbol", sort=False)
    x["age"] = g.cumcount() + 1
    x["ret1"] = g.qfq_close.pct_change(fill_method=None)
    for n in (5, 20, 60, 120): x[f"ret{n}"] = g.qfq_close.pct_change(n, fill_method=None)
    x["vol20"] = g.ret1.transform(lambda z: z.rolling(20).std())
    x["vol60"] = g.ret1.transform(lambda z: z.rolling(60).std())
    x["amount20"] = g.amount.transform(lambda z: z.rolling(20).mean())
    x["amount60"] = g.amount.transform(lambda z: z.rolling(60).mean())
    hi60 = g.qfq_close.transform(lambda z: z.rolling(60).max())
    lo60 = g.qfq_close.transform(lambda z: z.rolling(60).min())
    x["position60"] = (x.qfq_close-lo60)/(hi60-lo60)
    x["liq_ratio"] = x.amount20/x.amount60
    x["tradable"] = ((x.tradestatus.astype(str)=="1") & (x.isST.astype(str)!="1")
                     & x.volume.gt(0) & x.close.gt(0))
    x["one_price_up"] = ((x.high-x.low).abs()<1e-8) & x.pctChg.ge(9.5)
    x["one_price_down"] = ((x.high-x.low).abs()<1e-8) & x.pctChg.le(-9.5)
    x["eligible"] = (x.tradable & x.age.ge(120) & x.amount20.ge(50_000_000)
                     & x.vol20.between(.004,.065) & x.ret20.lt(.30))
    e = x[x.eligible].copy(); d=e.groupby("date")
    hi=lambda c:d[c].rank(pct=True)
    lo=lambda c:1-hi(c)
    e["score_A_return_rank"]=(.25*hi("ret20")+.35*hi("ret60")+.25*hi("ret120")
                              +.10*lo("vol60")+.05*hi("amount20"))
    pull = e.ret120.gt(0) & e.ret5.between(-.10,.02) & e.position60.between(.25,.85)
    e["score_B_pullback"]=(.42*hi("ret120")+.25*lo("ret5")+.18*lo("vol20")
                           +.15*hi("liq_ratio")).where(pull)
    # Point-in-time style groups approximate capital cohorts without historical
    # industry backfill: 120d strength quintile x 60d volatility tercile.
    e["strength_bucket"] = np.minimum((hi("ret120")*5).fillna(0).astype(int),4)
    e["vol_bucket"] = np.minimum((hi("vol60")*3).fillna(0).astype(int),2)
    grp=e.groupby(["date","strength_bucket","vol_bucket"])
    e["cohort_ret20"]=grp.ret20.transform("median")
    e["cohort_breadth"]=grp.ret20.transform(lambda z:(z>0).mean())
    cohort=e.cohort_ret20.gt(0) & e.cohort_breadth.ge(.55) & e.ret120.gt(0)
    e["score_C_cohort_diffusion"]=(.35*e.groupby("date").cohort_ret20.rank(pct=True)
        +.25*e.groupby("date").cohort_breadth.rank(pct=True)
        +.20*lo("ret5")+.20*hi("ret60")).where(cohort & e.ret5.lt(.08))
    e["score_D_liquidity_control"] = hi("amount20")
    scores=["score_A_return_rank","score_B_pullback","score_C_cohort_diffusion",
            "score_D_liquidity_control"]
    return x.merge(e[["date","symbol"]+scores],on=["date","symbol"],how="left")


def metrics(curve: pd.DataFrame) -> dict:
    r=curve.net_return; years=max((curve.date.iloc[-1]-curve.date.iloc[0]).days/365.25,1/252)
    total=curve.net_nav.iloc[-1]-1
    return {"final_nav":float(curve.net_nav.iloc[-1]),"total_return":float(total),
            "annualized_return":float(curve.net_nav.iloc[-1]**(1/years)-1),
            "max_drawdown":float((curve.net_nav/curve.net_nav.cummax()-1).min()),
            "sharpe":float(np.sqrt(252)*r.mean()/r.std()) if r.std() else 0,
            "gross_annualized_return":float(curve.gross_nav.iloc[-1]**(1/years)-1),
            "average_exposure":float(curve.exposure.mean()),
            "annual_turnover":float(curve.turnover.sum()/years)}


def simulate(x: pd.DataFrame, score: str) -> tuple[pd.DataFrame,dict]:
    dates=sorted(x.date.unique()); day={d:a.set_index("symbol") for d,a in x.groupby("date")}
    schedule=set(dates[119::REBALANCE]); current={}; pending=None; rows=[]
    gross=net=1.0
    for i,date in enumerate(dates):
        d=day[date]
        # Existing positions earn today's total return. Missing/suspended quotes
        # carry the last value instead of disappearing from NAV.
        port_ret=sum(w*float(d.at[s,"ret1"]) for s,w in current.items()
                     if s in d.index and np.isfinite(d.at[s,"ret1"]))
        gross*=1+port_ret; net*=1+port_ret
        turnover=0.0
        if pending is not None:
            target={}
            for s,w in pending.items():
                if s not in d.index: continue
                q=d.loc[s]
                if not bool(q.tradable) or bool(q.one_price_up): continue
                target[s]=w
            # Positions locked at one-price down retain their old weight.
            for s,w in current.items():
                if s in target: continue
                if s not in d.index or (bool(d.at[s,"tradable"]) and not bool(d.at[s,"one_price_down"])):
                    continue
                target[s]=w
            total=sum(target.values())
            if total>1: target={s:w/total for s,w in target.items()}
            all_names=set(current)|set(target)
            turnover=sum(abs(target.get(s,0)-current.get(s,0)) for s in all_names)
            net*=max(0,1-turnover*ONE_WAY_COST)
            current=target; pending=None
        rows.append({"date":date,"gross_nav":gross,"net_nav":net,"turnover":turnover,
                     "exposure":sum(current.values()),"positions":len(current)})
        if date in schedule:
            c=d[d[score].notna()].sort_values(score,ascending=False).head(TOP_N)
            pending={s:1/TOP_N for s in c.index}
    curve=pd.DataFrame(rows); curve["net_return"]=curve.net_nav.pct_change().fillna(0)
    return curve,metrics(curve)


def main():
    OUT.mkdir(parents=True,exist_ok=True); print("loading features",flush=True)
    x=load_features(); results=[]
    names={"score_A_return_rank":"A_可交易收益排序",
           "score_B_pullback":"B_强势股回踩",
           "score_C_cohort_diffusion":"C_风格群体扩散",
           "score_D_liquidity_control":"D_高流动性控制组"}
    for score,name in names.items():
        print(f"running {name}",flush=True); curve,m=simulate(x,score); m.update({"strategy":name})
        results.append(m); curve.to_parquet(OUT/f"{score}_curve.parquet",index=False)
    result=pd.DataFrame(results).sort_values("annualized_return",ascending=False)
    result.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    (OUT/"summary.json").write_text(json.dumps(result.to_dict("records"),ensure_ascii=False,indent=2),encoding="utf-8")
    print(result.to_string(index=False))

if __name__=="__main__": main()
