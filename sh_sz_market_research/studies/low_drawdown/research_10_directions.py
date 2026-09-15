"""From-scratch mainboard low-drawdown research, ten sequential structures.

Technical data only.  Signals use completed T bars and orders use T+1 raw open.
2025-2026/7 is reported only after all rules are frozen on 2020-2024.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data_pipeline"
CACHE = SOURCE / "data" / "derived" / "backtest_market_by_year"
OUT = Path(__file__).resolve().parent / "outputs"
START, DESIGN_END, END = pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31"), pd.Timestamp("2026-07-31")
INITIAL = 1_000_000.0
LOT, TARGET_COUNT, MIN_COUNT, MAX_COUNT = 100, 50, 30, 80
SLIPPAGE, COMMISSION, TRANSFER, MIN_FEE = .002, .0003, .00001, 5.0

VARIANTS = [
    ("D0", "低波动趋势基础", set()),
    ("D1", "横截面多因子与排名缓冲", {"multifactor", "buffer"}),
    ("D2", "增加风险平价", {"multifactor", "buffer", "risk_parity"}),
    ("D3", "增加市场状态仓位", {"multifactor", "buffer", "risk_parity", "regime"}),
    ("D4", "增加组合波动目标", {"multifactor", "buffer", "risk_parity", "regime", "vol_target"}),
    ("D5", "增加组合回撤保护", {"multifactor", "buffer", "risk_parity", "regime", "vol_target", "dd_guard"}),
    ("D6", "增加行业分散", {"multifactor", "buffer", "risk_parity", "regime", "vol_target", "dd_guard", "industry_cap"}),
    ("D7", "增加收益风险双评分", {"multifactor", "buffer", "risk_parity", "regime", "vol_target", "dd_guard", "industry_cap", "dual_score"}),
    ("D8", "增加分批建仓", {"multifactor", "buffer", "risk_parity", "regime", "vol_target", "dd_guard", "industry_cap", "dual_score", "staged"}),
    ("D9", "增加现金硬保护", {"multifactor", "buffer", "risk_parity", "regime", "vol_target", "dd_guard", "industry_cap", "dual_score", "staged", "cash_guard"}),
]


def fee(amount):
    return max(MIN_FEE, amount * COMMISSION) + amount * TRANSFER


def tax(amount, date):
    return amount * (.0005 if date >= pd.Timestamp("2023-08-28") else .001)


def load_data():
    use = ["date", "symbol", "exchange", "open", "high", "low", "close", "preclose",
           "volume", "amount", "tradestatus", "pctChg", "isST", "qfq_close"]
    frames = [pd.read_parquet(CACHE / f"{y}.parquet", columns=use) for y in range(2018, 2027)]
    x = pd.concat(frames, ignore_index=True)
    x["date"] = pd.to_datetime(x.date)
    for c in ["open", "high", "low", "close", "preclose", "volume", "amount", "pctChg", "qfq_close"]:
        x[c] = pd.to_numeric(x[c], errors="coerce")
    x.sort_values(["symbol", "date"], inplace=True)
    g = x.groupby("symbol", sort=False)
    x["listing_days"] = g.cumcount() + 1
    x["ret20"] = g.qfq_close.pct_change(20)
    x["ret60"] = g.qfq_close.pct_change(60)
    x["ret120"] = g.qfq_close.pct_change(120)
    x["ret1"] = g.qfq_close.pct_change()
    x["vol20"] = g.ret1.transform(lambda s: s.rolling(20).std())
    x["vol60"] = g.ret1.transform(lambda s: s.rolling(60).std())
    x["ma60"] = g.qfq_close.transform(lambda s: s.rolling(60).mean())
    x["ma120"] = g.qfq_close.transform(lambda s: s.rolling(120).mean())
    x["amount20"] = g.amount.transform(lambda s: s.rolling(20).mean())
    x["peak60"] = g.qfq_close.transform(lambda s: s.rolling(60).max())
    x["dd60"] = x.qfq_close / x.peak60 - 1
    x["downside20"] = g.ret1.transform(lambda s: s.where(s < 0, 0).rolling(20).std())
    x["eligible"] = ((x.tradestatus.astype(str) == "1") & (x.isST.astype(str) != "1")
        & (x.listing_days >= 120) & (x.amount20 >= 100_000_000) & (x.qfq_close > x.ma120)
        & x.ret120.between(-.10, .80) & x.ret20.lt(.25) & x.vol20.between(.005, .05))

    # Cross-sectional percentile scores are scale-stable across years.
    elig = x[x.eligible].copy()
    bydate = elig.groupby("date")
    p60 = bydate.ret60.rank(pct=True)
    p120 = bydate.ret120.rank(pct=True)
    plowvol = 1 - bydate.vol20.rank(pct=True)
    pdown = 1 - bydate.downside20.rank(pct=True)
    pliq = bydate.amount20.rank(pct=True)
    ptrend = bydate.dd60.rank(pct=True)
    elig["base_score"] = .42*p120 + .25*p60 + .23*plowvol + .10*ptrend
    elig["multi_score"] = .27*p120 + .22*p60 + .18*plowvol + .13*pdown + .10*pliq + .10*ptrend
    # A technical-only reward/risk proxy: smooth strength divided by downside risk.
    elig["dual_score"] = elig.multi_score + .12*pdown + .08*plowvol - .08*bydate.ret20.rank(pct=True)
    x = x.merge(elig[["date", "symbol", "base_score", "multi_score", "dual_score"]],
                on=["date", "symbol"], how="left")

    mapping = pd.read_csv(SOURCE / "data" / "metadata" / "current_industry_map.csv",
                          dtype=str, encoding="utf-8-sig")
    imap = mapping.drop_duplicates("symbol").set_index("symbol").industry.to_dict()
    x["industry"] = x.symbol.map(imap)

    breadth = x.groupby("date").eligible.mean().rename("breadth")
    idx = pd.read_parquet(SOURCE / "data" / "indices" / "000905.SH.parquet")
    idx["date"] = pd.to_datetime(idx.date)
    ic = pd.to_numeric(idx.close, errors="coerce")
    state = pd.DataFrame({"date": idx.date, "idx20": ic.pct_change(20), "idx60": ic.pct_change(60),
                          "idx120": ic.pct_change(120), "idx_vol20": ic.pct_change().rolling(20).std()})
    state = state.set_index("date").join(breadth).reset_index()
    return x, state


@dataclass
class Account:
    cash: float = INITIAL
    positions: dict = field(default_factory=dict)
    curve: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    prev_close: dict = field(default_factory=dict)
    highwater: float = INITIAL
    recent_returns: list = field(default_factory=list)


def exposure_for(modes, st, account):
    exposure = .90
    if "regime" in modes:
        if st.idx60 < 0 or st.breadth < .18:
            exposure = .45
        elif st.idx20 < 0 or st.breadth < .25:
            exposure = .65
        elif st.idx120 > 0 and st.breadth >= .32:
            exposure = .95
        else:
            exposure = .80
    if "vol_target" in modes and len(account.recent_returns) >= 20:
        vol = np.std(account.recent_returns[-20:], ddof=1) * np.sqrt(252)
        exposure *= np.clip(.12 / max(vol, .04), .35, 1.0)
    dd = account.curve[-1]["equity"] / account.highwater - 1 if account.curve else 0
    if "dd_guard" in modes:
        if dd <= -.105:
            # Keep a small recovery sleeve; a zero allocation would permanently
            # lock the account below its historical high-water mark.
            recovery = st.idx20 > 0 and st.idx60 > 0 and st.breadth >= .30
            exposure *= .45 if recovery else .10
        else:
            exposure *= .30 if dd <= -.08 else .55 if dd <= -.06 else .80 if dd <= -.04 else 1
    if "cash_guard" in modes and (st.idx60 < -.08 or (st.idx20 < -.05 and st.breadth < .18)):
        exposure = min(exposure, .10)
    return float(np.clip(exposure, 0, 1))


def metrics(curve, trades, start_cash=INITIAL):
    c = pd.DataFrame(curve)
    t = pd.DataFrame(trades)
    total = c.equity.iloc[-1] / start_cash - 1
    years = max((c.date.iloc[-1] - c.date.iloc[0]).days / 365.25, 1/12)
    dr = c.equity.pct_change().dropna()
    return {"final_equity": c.equity.iloc[-1], "total_return": total,
            "annualized_return": (1+total)**(1/years)-1,
            "max_drawdown": (c.equity/c.equity.cummax()-1).min(),
            "sharpe": np.sqrt(252)*dr.mean()/dr.std() if dr.std() else 0,
            "average_positions": c.positions.mean(), "min_positions": c.positions.min(),
            "max_positions": c.positions.max(), "closed_trades": len(t),
            "win_rate": (t["return"] > 0).mean() if len(t) else np.nan}


def simulate(data, states, modes, start, end):
    x = data[data.date.between(start, end)]
    dates = sorted(x.date.unique())
    days = {d: z.set_index("symbol") for d, z in x.groupby("date")}
    smap = states.set_index("date")
    account = Account()
    pending = []
    prior_state = None
    last_trade = data[(data.tradestatus.astype(str)=="1") & data.volume.gt(0)].groupby("symbol").date.max().to_dict()
    dataset_last = data.date.max()
    for k, date in enumerate(dates):
        day = days[date]
        st = prior_state if prior_state is not None else smap.loc[date]
        open_equity = account.cash + sum(p["qty"]*day.loc[s].open for s,p in account.positions.items() if s in day.index)
        exposure = exposure_for(modes, st, account)

        # Corporate actions.
        for s,p in list(account.positions.items()):
            if s not in day.index or s not in account.prev_close: continue
            row = day.loc[s]; factor = account.prev_close[s]/row.preclose if row.preclose > 0 else 1
            if factor >= 1.1:
                sf = round(factor, 1); old=p["qty"]
                dividend=max(0, account.prev_close[s]-row.preclose*sf)
                account.cash += old*dividend; p["qty"]=int(round(old*sf)); p["cost"]=(p["cost"]-dividend)/sf

        # A target formed at the prior weekly close is executed once on T+1.
        orders, pending = pending, []
        has_rebalance = bool(orders)
        desired = {z[0]: z[1] for z in orders}
        for s,p in list(account.positions.items()):
            if s not in day.index: continue
            row=day.loc[s]
            if str(row.tradestatus)!="1" or row.volume<=0 or row.open<=0: continue
            final_delist = last_trade.get(s)==date and date < dataset_last
            if not has_rebalance and not final_delist:
                continue
            locked_down = row.high==row.low and row.pctChg<=-9.5
            target_value = open_equity * exposure * desired.get(s, 0)
            target_qty = int(target_value/row.open/LOT)*LOT
            if "staged" in modes and s in desired:
                target_qty = min(target_qty, p["qty"] + max(LOT, target_qty//2//LOT*LOT))
            sell_qty = max(0, p["qty"]-target_qty)
            if final_delist: sell_qty=p["qty"]
            if sell_qty and (not locked_down or final_delist):
                px = row.close*.90 if final_delist else row.open*(1-SLIPPAGE)
                amount=sell_qty*px; proceeds=amount-fee(amount)-tax(amount,date)
                account.cash+=proceeds; p["realized"]+=proceeds; p["qty"]-=sell_qty
                if p["qty"]<=0:
                    account.trades.append({"symbol":s,"entry":p["entry_date"],"exit":date,
                        "reason":"DELIST" if final_delist else "REBALANCE","return":p["realized"]/p["initial"]})
                    del account.positions[s]

        # Buy/increase only from the prior completed-bar target.
        for s,w in orders:
            if s not in day.index: continue
            row=day.loc[s]
            if str(row.tradestatus)!="1" or str(row.isST)=="1" or row.volume<=0 or row.open<=0: continue
            if row.high==row.low and row.pctChg>=9.5: continue
            if last_trade.get(s)==date and date<dataset_last: continue
            target_value=open_equity*exposure*w
            current=account.positions.get(s,{}).get("qty",0)*row.open
            buy_value=max(0,target_value-current)
            if "staged" in modes: buy_value*=.50
            buy_value=min(buy_value,row.amount*.03)  # max 3% of daily amount
            px=row.open*(1+SLIPPAGE); qty=int(buy_value/px/LOT)*LOT
            amount=qty*px; total=amount+fee(amount) if qty>=LOT else np.inf
            while qty>=LOT and total>account.cash:
                qty-=LOT; amount=qty*px; total=amount+fee(amount)
            if qty<LOT: continue
            account.cash-=total
            if s in account.positions:
                p=account.positions[s]; old_cost=p["cost"]*p["qty"]
                p["qty"]+=qty; p["cost"]=(old_cost+total)/p["qty"]; p["realized"]-=total; p["initial"]+=total
            else:
                account.positions[s]={"qty":qty,"cost":total/qty,"entry_date":date,"realized":-total,"initial":total}

        equity=account.cash+sum(p["qty"]*day.loc[s].close for s,p in account.positions.items() if s in day.index)
        prev_eq=account.curve[-1]["equity"] if account.curve else INITIAL
        account.recent_returns.append(equity/prev_eq-1)
        account.highwater=max(account.highwater,equity)
        account.curve.append({"date":date,"equity":equity,"cash":account.cash,"positions":len(account.positions),"exposure":exposure})
        account.prev_close.update(day.close.to_dict())

        # Friday/last weekly session: construct orders for next session.
        next_date = dates[k+1] if k+1<len(dates) else None
        rebalance = next_date is None or pd.Timestamp(next_date).isocalendar().week != pd.Timestamp(date).isocalendar().week
        if rebalance:
            score_col = "dual_score" if "dual_score" in modes else "multi_score" if "multifactor" in modes else "base_score"
            cand=day[day.eligible.fillna(False) & day[score_col].notna()].copy().reset_index()
            cand.sort_values(score_col,ascending=False,inplace=True)
            if "buffer" in modes:
                keep=[s for s in account.positions if s in set(cand.head(100).symbol)]
                rest=[s for s in cand.symbol if s not in keep]
                names=(keep+rest)[:TARGET_COUNT]
                cand=cand.set_index("symbol").loc[names].reset_index()
            else: cand=cand.head(TARGET_COUNT)
            if "industry_cap" in modes:
                selected=[]; counts={}
                for z in cand.itertuples():
                    ind=z.industry
                    if counts.get(ind,0)>=7: continue
                    selected.append(z.symbol); counts[ind]=counts.get(ind,0)+1
                    if len(selected)>=TARGET_COUNT: break
                cand=cand.set_index("symbol").loc[selected].reset_index()
            if len(cand):
                if "risk_parity" in modes:
                    inv=1/cand.vol20.clip(.008,.05); weights=inv/inv.sum(); weights=weights.clip(upper=.03); weights=weights/weights.sum()
                else: weights=pd.Series(1/len(cand),index=cand.index)
                pending=list(zip(cand.symbol.tolist(),weights.tolist()))
            else: pending=[]
        prior_state=smap.loc[date]
    return metrics(account.curve,account.trades),pd.DataFrame(account.curve),pd.DataFrame(account.trades)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    data,states=load_data()
    rows=[]
    for code,name,modes in VARIANTS:
        print(f"{code} {name}",flush=True)
        design,curve,trades=simulate(data,states,modes,START,DESIGN_END)
        design.update({"code":code,"name":name,"period":"2020-2024","modes":"+".join(sorted(modes))})
        rows.append(design)
        curve.to_parquet(OUT/f"{code}_design_curve.parquet",index=False)
        trades.to_csv(OUT/f"{code}_design_trades.csv",index=False,encoding="utf-8-sig")
        print(json.dumps({k:(float(v) if isinstance(v,(np.floating,np.integer)) else v) for k,v in design.items()},ensure_ascii=False),flush=True)
    design_table=pd.DataFrame(rows)
    eligible=design_table[(design_table.max_drawdown>=-.12)&design_table.average_positions.between(MIN_COUNT,MAX_COUNT)]
    winner=(eligible.sort_values("annualized_return",ascending=False).iloc[0] if len(eligible)
            else design_table.sort_values(["max_drawdown","annualized_return"],ascending=[False,False]).iloc[0])
    frozen_code=winner.code
    modes=dict((c,m) for c,_,m in VARIANTS)[frozen_code]
    test,test_curve,test_trades=simulate(data,states,modes,pd.Timestamp("2025-01-01"),END)
    test.update({"code":frozen_code,"name":winner["name"],"period":"2025-2026/7","modes":"+".join(sorted(modes))})
    result=pd.concat([design_table,pd.DataFrame([test])],ignore_index=True)
    result.to_csv(OUT/"direction_results.csv",index=False,encoding="utf-8-sig")
    test_curve.to_parquet(OUT/"locked_test_curve.parquet",index=False)
    test_trades.to_csv(OUT/"locked_test_trades.csv",index=False,encoding="utf-8-sig")
    (OUT/"selection.json").write_text(json.dumps({"winner":frozen_code,"design_constraint_met":len(eligible)>0,
        "holdout_used_for_selection":False},ensure_ascii=False,indent=2),encoding="utf-8")
    print(result.to_string(index=False),flush=True)


if __name__=="__main__": main()
