import json
import datetime
import math
import numpy as np
import pandas as pd
from common import BASE,AUDIT,SPEC,FACTORS,sha,dump
from portfolio import Quotes,simulate


def aggregate(daily):
    rows=[]
    prior=1e6
    for year,g in daily.groupby(pd.to_datetime(daily.date).dt.year):
        curve=np.r_[prior,g.equity.to_numpy()]
        rows.append(dict(year=int(year),annual_return=float(g.equity.iloc[-1]/prior-1),
                         maximum_drawdown=float((1-curve/np.maximum.accumulate(curve)).max()),
                         end_equity=float(g.equity.iloc[-1])))
        prior=g.equity.iloc[-1]
    curve=np.r_[1e6,daily.equity.to_numpy()]
    elapsed=(pd.Timestamp(daily.date.iloc[-1])-pd.Timestamp('2020-12-31')).days
    return pd.DataFrame(rows),dict(cagr=float((daily.equity.iloc[-1]/1e6)**(365.25/elapsed)-1),
             cumulative_return=float(daily.equity.iloc[-1]/1e6-1),maximum_drawdown=float((1-curve/np.maximum.accumulate(curve)).max()),
             end_equity=float(daily.equity.iloc[-1]))


def market_reference(quotes):
    schedule=pd.read_parquet(AUDIT/'weekly_schedule.parquet')
    schedule=schedule.loc[schedule.year.isin([2021,2022,2023])]
    buys=set(schedule.monday)
    sells=set(schedule.tuesday)
    index=pd.read_parquet(BASE/'inputs_pre2025/sse_dev_v1.parquet').set_index('date')
    cash=1e6
    qty=0.
    rows=[]
    for date in quotes.days[quotes.days.year>=2021]:
        key=str(date.date())
        row=index.loc[date]
        if key in buys:
            qty=cash/row.open
            cash=0.
        if key in sells:
            cash=qty*row.close
            qty=0.
        equity=cash+qty*row.close
        rows.append(dict(method='sse_timing_gross',date=key,cash=cash,inventory=qty*row.close,cash_receivable=0.,
                         equity=equity,positions=int(qty>0),unknown=False,holdings='index' if qty>0 else ''))
    return pd.DataFrame(rows)


def independent_account(result,events,quotes):
    tx=result['transactions']
    trades=result['trades']
    daily=result['daily']
    transactions={d:g for d,g in tx.groupby('date')}
    records={}
    exdates={}
    for e in events:
        if e.get('supported'):
            records.setdefault(e['register_date'],[]).append(e)
            exdates.setdefault(e['ex_date'],[]).append(e)
    listed={}
    pending=[]
    claims=[]
    marks={}
    cash=1e6
    for row in daily.itertuples():
        day=row.date
        i=int(quotes.days.get_loc(pd.Timestamp(day)))
        for e in exdates.get(day,[]):
            for c in claims:
                if c['event_id']==e['event_id'] and not c['booked']:
                    c['booked']=True
                    if c['extra']:
                        pending.append(dict(key=c['key'],qty=c['extra'],listing=e['listing_date']))
            s=e['symbol']
            if s in marks and not quotes.bar(s,i)['active']:
                marks[s]=(marks[s]-e['cash_ps'])/(1+e['bonus_ps']+e['transfer_ps'])
        for p in pending:
            if p['listing']<=day and not p.get('credited',False):
                listed[p['key']]=listed.get(p['key'],0)+p['qty']
                p['credited']=True
        for c in claims:
            if c['booked'] and not c['paid'] and c['pay']<=day:
                cash+=c['cash']
                c['paid']=True
        if day in transactions:
            for t in transactions[day].itertuples():
                key=(t.symbol,t.trade_id)
                if t.side=='buy':
                    listed[key]=listed.get(key,0)+t.qty
                    cash-=t.notional+t.fee
                else:
                    listed[key]-=t.qty
                    assert listed[key]>=0
                    cash+=t.notional-t.fee
        for e in records.get(day,[]):
            for key,qty in listed.items():
                if key[0]==e['symbol'] and qty>0:
                    extra=qty*(e['bonus_ps']+e['transfer_ps'])
                    if abs(extra-round(extra))>1e-7:
                        continue
                    claims.append(dict(key=key,event_id=e['event_id'],cash=qty*e['cash_ps'],extra=int(round(extra)),
                                       pay=e['pay_date'],booked=False,paid=False))
        symbols={k[0] for k,q in listed.items() if q>0}|{p['key'][0] for p in pending if not p.get('credited',False)}
        for s in symbols:
            bar=quotes.bar(s,i)
            if bar['active']:
                marks[s]=bar['close']
        inventory=sum(q*marks[k[0]] for k,q in listed.items() if q>0)
        inventory+=sum(p['qty']*marks[p['key'][0]] for p in pending if not p.get('credited',False))
        receivable=sum(c['cash'] for c in claims if c['booked'] and not c['paid'])
        np.testing.assert_allclose([cash,inventory,receivable,cash+inventory+receivable],
                                   [row.cash,row.inventory,row.cash_receivable,row.equity],atol=1e-5,rtol=1e-11)
    assert math.isclose(trades.pnl.sum(),daily.equity.iloc[-1]-1e6,abs_tol=1e-5)


