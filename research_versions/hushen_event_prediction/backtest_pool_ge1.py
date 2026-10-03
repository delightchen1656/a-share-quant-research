"""Realistic daily backtest for the point-in-time >=1 prior rally universe."""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
MARKET_DIR = PROJECT / "data_pipeline" / "data" / "derived" / "backtest_market_by_year"
SCORE_FILE = HERE / "outputs" / "scores_pool_ge1_2024_2026.parquet"
OUT = HERE / "outputs" / "backtest_pool_ge1"
INITIAL = 1_000_000.0
COMMISSION, TRANSFER, MIN_FEE = .0003, .00001, 5.0
SLIP, PARTICIPATION = .002, .05


@dataclass
class Position:
    qty: int
    entry: float
    entry_date: pd.Timestamp
    peak: float
    half: bool = False


def buy_fee(value): return max(MIN_FEE, value * COMMISSION) + value * TRANSFER
def sell_fee(value, date):
    stamp = .0005 if date >= pd.Timestamp("2023-08-28") else .001
    return max(MIN_FEE, value * COMMISSION) + value * (TRANSFER + stamp)


def limit_prices(preclose, date):
    # New listings are excluded upstream; active non-ST main-board stocks use 10%.
    return round(preclose * 1.10 + 1e-8, 2), round(preclose * .90 + 1e-8, 2)


def metrics(equity: pd.DataFrame, trades: list[dict]) -> dict:
    nav = equity.equity / INITIAL
    ret = nav.pct_change().fillna(0)
    years = max((equity.date.iloc[-1] - equity.date.iloc[0]).days / 365.25, 1/252)
    cagr = float(nav.iloc[-1] ** (1 / years) - 1)
    dd = nav / nav.cummax() - 1
    sharpe = float(np.sqrt(252) * ret.mean() / ret.std()) if ret.std() else 0.0
    return {"final_asset": float(equity.equity.iloc[-1]), "total_return": float(nav.iloc[-1]-1),
            "annual_return": cagr, "max_drawdown": float(dd.min()), "sharpe": sharpe,
            "average_exposure": float(equity.exposure.mean()), "trades": len(trades)}


