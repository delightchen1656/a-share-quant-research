"""Thirty genuinely different technical routes under a 12% drawdown mandate.

Selection uses 2020-2024 only.  Only three winners, one per distinct family,
are evaluated on the locked 2025-2026/7 interval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
MIG = ROOT / "data_pipeline"
CACHE = MIG / "data" / "derived" / "backtest_market_by_year"
OUT = Path(__file__).resolve().parent / "outputs"
INITIAL, LOT = 1_000_000.0, 100
SLIP, COMMISSION, TRANSFER, MIN_FEE = .002, .0003, .00001, 5.0
DESIGN_START, DESIGN_END = pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")
TEST_START, TEST_END = pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-31")


def fee(v): return max(MIN_FEE, v*COMMISSION)+v*TRANSFER
def tax(v,d): return v*(.0005 if d>=pd.Timestamp("2023-08-28") else .001)


def load_features():
    cols=["date","symbol","exchange","open","high","low","close","preclose","volume","amount",
          "tradestatus","pctChg","isST","qfq_close"]
    x=pd.concat([pd.read_parquet(CACHE/f"{y}.parquet",columns=cols) for y in range(2018,2027)],ignore_index=True)
    x.date=pd.to_datetime(x.date)
    nums=["open","high","low","close","preclose","volume","amount","pctChg","qfq_close"]
    x[nums]=x[nums].apply(pd.to_numeric,errors="coerce")
    x.sort_values(["symbol","date"],inplace=True)
    g=x.groupby("symbol",sort=False)
    x["age"]=g.cumcount()+1
    x["r1"]=g.qfq_close.pct_change(); x["r5"]=g.qfq_close.pct_change(5)
    for n in (10,20,40,60,120,250): x[f"r{n}"]=g.qfq_close.pct_change(n)
    for n in (20,60):
        x[f"vol{n}"]=g.r1.transform(lambda s:s.rolling(n).std())
        x[f"ma{n}"]=g.qfq_close.transform(lambda s:s.rolling(n).mean())
    x["ma120"]=g.qfq_close.transform(lambda s:s.rolling(120).mean())
    x["hi20"]=g.qfq_close.transform(lambda s:s.rolling(20).max())
    x["hi120"]=g.qfq_close.transform(lambda s:s.rolling(120).max())
    x["hi250"]=g.qfq_close.transform(lambda s:s.rolling(250).max())
    x["lo20"]=g.qfq_close.transform(lambda s:s.rolling(20).min())
    x["amount20"]=g.amount.transform(lambda s:s.rolling(20).mean())
    x["amount60"]=g.amount.transform(lambda s:s.rolling(60).mean())
    x["down20"]=g.r1.transform(lambda s:s.where(s<0,0).rolling(20).std())
    x["up_ratio60"]=g.r1.transform(lambda s:(s>0).rolling(60).mean())
    x["squeeze"]=x.vol20/x.vol60
    x["break120"]=x.qfq_close/x.hi120
    x["break250"]=x.qfq_close/x.hi250
    x["pullback20"]=(x.qfq_close-x.lo20)/(x.hi20-x.lo20)
    x["liq_change"]=x.amount20/x.amount60
    x["trend_gap"]=x.qfq_close/x.ma120-1
    x["eligible"]=(x.age>=250)&(x.tradestatus.astype(str)=="1")&(x.isST.astype(str)!="1")&(
        x.amount20>=1e8)&x.vol20.between(.004,.055)&x.r20.lt(.30)&x.trend_gap.between(-.15,.80)

    # Build all route scores as daily percentile combinations. No future fields.
    e=x[x.eligible].copy(); d=e.groupby("date")
    hi=lambda c:d[c].rank(pct=True)
    lo=lambda c:1-d[c].rank(pct=True)
    scores={
      "trend_relative":.45*hi("r250")+.30*hi("r120")+.15*hi("up_ratio60")+.10*lo("vol60"),
      "trend_absolute":.40*hi("trend_gap")+.30*hi("r60")+.20*hi("up_ratio60")+.10*lo("down20"),
      "trend_smooth":.35*hi("r120")+.30*hi("up_ratio60")+.25*lo("vol20")+.10*lo("down20"),
      "break_120":.45*hi("break120")+.25*hi("r60")+.20*hi("liq_change")+.10*lo("vol20"),
      "break_250":.45*hi("break250")+.25*hi("r120")+.15*hi("up_ratio60")+.15*hi("liq_change"),
      "squeeze_break":.35*lo("squeeze")+.30*hi("break120")+.20*hi("r20")+.15*hi("liq_change"),
      "pullback_trend":.35*hi("r120")+.25*lo("pullback20")+.20*hi("up_ratio60")+.20*lo("down20"),
      "reversal_5":.35*lo("r5")+.25*hi("r120")+.20*lo("down20")+.20*hi("break120"),
      "reversal_20":.35*lo("r20")+.30*hi("r250")+.20*lo("vol20")+.15*hi("liq_change"),
      "lowvol_strength":.40*lo("vol60")+.25*hi("r120")+.20*lo("down20")+.15*hi("up_ratio60"),
      "downside_quality":.40*lo("down20")+.25*hi("up_ratio60")+.20*hi("r60")+.15*lo("vol20"),
      "contraction":.40*lo("squeeze")+.25*hi("r120")+.20*lo("down20")+.15*hi("break120"),
      "breadth_leader":.40*hi("r60")+.25*hi("up_ratio60")+.20*hi("break120")+.15*lo("vol20"),
      "breadth_laggard":.35*lo("r20")+.25*hi("r120")+.25*lo("down20")+.15*hi("up_ratio60"),
      "dispersion_quality":.35*hi("r120")+.30*lo("vol60")+.20*hi("break250")+.15*hi("liq_change"),
      "liquid_momentum":.35*hi("r120")+.25*hi("amount20")+.20*hi("liq_change")+.20*lo("down20"),
      "liquid_lowvol":.35*hi("amount20")+.30*lo("vol60")+.20*hi("r60")+.15*hi("up_ratio60"),
      "turnover_expansion":.35*hi("liq_change")+.30*hi("r60")+.20*hi("break120")+.15*lo("down20"),
      "quality_vote":(hi("r120")+hi("r60")+lo("vol60")+lo("down20")+hi("up_ratio60"))/5,
      "multi_horizon":.25*hi("r20")+.25*hi("r60")+.25*hi("r120")+.15*hi("r250")+.10*lo("down20"),
      "stable_break":.30*hi("break250")+.25*lo("vol60")+.20*lo("down20")+.15*hi("up_ratio60")+.10*hi("liq_change"),
      "fast_rotation":.40*hi("r20")+.25*hi("r60")+.20*hi("liq_change")+.15*lo("down20"),
      "slow_rotation":.45*hi("r250")+.30*hi("r120")+.15*lo("vol60")+.10*hi("amount20"),
      "balanced_rotation":.30*hi("r120")+.25*hi("r60")+.20*lo("vol60")+.15*lo("down20")+.10*hi("liq_change"),
      "tail_safe":.40*lo("down20")+.30*lo("vol60")+.20*hi("r120")+.10*hi("break120"),
      "crash_resistant":.35*lo("down20")+.25*lo("r5")+.20*hi("r250")+.20*lo("vol20"),
      "barbell":.30*hi("r120")+.30*lo("vol60")+.20*hi("break250")+.20*lo("r5"),
      "trend_recovery":.35*hi("r250")+.25*lo("r20")+.20*hi("up_ratio60")+.20*lo("down20"),
      "confirmed_recovery":.30*lo("r20")+.25*hi("r5")+.20*hi("r120")+.15*hi("liq_change")+.10*lo("vol20"),
      "defensive_growth":.30*hi("r120")+.30*lo("vol60")+.25*lo("down20")+.15*hi("amount20"),
    }
    for name,val in scores.items(): e[name]=val
    x=x.merge(e[["date","symbol"]+list(scores)],on=["date","symbol"],how="left")
    breadth=x.groupby("date").agg(breadth=("eligible","mean"),median20=("r20","median")).reset_index()
    idx=pd.read_parquet(MIG/"data"/"indices"/"000905.SH.parquet"); idx.date=pd.to_datetime(idx.date)
    c=pd.to_numeric(idx.close,errors="coerce")
    state=pd.DataFrame({"date":idx.date,"i20":c.pct_change(20),"i60":c.pct_change(60),"i120":c.pct_change(120),
                        "ivol20":c.pct_change().rolling(20).std()}).merge(breadth,on="date",how="left")
    return x,state,list(scores)


ROUTES = [
 # Round, route, family, rebalance sessions, count, max exposure, vol target, risk style
 (1,"trend_relative","trend",20,50,.80,.10,"invvol"),(1,"trend_absolute","trend",10,50,.70,.09,"equal"),(1,"trend_smooth","trend",20,60,.85,.10,"invvol"),
 (2,"break_120","breakout",10,50,.75,.10,"equal"),(2,"break_250","breakout",20,60,.85,.11,"invvol"),(2,"squeeze_break","breakout",5,40,.65,.09,"invvol"),
 (3,"pullback_trend","reversal",10,50,.70,.09,"invvol"),(3,"reversal_5","reversal",5,60,.55,.08,"equal"),(3,"reversal_20","reversal",10,50,.60,.08,"invvol"),
 (4,"lowvol_strength","lowvol",20,60,.90,.10,"invvol"),(4,"downside_quality","lowvol",10,50,.75,.09,"invdown"),(4,"contraction","lowvol",20,50,.75,.09,"invvol"),
 (5,"breadth_leader","breadth",10,50,.80,.10,"invvol"),(5,"breadth_laggard","breadth",10,60,.65,.08,"equal"),(5,"dispersion_quality","breadth",20,50,.85,.10,"invvol"),
 (6,"liquid_momentum","liquidity",10,50,.85,.10,"equal"),(6,"liquid_lowvol","liquidity",20,60,.90,.10,"invvol"),(6,"turnover_expansion","liquidity",5,40,.65,.09,"equal"),
 (7,"quality_vote","ensemble",20,50,.85,.10,"invvol"),(7,"multi_horizon","ensemble",10,50,.75,.09,"invvol"),(7,"stable_break","ensemble",20,60,.90,.10,"invdown"),
 (8,"fast_rotation","rotation",5,40,.60,.08,"equal"),(8,"slow_rotation","rotation",20,70,.90,.11,"invvol"),(8,"balanced_rotation","rotation",10,50,.80,.10,"invvol"),
 (9,"tail_safe","defensive",20,60,.90,.09,"invdown"),(9,"crash_resistant","defensive",10,50,.65,.08,"invvol"),(9,"barbell","defensive",20,60,.85,.10,"invvol"),
 (10,"trend_recovery","recovery",10,50,.75,.09,"invvol"),(10,"confirmed_recovery","recovery",5,40,.60,.08,"equal"),(10,"defensive_growth","recovery",20,60,.90,.10,"invdown"),
]


@dataclass
class Book:
    cash:float=INITIAL; pos:dict=field(default_factory=dict); curve:list=field(default_factory=list); trades:list=field(default_factory=list)
    prev:dict=field(default_factory=dict); high:float=INITIAL; recent:list=field(default_factory=list)


def desired_exposure(book, st, cap, target_vol):
    # Continuous, past-only exposure control shared by every route.
    regime=1.0 if st.i60>=0 and st.breadth>=.20 else .65 if st.i20>=-.04 else .30
    if st.i120<-.12 and st.breadth<.16: regime=.10
    volscale=1.0
    if len(book.recent)>=20:
        realized=np.std(book.recent[-20:],ddof=1)*np.sqrt(252)
        volscale=np.clip(target_vol/max(realized,.035),.20,1.0)
    dd=(book.curve[-1]["equity"]/book.high-1) if book.curve else 0
    budget=1.0 if dd>-.04 else .75 if dd>-.07 else .45 if dd>-.095 else .15
    if dd<=-.095 and st.i20>0 and st.i60>0 and st.breadth>.25: budget=.40
    return float(np.clip(cap*regime*volscale*budget,.03,cap))


def summarize(curve,trades):
    c=pd.DataFrame(curve); t=pd.DataFrame(trades); total=c.equity.iloc[-1]/INITIAL-1
    years=(c.date.iloc[-1]-c.date.iloc[0]).days/365.25; dr=c.equity.pct_change().dropna()
    return {"final_equity":c.equity.iloc[-1],"annualized_return":(1+total)**(1/years)-1,
      "total_return":total,"max_drawdown":(c.equity/c.equity.cummax()-1).min(),
      "sharpe":np.sqrt(252)*dr.mean()/dr.std() if dr.std() else 0,"average_positions":c.positions.mean(),
      "average_invested_ratio":c.invested_ratio.mean(),
      "closed_trades":len(t),"win_rate":float((t["return"]>0).mean()) if len(t) else np.nan}


def prepare_context(data,state,start,end):
    z=data[data.date.between(start,end)]
    dates=sorted(z.date.unique())
    days={d:a.set_index("symbol") for d,a in z.groupby("date")}
    last=data[(data.tradestatus.astype(str)=="1")&data.volume.gt(0)].groupby("symbol").date.max().to_dict()
    return dates,days,state.set_index("date"),last,data.date.max()


def simulate(data,state,route,start,end,context=None):
    rnd,score,family,step,count,cap,tvol,weight_style=route
    dates,days,sm,last,data_end=context or prepare_context(data,state,start,end)
    b=Book(); pending=None
    prior_state=None
    for i,date in enumerate(dates):
        day=days[date]; st=prior_state if prior_state is not None else sm.loc[date]
        eqopen=b.cash+sum(p["qty"]*day.loc[s].open for s,p in b.pos.items() if s in day.index)
        expo=desired_exposure(b,st,cap,tvol)
        # Corporate-action share reconciliation.
        for s,p in list(b.pos.items()):
            if s in day.index and s in b.prev and day.loc[s].preclose>0:
                factor=b.prev[s]/day.loc[s].preclose
                if factor>=1.1:
                    sf=round(factor,1); p["qty"]=int(round(p["qty"]*sf)); p["cost"]/=sf
        orders=pending; pending=None
        target=dict(orders or [])
        for s,p in list(b.pos.items()):
            if s not in day.index: continue
            r=day.loc[s]
            final=last.get(s)==date and date<data_end
            if not final and orders is None: continue
            if str(r.tradestatus)!="1" or r.volume<=0 or r.open<=0: continue
            locked=r.high==r.low and r.pctChg<=-9.5
            tq=int(eqopen*expo*target.get(s,0)/r.open/LOT)*LOT
            qty=p["qty"] if final else max(0,p["qty"]-tq)
            if qty and (not locked or final):
                px=r.close*.90 if final else r.open*(1-SLIP); value=qty*px; b.cash+=value-fee(value)-tax(value,date)
                p["realized"]+=value-fee(value)-tax(value,date); p["qty"]-=qty
                if p["qty"]<=0:
                    b.trades.append({"symbol":s,"entry":p["entry"],"exit":date,"return":p["realized"]/p["initial"]}); del b.pos[s]
        for s,w in orders or []:
            if s not in day.index: continue
            r=day.loc[s]
            if str(r.tradestatus)!="1" or str(r.isST)=="1" or r.volume<=0 or r.open<=0 or (r.high==r.low and r.pctChg>=9.5): continue
            current=b.pos.get(s,{}).get("qty",0)*r.open; value=min(max(0,eqopen*expo*w-current),r.amount*.03)
            px=r.open*(1+SLIP); qty=int(value/px/LOT)*LOT; total=qty*px+fee(qty*px) if qty>=LOT else np.inf
            while qty>=LOT and total>b.cash: qty-=LOT; total=qty*px+fee(qty*px)
            if qty<LOT: continue
            b.cash-=total
            if s in b.pos:
                p=b.pos[s]; old=p["cost"]*p["qty"]; p["qty"]+=qty; p["cost"]=(old+total)/p["qty"]; p["realized"]-=total; p["initial"]+=total
            else:b.pos[s]={"qty":qty,"cost":total/qty,"entry":date,"realized":-total,"initial":total}
        equity=b.cash+sum(p["qty"]*day.loc[s].close for s,p in b.pos.items() if s in day.index)
        prev=b.curve[-1]["equity"] if b.curve else INITIAL; b.recent.append(equity/prev-1); b.high=max(b.high,equity)
        invested=sum(p["qty"]*day.loc[s].close for s,p in b.pos.items() if s in day.index)
        b.curve.append({"date":date,"equity":equity,"positions":len(b.pos),"target_exposure":expo,
                        "invested_ratio":invested/equity if equity>0 else 0}); b.prev.update(day.close.to_dict())
        if i%step==step-1:
            cand=day[day[score].notna()].sort_values(score,ascending=False).head(count*2).reset_index()
            held=[s for s in b.pos if s in set(cand.head(min(count*2,100)).symbol)]
            names=(held+[s for s in cand.symbol if s not in held])[:count]; cand=cand.set_index("symbol").loc[names].reset_index()
            risk=cand.down20 if weight_style=="invdown" else cand.vol60 if weight_style=="invvol" else pd.Series(1,index=cand.index)
            w=1/risk.clip(.006,.06) if weight_style!="equal" else pd.Series(1,index=cand.index); w=w/w.sum(); w=w.clip(upper=.035); w=w/w.sum()
            pending=list(zip(cand.symbol,w))
        prior_state=sm.loc[date]
    return summarize(b.curve,b.trades),pd.DataFrame(b.curve),pd.DataFrame(b.trades)


def main():
    OUT.mkdir(parents=True,exist_ok=True); data,state,_=load_features(); rows=[]
    design_context=prepare_context(data,state,DESIGN_START,DESIGN_END)
    test_context=prepare_context(data,state,TEST_START,TEST_END)
    for n,route in enumerate(ROUTES,1):
        print(f"[{n}/30] round={route[0]} route={route[1]}",flush=True)
        m,c,t=simulate(data,state,route,DESIGN_START,DESIGN_END,design_context); m.update({"round":route[0],"route":route[1],"family":route[2]}); rows.append(m)
        print(json.dumps({k:float(v) if isinstance(v,(np.floating,np.integer)) else v for k,v in m.items()},ensure_ascii=False),flush=True)
    design=pd.DataFrame(rows); design.to_csv(OUT/"design_30_routes.csv",index=False,encoding="utf-8-sig")
    ok=design[(design.max_drawdown>=-.12)&design.average_invested_ratio.between(.30,.80)].copy()
    pool=ok if len(ok)>=3 else design[design.average_invested_ratio.between(.30,.80)].copy()
    # Greedy one-per-family selection, annual return first.
    winners=[]
    for row in pool.sort_values(["annualized_return","max_drawdown"],ascending=[False,False]).itertuples():
        if row.family in {x.family for x in winners}: continue
        winners.append(row)
        if len(winners)==3: break
    tests=[]; curves={}
    route_map={r[1]:r for r in ROUTES}
    for w in winners:
        m,c,t=simulate(data,state,route_map[w.route],TEST_START,TEST_END,test_context); m.update({"route":w.route,"family":w.family,"period":"2025-2026/7"}); tests.append(m); curves[w.route]=c.set_index("date").equity.pct_change()
        c.to_parquet(OUT/f"test_{w.route}_curve.parquet",index=False); t.to_csv(OUT/f"test_{w.route}_trades.csv",index=False,encoding="utf-8-sig")
    corr=pd.DataFrame(curves).corr() if curves else pd.DataFrame(); corr.to_csv(OUT/"winner_return_correlation.csv",encoding="utf-8-sig")
    pd.DataFrame(tests).to_csv(OUT/"locked_test_top3.csv",index=False,encoding="utf-8-sig")
    selection={"hard_constraint_candidates":len(ok),"selection_period":"2020-2024","holdout_used":False,"winners":[w.route for w in winners]}
    (OUT/"selection.json").write_text(json.dumps(selection,ensure_ascii=False,indent=2),encoding="utf-8")
    print(design.sort_values("annualized_return",ascending=False).head(10).to_string(index=False),flush=True); print(pd.DataFrame(tests).to_string(index=False),flush=True); print(corr.to_string(),flush=True)


if __name__=="__main__":main()
