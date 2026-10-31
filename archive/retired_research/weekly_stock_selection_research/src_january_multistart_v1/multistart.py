"""Shared evaluation mechanics, no start-date or performance selection."""
import math
import numpy as np
import pandas as pd
from portfolio import simulate
from account_validation import independent_account
from common import SPEC,fee
from execution import plan_buy,price_band

def validate_account(result,events,quotes,scores):
    independent_account(result,events,quotes)
    daily=result['daily'];initial=result['initial_cash']
    for date,g in result['plans'].groupby('date',sort=False):
        hist=daily.loc[daily.date.lt(date)]
        cash=float(hist.cash.iloc[-1]) if len(hist) else initial
        held=set(hist.holdings.iloc[-1].split(';'))-{''} if len(hist) else set()
        selected=scores.loc[scores.monday.eq(date)].sort_values('rank')
        expected=[s for s in selected.symbol if s not in held][:10-len(held)]
        assert g.symbol.tolist()==expected
        nav=daily.loc[daily.date.eq(selected.signal_date.iloc[0]),'equity']
        target=float(nav.iloc[0])/10 if len(nav) else initial/10
        for row in g.itertuples():
            budget=min(target,cash);cash-=budget
            assert abs(row.budget-budget)<1e-6
            i=quotes.days.get_loc(pd.Timestamp(date));bar=quotes.bar(row.symbol,i);prev=quotes.bar(row.symbol,i-1)
            order,reason=plan_buy(bar,budget,prev['volume'] if prev['active'] else 0,date)
            assert row.qty==(order['qty'] if order else 0)
            if order:assert row.limit_price==order['limit_price']
            else:assert row.reason==reason
    for t in result['transactions'].itertuples():
        assert math.isclose(t.notional,t.qty*t.price,abs_tol=1e-7)
        assert math.isclose(t.fee,fee(t.notional,t.side,t.date),abs_tol=1e-7)
        i=quotes.days.get_loc(pd.Timestamp(t.date));bar=quotes.bar(t.symbol,i)
        if t.side=='buy':
            assert pd.Timestamp(t.date).weekday()==0 and t.qty%100==0 and t.price==bar['open']
        elif t.exit_kind=='daily_reopen_floor':
            assert t.price==price_band(bar,t.date)['lower'] and bar['high']>t.price+.004
        else:assert t.price==bar['close']

def evaluate(scores,quotes,events,plan,years,cutoff):
    results={};summaries=[];required=set()
    for year in years:
        starts=quotes.days[(quotes.days.year==year)&(quotes.days.month==1)&(quotes.days.weekday==0)]
        end=min(pd.Timestamp(f'{year}-12-31'),pd.Timestamp(cutoff))
        for n,start in enumerate(starts,1):
            if start>end:continue
            account=f'{year}_jan_{n}_{start.date()}'
            r=simulate('long120',scores,quotes,events,plan=plan,start=start,end=end,initial_cash=100000.)
            validate_account(r,events,quotes,scores)
            required.update(map(tuple,r['requested']))
            daily=r['daily'];tx=r['transactions'];trades=r['trades'];logs=r['logs']
            sell=tx.loc[tx.side.eq('sell')];buy=tx.loc[tx.side.eq('buy')]
            emergency=sell.loc[sell.exit_kind.eq('daily_reopen_floor')]
            curve=np.r_[100000.,daily.equity.to_numpy()]
            summary=dict(account_id=account,year=year,start_number=n,start_date=str(start.date()),
                end_date=daily.date.iloc[-1],initial_cash=100000.,account_return=float(curve[-1]/100000.-1),
                maximum_drawdown=float((1-curve/np.maximum.accumulate(curve)).max()),end_equity=float(curve[-1]),
                first_actual_buy=buy.date.min() if len(buy) else None,fees=float(tx.fee.sum()),buys=len(buy),sell_fills=len(sell),
                cancelled_buys=int(logs.kind.eq('buy_cancelled').sum()),emergency_fills=len(emergency),
                ambiguous_order_fills=int(emergency.ambiguous_order.sum()),floor_below_daily_low_fills=int(emergency.outside_daily_range.sum()),
                end_cash=float(daily.cash.iloc[-1]),end_share_value=float(daily.inventory.iloc[-1]),
                end_cash_receivable=float(daily.cash_receivable.iloc[-1]),open_trades=int(trades.status.eq('open').sum()),
                conditional_account_complete=r['complete'],exception_count=len(r['bad']),actual_execution_certified=False,
                year_completed=year<pd.Timestamp(cutoff).year,average_close_exposure=float((daily.inventory/daily.equity).mean()))
            results[account]=r;summaries.append(summary)
    return results,pd.DataFrame(summaries),sorted(required)