def run(market, scores, start, end, params):
    dates = sorted(d for d in market.date.unique() if pd.Timestamp(start) <= d <= pd.Timestamp(end))
    by_day = {d: x.set_index("symbol") for d, x in market[market.date.isin(dates)].groupby("date")}
    ranked = {d: x.sort_values("probability", ascending=False).head(params["top_daily"])
              for d, x in scores.groupby("trade_date")}
    cash, pos, records, trades = INITIAL, {}, [], []
    for date in dates:
        day = by_day[date]
        # Morning buys use only cash available before today's sells.
        candidates = ranked.get(date)
        if candidates is not None:
            for row in candidates.itertuples():
                if row.symbol in pos or len(pos) >= params["max_positions"] or row.symbol not in day.index:
                    continue
                q = day.loc[row.symbol]
                if str(q.tradestatus) != "1" or str(q.isST) == "1" or q.volume <= 0:
                    continue
                upper, _ = limit_prices(float(q.preclose), date)
                if q.open >= upper - .005 and q.low >= upper - .005:
                    continue
                px = float(q.open) * (1 + SLIP)
                equity_open = cash + sum(p.qty * float(day.at[s, "open"]) for s, p in pos.items() if s in day.index)
                # Optional point-in-time position sizing.  This lets research
                # routes use inverse-volatility/risk-budget weights without
                # changing the legacy fixed-weight backtests.
                row_weight = getattr(row, "target_weight", params["weight"])
                if not np.isfinite(row_weight) or row_weight <= 0:
                    continue
                budget = min(equity_open * float(row_weight), cash / 1.001)
                qty = int(min(budget / px, float(q.volume) * PARTICIPATION) // 100 * 100)
                if qty < 100: continue
                value = qty * px; fee = buy_fee(value)
                if value + fee > cash: continue
                cash -= value + fee
                pos[row.symbol] = Position(qty, px, date, px)
                trades.append({"date": date, "symbol": row.symbol, "side": "BUY", "qty": qty, "price": px})

        # Intraday exits; same-bar stop is assumed before profit (conservative).
        for symbol in list(pos):
            if symbol not in day.index: continue
            q, p = day.loc[symbol], pos[symbol]
            if str(q.tradestatus) != "1" or q.volume <= 0: continue
            p.peak = max(p.peak, float(q.high))
            age = int(np.busday_count(p.entry_date.date(), date.date()))
            if date <= p.entry_date: continue  # A-share T+1
            _, lower = limit_prices(float(q.preclose), date)
            if q.open <= lower + .005 and q.high <= lower + .005: continue
            stop_px = p.entry * (1 - params["stop"])
            exit_qty, reason, trigger = 0, None, None
            if q.low <= stop_px:
                exit_qty, reason, trigger = p.qty, "STOP", min(float(q.open), stop_px)
            elif p.half and q.low <= p.peak * (1 - params["trail"]):
                exit_qty, reason, trigger = p.qty, "TRAIL", min(float(q.open), p.peak*(1-params["trail"]))
            elif not p.half and q.high >= p.entry * (1 + params["tp1"]):
                exit_qty, reason, trigger = max(100, (p.qty // 200) * 100), "TP1", p.entry*(1+params["tp1"])
            elif q.high >= p.entry * (1 + params["tp2"]):
                exit_qty, reason, trigger = p.qty, "TP2", p.entry*(1+params["tp2"])
            elif age >= params["max_hold"]:
                exit_qty, reason, trigger = p.qty, "EXPIRY", float(q.open)
            if exit_qty:
                exit_qty = min(exit_qty, int(float(q.volume)*PARTICIPATION)//100*100, p.qty)
                if exit_qty <= 0: continue
                px = trigger * (1-SLIP); value = exit_qty*px
                cash += value-sell_fee(value,date); p.qty -= exit_qty
                trades.append({"date": date, "symbol": symbol, "side": "SELL", "reason": reason,
                               "qty": exit_qty, "price": px})
                if p.qty <= 0: del pos[symbol]
                elif reason == "TP1": p.half = True
        mv = sum(p.qty * float(day.at[s, "close"]) for s,p in pos.items() if s in day.index)
        records.append({"date": date, "equity": cash+mv, "exposure": mv/max(cash+mv,1)})
    eq = pd.DataFrame(records)
    return metrics(eq,trades),eq,pd.DataFrame(trades)


def load_data():
    market = pd.concat([pd.read_parquet(MARKET_DIR/f"{y}.parquet") for y in (2024,2025,2026)], ignore_index=True)
    market["date"] = pd.to_datetime(market.date)
    market = market[(market.date <= "2026-07-31") & market.symbol.notna()]
    scores = pd.read_parquet(SCORE_FILE)
    scores["date"] = pd.to_datetime(scores.date)
    # T close signal enters on the next market trading day.
    calendar = np.array(sorted(market.date.unique()), dtype="datetime64[ns]")
    score_dates = scores.date.to_numpy(dtype="datetime64[ns]")
    idx = np.searchsorted(calendar, score_dates, side="right")
    good = idx < len(calendar)
    scores = scores.loc[good].copy(); scores["trade_date"] = calendar[idx[good]]
    return market, scores


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    market,scores=load_data()
    trials=[]
    for stop,tp1,tp2,hold,top in itertools.product((.06,.08,.10),(.18,.22),(.35,.50),(15,25,35),(1,2,3)):
        p={"stop":stop,"tp1":tp1,"tp2":tp2,"max_hold":hold,"top_daily":top,
           "trail":.10,"weight":.08,"max_positions":10}
        m,_,_=run(market,scores,"2024-01-01","2024-12-31",p)
        m.update(p); m["score"] = m["annual_return"] + .15*m["sharpe"]
        trials.append(m)
    grid=pd.DataFrame(trials)
    feasible=grid[(grid.max_drawdown>=-.35)&grid.average_exposure.between(.30,.80)]
    # When the hard constraints have no feasible solution, retain only a
    # diagnostic run and never describe it as a locked/deployable strategy.
    best=(feasible if len(feasible) else grid).sort_values("score",ascending=False).iloc[0].to_dict()
    keys=("stop","tp1","tp2","max_hold","top_daily","trail","weight","max_positions")
    p={k:(int(best[k]) if k in ("max_hold","top_daily","max_positions") else float(best[k])) for k in keys}
    periods=(("validation_2024","2024-01-01","2024-12-31"),("holdout_2025_2026","2025-01-01","2026-07-31"),
             ("continuous_2024_2026","2024-01-01","2026-07-31"))
    results=[]
    for name,start,end in periods:
        m,eq,tr=run(market,scores,start,end,p); m.update({"period":name,"start":start,"end":end}); results.append(m)
        eq.to_csv(OUT/f"equity_{name}.csv",index=False,encoding="utf-8-sig")
        tr.to_csv(OUT/f"trades_{name}.csv",index=False,encoding="utf-8-sig")
    grid.to_csv(OUT/"parameter_search_2024.csv",index=False,encoding="utf-8-sig")
    pd.DataFrame(results).to_csv(OUT/"backtest_summary.csv",index=False,encoding="utf-8-sig")
    status = {"status": "feasible" if len(feasible) else "rejected_no_feasible_solution",
              "feasible_parameter_sets": int(len(feasible)), "diagnostic_parameters": p}
    (OUT/"selection_status.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SELECTION",json.dumps(status,ensure_ascii=False)); print(pd.DataFrame(results).to_string(index=False))


if __name__=="__main__": main()
