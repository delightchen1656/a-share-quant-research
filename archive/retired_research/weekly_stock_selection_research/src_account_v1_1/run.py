import json
import datetime
import math
import numpy as np
import pandas as pd
from common import BASE,AUDIT,SPEC,sha,dump,fee,install_development_guard
from portfolio import Quotes,simulate
from account_validation import aggregate,independent_account


def market_reference(quotes,plan):
    index=pd.read_parquet(BASE/'inputs_pre2025/sse_dev_v1.parquet').set_index('date')
    buys=set(plan.loc[plan.year.isin([2021,2022,2023]),'monday'])
    sells=set(plan.loc[plan.year.isin([2021,2022,2023]),'tuesday'])
    cash=1e6
    qty=0.
    rows=[]
    for date in quotes.days[quotes.days.year>=2021]:
        key=str(date.date())
        bar=index.loc[date]
        if key in buys:qty=cash/bar.open;cash=0.
        if key in sells:cash=qty*bar.close;qty=0.
        rows.append(dict(method='sse_timing_gross',date=key,cash=cash,inventory=qty*bar.close,cash_receivable=0.,equity=cash+qty*bar.close,
                         positions=int(qty>0),unknown=False,holdings='index' if qty else ''))
    return pd.DataFrame(rows)


def main():
    install_development_guard()
    assert not (AUDIT/'summary.parquet').exists(),'Do not overwrite a completed rule backtest'
    assert json.loads((AUDIT/'minimum_checks.json').read_text(encoding='utf-8'))['passed']
    rules_dir=BASE/'audits/holdout_restricted/monday_trading_rules_v1'
    rules=json.loads((rules_dir/'RULES.json').read_text(encoding='utf-8'))
    assert sha(rules_dir/'RULES.json')==SPEC['rules_sha256']
    events=json.loads((AUDIT/'company_events_conditional.json').read_text(encoding='utf-8'))
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    covered={(r['symbol'],r['year']) for r in collection['sources'] if r['ok']}
    for r in collection['sources']:
        assert r['ok'] and sha(BASE/'inputs_pre2025/corporate_provider_v1'/f"{r['symbol']}_{r['year']}.parquet")==r['sha256']
    code=list((BASE/'src_account_v1').glob('*.py'))
    dump(AUDIT/'execution_registration.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        before_account_performance_published=True,spec_sha256=sha(AUDIT/'spec.json'),rules_sha256=sha(rules_dir/'RULES.json'),
        score_sha256=sha(AUDIT/'scores.parquet'),event_sha256=sha(AUDIT/'company_events_conditional.json'),
        code=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted(code)]))
    scores=pd.read_parquet(AUDIT/'scores.parquet')
    quotes=Quotes()
    plan=pd.read_parquet(AUDIT/'weekly_schedule.parquet')
    summaries=[]
    annual_all=[]
    daily_all=[]
    trades_all=[]
    tx_all=[]
    plans_all=[]
    logs_all=[]
    for method in ['long120','anchor11']:
        result=simulate(method,scores,quotes,events)
        assert set(tuple(x) for x in result['requested'])<=covered,'Need additional held-year evidence before publishing'
        independent_account(result,events,quotes)
        daily=result['daily']
        annual,summary=aggregate(daily)
        tx=result['transactions']
        trades=result['trades']
        for row in tx.itertuples():
            date=pd.Timestamp(row.date)
            bar=quotes.bar(row.symbol,quotes.days.get_loc(date))
            assert math.isclose(row.notional,row.qty*row.price,abs_tol=1e-7)
            assert math.isclose(row.fee,fee(row.notional,row.side,date),abs_tol=1e-7)
            if row.side=='buy':
                assert date.weekday()==0 and row.qty%100==0 and row.price==bar['open']
                p=result['plans'].loc[result['plans'].date.eq(row.date)&result['plans'].symbol.eq(row.symbol)].iloc[0]
                assert row.qty==p.qty and row.price<=p.limit_price+.004
            else:
                assert date.weekday()==1 and row.price==bar['close']
        closed=trades.loc[trades.status.eq('closed')]
        planned_exit=pd.to_datetime(trades.entry_date)+pd.Timedelta(days=1)
        late=pd.to_datetime(trades.exit_date)>planned_exit
        summary.update(method=method,conditional_account_complete=result['complete'],unresolved_cases=len(result['bad']),
            actual_auction_execution_certified=False,fees=float(tx.fee.sum()),gross_dividends=float(trades.gross_dividend.sum()),
            buys=int(tx.side.eq('buy').sum()),sell_fills=int(tx.side.eq('sell').sum()),
            cancelled_buys=int(result['logs'].kind.eq('buy_cancelled').sum()),
            delayed_sell_attempts=int(result['logs'].kind.eq('sell_delayed').sum()),delayed_trades=int(late.sum()),
            delayed_trades_pnl=float(trades.loc[late,'pnl'].sum()),
            closed_trade_win_rate=float(closed.pnl.gt(0).mean()),closed_trades=len(closed),open_trades=int(trades.status.eq('open').sum()),
            average_close_exposure=float((daily.inventory/daily.equity).mean()),
            longest_closed_calendar_hold=int((pd.to_datetime(closed.exit_date)-pd.to_datetime(closed.entry_date)).dt.days.max()))
        summaries.append(summary)
        annual['method']=method
        annual_all.append(annual)
        daily_all.append(daily)
        trades_all.append(trades)
        tx_all.append(tx)
        plans_all.append(result['plans'])
        logs_all.append(result['logs'])
        dump(AUDIT/f'{method}_account_exceptions.json',result['bad'])
        print('Account cash/share replay verified',method,'unresolved',len(result['bad']),flush=True)
    market=market_reference(quotes,plan)
    annual,summary=aggregate(market)
    summary.update(method='sse_timing_gross',conditional_account_complete=True,unresolved_cases=0,actual_auction_execution_certified=False,fees=0.)
    summaries.append(summary)
    annual['method']='sse_timing_gross'
    annual_all.append(annual)
    daily_all.append(market)
    summary=pd.DataFrame(summaries)
    annual=pd.concat(annual_all,ignore_index=True)
    summary.to_parquet(AUDIT/'summary.parquet',index=False)
    annual.to_parquet(AUDIT/'annual.parquet',index=False)
    pd.concat(daily_all,ignore_index=True).to_parquet(AUDIT/'daily_nav.parquet',index=False)
    pd.concat(trades_all,ignore_index=True).to_parquet(AUDIT/'trades.parquet',index=False)
    pd.concat(tx_all,ignore_index=True).to_parquet(AUDIT/'transactions.parquet',index=False)
    pd.concat(plans_all,ignore_index=True).to_parquet(AUDIT/'preopen_plans.parquet',index=False)
    pd.concat(logs_all,ignore_index=True).to_parquet(AUDIT/'execution_log.parquet',index=False)
    dump(AUDIT/'account_validation.json',dict(independent_full_cash_shares_pending_listings_receivables_replay=True,
        preopen_quantity_and_limit_verified_all_fills=True,original_top10_no_replacement=True,
        actual_auction_fills_not_certified=True,quote_proxy_results_conditional=True,personal_dividend_tax_not_deducted=True,
        no_posterior_files_read=True,no_model_retraining_or_rule_tuning=True))
    print(summary[['method','cumulative_return','cagr','maximum_drawdown','conditional_account_complete','unresolved_cases']].to_string(index=False),flush=True)
    print(annual.to_string(index=False),flush=True)


if __name__=='__main__':
    main()
