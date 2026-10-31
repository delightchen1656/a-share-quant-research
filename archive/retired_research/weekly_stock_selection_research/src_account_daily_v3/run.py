"""Replay fixed development scores; inventory company evidence before publishing."""
import json
import datetime
import math
import pandas as pd
from common import BASE,AUDIT,SPEC,dump,sha,fee,install_development_guard
from portfolio import Quotes,simulate
from account_validation import independent_account,aggregate
from execution import plan_buy

OLD=BASE/'audits/holdout_restricted/monday_account_backtest_v1_1'
RULES=BASE/'audits/holdout_restricted/monday_trading_rules_daily_v3'

def main():
    install_development_guard()
    assert not (AUDIT/'summary.parquet').exists(),'Preserve completed runs'
    assert json.loads((AUDIT/'minimum_checks.json').read_text(encoding='utf-8'))['passed']
    assert sha(RULES/'RULES.json')==SPEC['rules_sha256']
    assert sha(AUDIT/'scores.parquet')==sha(OLD/'scores.parquet')
    quotes=Quotes()
    scores=pd.read_parquet(AUDIT/'scores.parquet')
    plan=pd.read_parquet(AUDIT/'weekly_schedule.parquet')
    events=json.loads((AUDIT/'company_events_conditional.json').read_text(encoding='utf-8'))
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    covered={(r['symbol'],r['year']) for r in collection['sources'] if r['ok']}
    for r in collection['sources']:
        assert r['ok'] and sha(BASE/'inputs_pre2025/corporate_provider_v1'/f"{r['symbol']}_{r['year']}.parquet")==r['sha256']
    registration=AUDIT/'execution_registration.json'
    current=dict(rules_sha256=sha(RULES/'RULES.json'),scores_sha256=sha(AUDIT/'scores.parquet'),
        code=[dict(path=p.name,sha256=sha(p)) for p in sorted(__import__('pathlib').Path(__file__).parent.glob('*.py'))])
    if not registration.exists():
        dump(registration,dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),before_results=True,**current))
    else:
        registered=json.loads(registration.read_text(encoding='utf-8'))
        assert all(registered[k]==v for k,v in current.items()),'Code changed after registration; retain and re-register explicitly'
    results={m:simulate(m,scores,quotes,events,plan=plan) for m in ['long120','anchor11']}
    required=set().union(*(set(map(tuple,r['requested'])) for r in results.values()))
    missing=sorted(required-covered)
    dump(AUDIT/'held_year_inventory.json',dict(required=sorted(required),missing=missing,
        no_strategy_results_published_before_evidence=True))
    if missing:
        print('Additional development company stock-years needed:',len(missing),flush=True)
        return
    summaries=[];annuals=[]
    for method,r in results.items():
        independent_account(r,events,quotes)
        assert r['complete'],f'Development unresolved evidence: {method}, see exception file'
        daily=r['daily'];tx=r['transactions'];plans=r['plans'];trades=r['trades']
        # Independently reconstruct pre-auction cash, slots, rank selection and budgets.
        for date,g in plans.groupby('date',sort=False):
            hist=daily.loc[daily.date.lt(date)]
            cash=float(hist.cash.iloc[-1]) if len(hist) else 1e6
            held=set(hist.holdings.iloc[-1].split(';'))-{''} if len(hist) else set()
            chosen=scores.loc[scores.method.eq(method)&scores.monday.eq(date)].sort_values('rank')
            expected=[s for s in chosen.symbol if s not in held][:10-len(held)]
            assert g.symbol.tolist()==expected
            signal_nav=daily.loc[daily.date.eq(chosen.signal_date.iloc[0]),'equity']
            target=float(signal_nav.iloc[0])/10 if len(signal_nav) else 1e5
            for p in g.itertuples():
                budget=min(target,cash);cash-=budget
                assert abs(p.budget-budget)<1e-6
                i=quotes.days.get_loc(pd.Timestamp(date));b=quotes.bar(p.symbol,i);prev=quotes.bar(p.symbol,i-1)
                order,reason=plan_buy(b,budget,prev['volume'] if prev['active'] else 0,date)
                assert p.qty==(order['qty'] if order else 0)
                if order:assert p.limit_price==order['limit_price']
                else:assert p.reason==reason
        for t in tx.itertuples():
            assert math.isclose(t.notional,t.qty*t.price,abs_tol=1e-7)
            assert math.isclose(t.fee,fee(t.notional,t.side,t.date),abs_tol=1e-7)
            i=quotes.days.get_loc(pd.Timestamp(t.date));b=quotes.bar(t.symbol,i)
            if t.side=='buy':
                assert pd.Timestamp(t.date).weekday()==0 and t.price==b['open'] and t.qty%100==0
            elif t.exit_kind=='daily_reopen_floor':
                from execution import price_band
                assert t.price==price_band(b,t.date)['lower'] and b['high']>t.price+.004
            else:assert t.price==b['close']
        annual,summary=aggregate(daily)
        closed=trades.loc[trades.status.eq('closed')]
        late=pd.to_datetime(trades.exit_date)>(pd.to_datetime(trades.entry_date)+pd.Timedelta(days=1))
        sells=tx.loc[tx.side.eq('sell')]
        emergency=sells.loc[sells.exit_kind.eq('daily_reopen_floor')]
        summary.update(method=method,conditional_account_complete=r['complete'],unresolved_cases=len(r['bad']),
            fees=float(tx.fee.sum()),buys=int(tx.side.eq('buy').sum()),sell_fills=len(sells),
            cancelled_buys=int(r['logs'].kind.eq('buy_cancelled').sum()),
            delayed_sell_attempts=int(r['logs'].kind.eq('sell_delayed').sum()),delayed_trades=int(late.sum()),
            emergency_fills=len(emergency),ambiguous_order_fills=int(emergency.ambiguous_order.sum()),
            floor_below_daily_low_fills=int(emergency.outside_daily_range.sum()),
            open_trades=int(trades.status.eq('open').sum()),closed_trade_win_rate=float(closed.pnl.gt(0).mean()),
            average_close_exposure=float((daily.inventory/daily.equity).mean()),
            longest_closed_calendar_hold=int((pd.to_datetime(closed.exit_date)-pd.to_datetime(closed.entry_date)).dt.days.max()),
            actual_execution_certified=False)
        summaries.append(summary);annual['method']=method;annuals.append(annual)
        dump(AUDIT/f'{method}_account_exceptions.json',r['bad'])
    for key,name in [('daily','daily_nav'),('trades','trades'),('transactions','transactions'),('plans','preopen_plans'),('logs','execution_log')]:
        pd.concat([r[key] for r in results.values()],ignore_index=True).to_parquet(AUDIT/f'{name}.parquet',index=False)
    pd.DataFrame(summaries).to_parquet(AUDIT/'summary.parquet',index=False)
    pd.concat(annuals,ignore_index=True).to_parquet(AUDIT/'annual.parquet',index=False)
    dump(AUDIT/'account_validation.json',dict(passed=True,independent_account_replay=True,
        full_preopen_budget_rank_quantity_and_slot_replay=True,evidence_inventory_covered=True,
        no_model_changes=True,no_posterior_read=True,daily_exit_is_explicit_hypothesis=True))
    print(pd.DataFrame(summaries).to_string(index=False),flush=True)
    print(pd.concat(annuals).to_string(index=False),flush=True)

if __name__=='__main__':main()