def main():
    assert json.loads((AUDIT/'pipeline_validation.json').read_text(encoding='utf-8'))['passed']
    assert sha(AUDIT/'spec.json')==json.loads((AUDIT/'registration.json').read_text(encoding='utf-8'))['spec_sha256']
    out=AUDIT/'comparison'
    out.mkdir(exist_ok=True)
    assert not (out/'summary.parquet').exists(),'Retain completed comparison, no hidden retries'
    codefiles=[BASE/'src'/f for f in ['common.py','execution.py','portfolio.py','build_panel.py','fit_methods.py','run_comparison.py','company_data.py']]
    dump(AUDIT/'execution_registration.json',dict(registered_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         before_compared_account_performance=True,code=[dict(path=p.name,sha256=sha(p)) for p in codefiles],
         score_sha256=sha(AUDIT/'selection_scores_top30.parquet'),events_sha256=sha(AUDIT/'company_events_conditional.json')))
    events=json.loads((AUDIT/'company_events_conditional.json').read_text(encoding='utf-8'))
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    covered={(r['symbol'],r['year']) for r in collection['sources'] if r['ok']}
    scores=pd.read_parquet(AUDIT/'selection_scores_top30.parquet')
    quotes=Quotes()
    summaries=[]
    yearly=[]
    daily_all=[]
    trades_all=[]
    tx_all=[]
    logs_all=[]
    missing=set()
    for method in SPEC['methods']:
        name=method['id']
        result=simulate(name,scores,quotes,events)
        needed={tuple(x) for x in result['requested']}
        missing.update(needed-covered)
        independent_account(result,events,quotes)
        d=result['daily']
        annual,summary=aggregate(d)
        tx=result['transactions']
        closed=result['trades'].loc[result['trades'].status.eq('closed')]
        buy_cancel=result['logs'].loc[result['logs'].kind.eq('buy_cancelled')]
        delayed=result['logs'].loc[result['logs'].kind.eq('sell_delayed')]
        summary.update(method=name,conditional_account_complete=bool(result['complete'] and not (needed-covered)),
             unresolved_accounting_cases=len(result['bad']),buys=int(tx.side.eq('buy').sum()),sell_fills=int(tx.side.eq('sell').sum()),
             closed_trades=len(closed),open_trades=int(result['trades'].status.eq('open').sum()),
             closed_win_rate=float(closed.pnl.gt(0).mean()) if len(closed) else None,
             fees=float(tx.fee.sum()),average_exposure=float((d.inventory/d.equity).mean()),
             cancelled_buys=len(buy_cancel),delayed_sell_attempts=len(delayed),
             gross_dividends=float(result['trades'].gross_dividend.sum()),
             fee_addback_fixed_fills_cumulative_return=float((d.equity.iloc[-1]+tx.fee.sum())/1e6-1),
             positive_validation_years=int(annual.annual_return.gt(0).sum()))
        summaries.append(summary)
        annual['method']=name
        yearly.append(annual)
        daily_all.append(d)
        trades_all.append(result['trades'])
        tx_all.append(tx)
        logs_all.append(result['logs'])
        dump(out/f'{name}_account_exceptions.json',result['bad'])
        print('conditional accounting checked',name,'unresolved',len(result['bad']),flush=True)
    if missing:
        old=json.loads((AUDIT/'company_query_requests.json').read_text(encoding='utf-8'))
        old_set={tuple(x) for x in old['requests']}
        old['requests']=[list(x) for x in sorted(old_set|missing)]
        dump(AUDIT/'company_query_requests.json',old)
        dump(AUDIT/'additional_evidence_needed.json',dict(requests=[list(x) for x in sorted(missing)],
             note='Additional held stockyear evidence caused by correctly accounted shares/blocked positions, not parameter change'))
        raise RuntimeError(f'{len(missing)}additional stockyear evidence queries required; refresh source cache under unchanged rules')
    market=market_reference(quotes)
    annual,summary=aggregate(market)
    summary.update(method='sse_timing_gross',conditional_account_complete=True,unresolved_accounting_cases=0,
                   fees=0.,average_exposure=float((market.inventory/market.equity).mean()))
    summaries.append(summary)
    annual['method']='sse_timing_gross'
    yearly.append(annual)
    daily_all.append(market)
    summary=pd.DataFrame(summaries).sort_values('cagr',ascending=False)
    annual=pd.concat(yearly,ignore_index=True)
    lookup=summary.set_index('method')
    decisions=[]
    for row in summary.itertuples():
        if row.method in ['random10','liquidity10','sse_timing_gross']:
            continue
        y=annual.loc[annual.method.eq(row.method)].set_index('year').annual_return
        r=annual.loc[annual.method.eq('random10')].set_index('year').annual_return
        l=annual.loc[annual.method.eq('liquidity10')].set_index('year').annual_return
        over_random=int(y.gt(r).sum())
        over_liquidity=int(y.gt(l).sum())
        passes=bool(row.conditional_account_complete and lookup.loc['random10','conditional_account_complete'] and lookup.loc['liquidity10','conditional_account_complete']
                    and row.cagr>max(lookup.loc['random10','cagr'],lookup.loc['liquidity10','cagr'],lookup.loc['sse_timing_gross','cagr'])
                    and min(over_random,over_liquidity)>=2)
        decisions.append(dict(method=row.method,annual_excess_random_positive_years=over_random,
                              annual_excess_liquidity_positive_years=over_liquidity,candidate_gate=passes,
                              interpretation='Development lead only, not final independent validation; incomplete account fails'))
    summary.to_parquet(out/'summary.parquet',index=False)
    annual.to_parquet(out/'annual.parquet',index=False)
    pd.concat(daily_all,ignore_index=True).to_parquet(out/'daily_nav.parquet',index=False)
    pd.concat(trades_all,ignore_index=True).to_parquet(out/'trades.parquet',index=False)
    pd.concat(tx_all,ignore_index=True).to_parquet(out/'transactions.parquet',index=False)
    pd.concat(logs_all,ignore_index=True).to_parquet(out/'execution_log.parquet',index=False)
    dump(out/'candidate_decisions.json',decisions)
    dump(out/'validation.json',dict(all10methods_compared=True,source_held_stockyears_covered=True,
         cash_units_and_claims_reconciled=True,weekday_fixed=True,selection_methods_frozen=True,
         original_economic_targets_not_borrowed=True,shareholder_dividend_tax_not_deducted=True,
         full_history_universe_not_established=True,results_are_conditional=True))
    print(summary[['method','cagr','maximum_drawdown','conditional_account_complete','unresolved_accounting_cases','average_exposure']].to_string(index=False),flush=True)
    print(annual.pivot(index='year',columns='method',values='annual_return').to_string(),flush=True)
    print(json.dumps(decisions,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
