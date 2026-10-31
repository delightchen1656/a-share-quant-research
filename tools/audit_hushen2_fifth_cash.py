"""Diagnostic trace of remaining cash rejections; trade/curve equality required."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
import test_hushen2_fifth_minus100 as trial
from replay_hushen2_local import ROOT,APP,STRATEGY,GAME,CASES,sha

PRIOR=ROOT/'archive/reports/holdout_restricted/hushen2_fifth_minus100/attempt_20261026_031615'
G={}

def initialize(end):
    trial.initialize(end,str(PRIOR));core=trial.G['engines']['fifth_minus100'];source=core.trial_source
    anchor='fixed_order_attempts.append(attempt)';assert source.count(anchor)==1
    source=source.replace(anchor,anchor+'''
            requested_gross = p.quantity * buy_price
            requested_fee = commission(requested_gross, comm_rate, comm_min)
            attempt.update(cash_before=float(cash),deferred_cash=float(deferred_cash),held_count=len(holdings),pending_count=len(pending),
                required_gross=float(requested_gross),required_fee=float(requested_fee),required_cost=float(requested_gross+requested_fee),
                modeled_buy_price=float(buy_price),trigger_price=float(p.target),signal_budget=float(p.budget),
                current_equity=float(mark_equity(cash,deferred_cash,holdings,by_symbol,date,sum(x[1] for x in receivables))))
''')
    exec(compile(source,'<cash_trace_diagnostics_only>','exec'),core.__dict__)
    old=PRIOR/'fifth_minus100'
    G.update(metrics=pd.read_parquet(old/'START_METRICS.parquet'),trades=pd.read_parquet(old/'TRADES.parquet'),
        curves=pd.read_parquet(old/'EQUITY_CURVES.parquet'),attempts=pd.read_parquet(old/'ORDER_ATTEMPTS.parquet'))

def run(job):
    i,start=job;v,m,c,t,a,o,h,skips=trial.run(('fifth_minus100',i,start))
    oldm=G['metrics'].loc[G['metrics'].start_ordinal.eq(i)].iloc[0]
    for k in ['ending_equity','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0','created','filled','failed','cash_rejected']:
        assert abs(m[k]-oldm[k])<1e-8,k
    oldc=G['curves'].loc[G['curves'].start_ordinal.eq(i)].sort_values('date')
    assert len(oldc)==len(c) and np.allclose(oldc.equity,c.equity,atol=1e-8,rtol=0)
    keys=['exit_date','entry_date','symbol','signal_date']
    oldt=G['trades'].loc[G['trades'].start_ordinal.eq(i)].sort_values(keys).reset_index(drop=True)
    t=t.sort_values(keys).reset_index(drop=True)
    assert len(oldt)==len(t)
    for k in ['symbol','signal_date','entry_date','exit_date','reason']:assert oldt[k].astype(str).tolist()==t[k].astype(str).tolist(),k
    assert np.allclose(oldt.pnl,t.pnl,atol=1e-8,rtol=0)
    keys=['date','signal_date','symbol']
    olda=G['attempts'].loc[G['attempts'].start_ordinal.eq(i)].sort_values(keys).reset_index(drop=True)
    a=a.sort_values(keys).reset_index(drop=True)
    for k in ['symbol','signal_date','date','requested_quantity','filled_quantity','status']:assert olda[k].astype(str).tolist()==a[k].astype(str).tolist(),k
    a['signal_date']=pd.to_datetime(a.signal_date);o['signal_date']=pd.to_datetime(o.signal_date)
    a=a.merge(o[['signal_date','symbol','occupied_slot','original_quantity','quantity']],on=['signal_date','symbol'],validate='one_to_one')
    assert a.quantity.eq(a.requested_quantity).all()
    return a,m['action_gaps']

def main():
    summary=json.loads((PRIOR/'SUMMARY.json').read_text(encoding='utf-8'));assert summary['status']=='verified';end=summary['end']
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',APP/'tracker/data/market_status.json',
        GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',STRATEGY/'model/manifest.json',APP/'tracker/service.py']
    before={str(p):sha(p) for p in protected}
    starts=pd.read_parquet(PRIOR/'fifth_minus100/START_METRICS.parquet').sort_values('start_ordinal')
    out=ROOT/'archive/reports/holdout_restricted/hushen2_fifth_cash_audit'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True)
    print('OUTPUT',out,'PATHS',len(starts),flush=True);parts=[];gaps=set()
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(end,)) as pool:
        for i,future in enumerate(as_completed([pool.submit(run,(int(r.start_ordinal),pd.Timestamp(r.start_date))) for r in starts.itertuples()]),1):
            a,g=future.result();parts.append(a);gaps.update(g)
            if i%10==0 or i==len(starts):print('VERIFIED',i,len(starts),flush=True)
    a=pd.concat(parts,ignore_index=True);f=a.loc[a.status.eq('insufficient_cash_rejected')].copy()
    f['shortfall']=f.required_cost-f.cash_before;assert f.shortfall.gt(0).all()
    f['shortfall_fraction']=f.shortfall/f.required_cost
    f['covered_by_deferred']=f.cash_before+f.deferred_cash+1e-9>=f.required_cost
    f['fee_only']=f.cash_before+1e-9>=f.required_gross
    f['creation_fifth']=f.occupied_slot.eq(5)
    f['after_another100_affordable']=(f.quantity-100).ge(100)&((f.quantity-100)*f.modeled_buy_price+np.maximum(5,(f.quantity-100)*f.modeled_buy_price*.0003)).le(f.cash_before+1e-9)
    a.to_parquet(out/'ALL_ATTEMPTS.parquet',index=False);f.to_parquet(out/'CASH_REJECTIONS.parquet',index=False)
    expected=summary['rows'][1]['means']['cash_rejected']*58;assert abs(len(f)-expected)<1e-8
    assert all(sha(p)==h for p,h in before.items()) and not gaps
    counts=lambda field:{str(k):dict(total=int(len(g)),mean_per_path=float(len(g)/58),fraction=float(len(g)/len(f))) for k,g in f.groupby(field)}
    report=dict(status='verified',end=end,paths=58,rejections=len(f),mean_per_path=len(f)/58,
        creation_slot_distribution=counts('occupied_slot'),held_count_at_trigger_distribution=counts('held_count'),
        covered_by_deferred=int(f.covered_by_deferred.sum()),not_covered_even_with_deferred=int((~f.covered_by_deferred).sum()),
        fee_only=int(f.fee_only.sum()),already_reduced_fifth_orders=int(f.creation_fifth.sum()),
        shortfall_quantiles={str(q):float(f.shortfall.quantile(q)) for q in [0,.25,.5,.75,.9,1]},
        shortfall_fraction_quantiles={str(q):float(f.shortfall_fraction.quantile(q)) for q in [0,.25,.5,.75,.9,1]},
        diagnostic_only_another100_affordable=int(f.after_another100_affordable.sum()),
        examples=f.loc[~f.covered_by_deferred].sort_values('shortfall').iloc[[0,len(f.loc[~f.covered_by_deferred])//2,-1]].to_dict('records'),
        baseline_trade_equity_attempts_exact_match=True,protected_unchanged=True,action_gaps=[],
        note='Remaining rejections under fifth-slot preset-minus100 research variant,not production. No execution changes. Covered_by_deferred is a counterfactual affordability diagnostic,not proof that proceeds were usable before the buy intraday. Another100 statistic is not a strategy replay.')
    (out/'SUMMARY.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),**report),default=str,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
