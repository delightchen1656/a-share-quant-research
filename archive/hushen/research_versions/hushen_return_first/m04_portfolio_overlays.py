"""Portfolio overlays for R8, designed on 2018-2023 and validated later.

All overlay decisions use data through T close and affect T+1 return.  The
underlying R8 gross return and turnover are reconstructed from its saved curve.
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent; PROJECT=STUDY.parents[1]
BASE=STUDY/"reports"/"m3_reversal_regime"/"R8_低波反转分散40_curve.parquet"
INDEX=PROJECT/"data_pipeline"/"data"/"indices"/"000905.SH.parquet"
OUT=STUDY/"reports"/"m4_portfolio_overlays"
STOCK_COST=.003; ETF_COST=.0015
PERIODS=[("design_2018_2023","2018-01-01","2023-12-31"),
         ("validation_2024","2024-01-01","2024-12-31"),
         ("history_2025_202608","2025-01-01","2026-08-31"),
         ("full","2018-01-01","2026-08-31")]

def load():
    x=pd.read_parquet(BASE); x.date=pd.to_datetime(x.date); x=x.sort_values("date")
    x["base_gross_return"]=x.gross_nav.pct_change().fillna(0)
    x["base_net_return"]=x.net_nav.pct_change().fillna(0)
    idx=pd.read_parquet(INDEX); idx.date=pd.to_datetime(idx.date); idx=idx.sort_values("date")
    idx["index_close"]=pd.to_numeric(idx.close,errors="coerce")
    idx["index_return"]=idx.index_close.pct_change().fillna(0)
    x=x.merge(idx[["date","index_close","index_return"]],on="date",how="left")
    # Signals are calculated at T close; shift makes them executable from T+1.
    nav=x.net_nav
    x["nav_above_60"]=(nav>nav.rolling(60).mean()).shift(1).fillna(False)
    x["nav_above_120"]=(nav>nav.rolling(120).mean()).shift(1).fillna(False)
    x["nav_fast_slow"]=(nav.rolling(20).mean()>nav.rolling(60).mean()).shift(1).fillna(False)
    x["idx_above_120"]=(x.index_close>x.index_close.rolling(120).mean()).shift(1).fillna(False)
    x["idx_fast_slow"]=(x.index_close.rolling(20).mean()>x.index_close.rolling(60).mean()).shift(1).fillna(False)
    realized=x.base_net_return.rolling(20).std()*np.sqrt(252)
    x["vol_scale"]=(.16/realized.clip(lower=.05)).clip(.25,1).shift(1).fillna(.5)
    dd=nav/nav.cummax()-1
    x["drawdown"] = dd.shift(1).fillna(0)
    return x

def allocations(x,name):
    one=pd.Series(1.,index=x.index); zero=pd.Series(0.,index=x.index)
    if name=="O0_R8原版": return one,zero
    if name=="O1_策略60日趋势": return x.nav_above_60.map({True:1.,False:.30}),zero
    if name=="O2_策略120日趋势": return x.nav_above_120.map({True:1.,False:.30}),zero
    if name=="O3_策略双趋势":
        on=x.nav_above_120|x.nav_fast_slow; return on.map({True:1.,False:.25}),zero
    if name=="O4_组合波动目标": return x.vol_scale,zero
    if name=="O5_回撤分级":
        a=pd.Series(np.select([x.drawdown<=-.20,x.drawdown<=-.12,x.drawdown<=-.07],[.20,.45,.70],default=1.),index=x.index)
        return a,zero
    if name=="O6_回撤加趋势恢复":
        a=pd.Series(np.select([x.drawdown<=-.18,x.drawdown<=-.10],[.20,.50],default=1.),index=x.index)
        a[(x.nav_fast_slow)&(x.nav_above_60)]=1.; return a,zero
    if name=="O7_策略与指数确认":
        count=x.nav_above_60.astype(int)+x.idx_above_120.astype(int)
        return count.map({0:.20,1:.60,2:1.}),zero
    if name=="O8_R8加指数趋势":
        stock=pd.Series(.75,index=x.index); etf=x.idx_above_120.map({True:.25,False:0.}); return stock,etf
    if name=="O9_趋势轮换":
        stock=x.nav_above_60.map({True:1.,False:0.}); etf=((~x.nav_above_60)&x.idx_above_120).astype(float); return stock,etf
    if name=="O10_双资产分级":
        stock=x.nav_above_60.map({True:.75,False:.25}); etf=x.idx_above_120.map({True:.25,False:0.}); return stock,etf
    raise KeyError(name)

def run(x,name):
    stock,etf=allocations(x,name); stock=stock.clip(0,1); etf=etf.clip(0,1-stock)
    # Underlying rebalance cost scales with allocated capital. Allocation changes
    # add explicit one-way turnover cost for the stock and ETF sleeves.
    stock_cost=x.turnover*STOCK_COST*stock + stock.diff().abs().fillna(stock.iloc[0])*STOCK_COST
    etf_cost=etf.diff().abs().fillna(etf.iloc[0])*ETF_COST
    ret=stock*x.base_gross_return.fillna(0)+etf*x.index_return.fillna(0)-stock_cost-etf_cost
    y=pd.DataFrame({"date":x.date,"return":ret,"stock_weight":stock,"etf_weight":etf,
                    "total_exposure":stock+etf,"turnover_cost":stock_cost+etf_cost})
    y["nav"]=(1+y["return"]).cumprod(); return y

def stats(y):
    days=max((y.date.iloc[-1]-y.date.iloc[0]).days,1); r=y["return"]
    return {"final_nav":y.nav.iloc[-1],"annualized_return":y.nav.iloc[-1]**(365.25/days)-1,
            "max_drawdown":(y.nav/y.nav.cummax()-1).min(),
            "sharpe":np.sqrt(252)*r.mean()/r.std() if r.std() else 0,
            "average_exposure":y.total_exposure.mean(),"total_cost":y.turnover_cost.sum()}

def main():
    OUT.mkdir(parents=True,exist_ok=True); x=load()
    names=[f"O{i}_{n}" for i,n in enumerate(["R8原版","策略60日趋势","策略120日趋势","策略双趋势",
        "组合波动目标","回撤分级","回撤加趋势恢复","策略与指数确认","R8加指数趋势","趋势轮换","双资产分级"])]
    rows=[]
    for name in names:
        y=run(x,name); y.to_parquet(OUT/f"{name}_curve.parquet",index=False)
        for period,start,end in PERIODS:
            z=y[y.date.between(start,end)].copy()
            # Rebase each reported period; the rule state still comes from past data.
            z["nav"]=(1+z["return"]).cumprod(); m=stats(z)
            m.update({"overlay":name,"period":period}); rows.append(m)
    r=pd.DataFrame(rows); r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    wide=r.pivot(index="overlay",columns="period",values=["annualized_return","max_drawdown","sharpe"])
    wide.to_csv(OUT/"comparison.csv",encoding="utf-8-sig")
    print(r[r.period=="full"].sort_values("annualized_return",ascending=False).to_string(index=False))
    print("VALIDATION")
    print(r[r.period!="full"].pivot(index="overlay",columns="period",values="annualized_return").to_string())

if __name__=="__main__":main()
