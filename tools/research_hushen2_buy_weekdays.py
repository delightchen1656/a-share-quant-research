"""Controlled entry-weekday trial. Frozen signals, no production writes or fitting."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
import argparse,json,pickle
import numpy as np
import pandas as pd
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load

G={}
VARIANTS={'current':None,'monday':(0,),'friday':(4,),'monday_friday':(0,4)}


def make_engine(allowed):
    original=load('weekday_frozen_core',GAME/'runtime/run_batch.py')
    adapter=load('weekday_fixed_adapter',GAME/'runtime/baseline_fixed_ioc.py')
    engine=adapter.fixed_ioc_engine(original,manual_expiry_open=False,filled_slots=False)
    source=engine.adapted_source
    if allowed is not None:
        old='            bar = get_bar(by_symbol, p.symbol, date)'
        assert source.count(old)==1
        source=source.replace(old,
            '            if date.weekday() not in ALLOWED_ENTRY_WEEKDAYS:\n'
            '                still_pending.append(p)\n                continue\n'+old)
        engine.ALLOWED_ENTRY_WEEKDAYS=allowed
        exec(compile(source,'<entry_weekday_gate_only>','exec'),engine.__dict__)
    engine.adapted_source=source
    return engine


def initialize(out):
    with (Path(out)/'INPUTS_PRE2025.pkl').open('rb') as f:G['p']=pickle.load(f)
    G.update(out=Path(out),risk=load('weekday_risk',STRATEGY/'backtest/compute_risk_metrics.py'))


def run(job):
    variant,year=job;p=G['p'];core=make_engine(VARIANTS[variant]);end=pd.Timestamp(f'{year}-12-31')
    last=end-pd.Timedelta(days=37);calendar=[d for d in p['calendar'] if d<=end]
    starts=[d for d in calendar if d.year==year and d.month<=3]
    records=[];trades=[];all_gaps=set()
    for i,start in enumerate(starts,1):
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=[year]
        curve=[];gaps=set()
        r,t=core.simulate(p['signals'].loc[p['signals'].date.between(start,last)],p['bars'],calendar,
            'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,
            actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
        c=pd.DataFrame(curve);c['start_ordinal']=i;c['start_date']=start
        m=G['risk'].recompute_metrics(c).iloc[0].to_dict()
        a=pd.DataFrame(r['fixed_order_attempts'])
        filled=int(a.filled_quantity.gt(0).sum()) if len(a) else 0
        zero=int(a.filled_quantity.eq(0).sum()) if len(a) else 0
        assert not r['open_positions_at_end'] and not r['pending_orders_at_end']
        assert filled==r['filled_orders']==len(t)
        assert r['pending_orders_created']==filled+zero+r['expired_entry_orders']
        assert abs(c.equity.iloc[-1]-100000-t.pnl.sum())<1e-6
        assert c.date.max()<=pd.Timestamp('2024-12-31')
        if VARIANTS[variant] is not None and len(t):
            assert pd.to_datetime(t.entry_date).dt.weekday.isin(VARIANTS[variant]).all()
        elapsed=(c.date.iloc[-1]-start).days
        bm=(p['index'].loc[c.date.iloc[-1]]/p['index'].loc[start])**(365/elapsed)-1
        m.update(start_date=str(start.date()),start_ordinal=i,benchmark_annualized=float(bm),
            annualized_excess=m['annualized_return']-bm,created=r['pending_orders_created'],filled=filled,
            failed=zero+r['expired_entry_orders'],expired=r['expired_entry_orders'],
            cash_rejected=int(a.status.eq('insufficient_cash_rejected').sum()) if len(a) else 0,
            take_count=int(t.reason.eq('take').sum()),stop_count=int(t.reason.eq('stop').sum()),
            expiry_count=int(t.reason.eq('expiry').sum()))
        records.append(m);all_gaps.update(gaps)
        t['start_ordinal']=i;trades.append(t)
    folder=G['out']/str(year)/variant;folder.mkdir(parents=True,exist_ok=True)
    m=pd.DataFrame(records);m.to_parquet(folder/'START_METRICS.parquet',index=False)
    if variant=='current':
        reference=pd.read_parquet(CASES/str(year)/'START_METRICS.parquet')
        keys=['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']
        assert list(pd.to_datetime(m.start_date))==list(pd.to_datetime(reference.start_date))
        assert (m[keys]-reference[keys]).abs().max().max()<1e-12,'Baseline regression mismatch'
    pd.concat(trades,ignore_index=True).to_parquet(folder/'TRADES.parquet',index=False)
    (folder/'SIMULATE_SOURCE.txt').write_text(core.adapted_source,encoding='utf-8')
    keys=['cumulative_return','annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0',
        'created','filled','failed','expired','cash_rejected','take_count','stop_count','expiry_count']
    return dict(variant=variant,year=year,starts=len(starts),end=str(end.date()),
        **{k:float(m[k].mean()) for k in keys},positive_fraction=float(m.cumulative_return.gt(0).mean()),
        beat_fraction=float(m.annualized_excess.gt(0).mean()),action_gaps=sorted(all_gaps))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--output',type=Path);parser.add_argument('--fetch-gaps',action='store_true');args=parser.parse_args()
    out=args.output or ROOT/'archive/reports/holdout_restricted/hushen2_entry_weekdays'/datetime.now().strftime('pre2025_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=bool(args.output))
    if args.fetch_gaps:
        import baostock as bs
        gaps=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))['action_gaps']
        folder=out/'actions';folder.mkdir(exist_ok=True)
        assert bs.login().error_code=='0'
        try:
            for key in gaps:
                symbol,year=key.split('/');assert int(year)<=2024
                r=bs.query_dividend_data(code=symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate');records=[]
                while r.error_code=='0' and r.next():records.append(dict(zip(r.fields,r.get_row_data())))
                assert r.error_code=='0'
                (folder/(key.replace('/','_')+'.json')).write_text(json.dumps(dict(key=key,error_code=r.error_code,records=records,fetched_at=datetime.now().isoformat()),ensure_ascii=False,indent=2),encoding='utf-8')
                print('ACTION_RECEIPT',key,records,flush=True)
        finally:bs.logout()
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',GAME/'runtime/run_batch.py',
        GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl']
    protected+=list((STRATEGY/'model').glob('*.txt'))
    before={str(f):sha(f) for f in protected}
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ('runtime','inputs'):
        for rel,expected in manifest[group].items():assert sha(GAME/rel)==expected
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))['selection']
    assert selection['slots']==5 and selection['signal_filter']['minimum_atr']==.025
    with (CASES/'INPUT_PACK.pkl').open('rb') as f:p=pickle.load(f)
    for path in (out/'actions').glob('*.json'):
        receipt=json.loads(path.read_text(encoding='utf-8'));assert receipt['error_code']=='0'
        key=receipt['key'];symbol,year=key.split('/');assert int(year)<=2024
        if key in p['known']:continue
        p['known'].add(key)
        for row in receipt['records']:
            if not row.get('dividOperateDate'):continue
            d=pd.Timestamp(row['dividOperateDate']);number=lambda k:float(str(row.get(k,'')).strip() or 0)
            p['actions'].setdefault((d,symbol),[]).append(dict(cash=number('dividCashPsBeforeTax'),
                stock=number('dividStocksPs')+number('dividReserveToStockPs'),taxable_stock=number('dividStocksPs'),
                pay=pd.Timestamp(row.get('dividPayDate') or d),release=pd.Timestamp(row.get('dividStockMarketDate') or d),source=str(path)))
    end=pd.Timestamp('2024-12-31')
    p['signals']=p['signals'].loc[p['signals'].date.between('2020-01-01',end)].copy()
    assert p['signals'].atr_pct.ge(.025).all()
    p['calendar']=[d for d in p['calendar'] if d<=end];p['index']=p['index'].loc[:end]
    p['bars']={s:b.loc[:end].copy() for s,b in p['bars'].items()}
    p['actions']={k:v for k,v in p['actions'].items() if k[0]<=end}
    p['delists']={s:d for s,d in p['delists'].items() if d<=end};p['end']=end
    with (out/'INPUTS_PRE2025.pkl').open('wb') as f:pickle.dump(p,f,pickle.HIGHEST_PROTOCOL)
    protocol=dict(scope='2020-2024 yearly Q1 all trading-day starts; entry-day gate only',
        variants=VARIANTS,entry_window='Original7 calendar days, no extension; keep pending until expiry on disallowed days',
        baseline='ATR025 current5slots20%,fixedIOC,original expiry close,37day stop-entry tail,all other frozen rules',
        retraining=False,software_changed=False,isolation_claim='Root runs prespecified controlled comparison; not a fresh context-isolated development agent',
        input_sha256=sha(out/'INPUTS_PRE2025.pkl'),protected_before=before)
    (out/'PROTOCOL.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OUTPUT',out,flush=True);rows=[]
    with ProcessPoolExecutor(max_workers=args.workers,initializer=initialize,initargs=(str(out),)) as pool:
        for fut in as_completed([pool.submit(run,(v,y)) for y in range(2020,2025) for v in VARIANTS]):
            row=fut.result();rows.append(row);print('COMPLETE',row['year'],row['variant'],'GAPS',row['action_gaps'],flush=True)
    rows.sort(key=lambda r:(r['year'],list(VARIANTS).index(r['variant'])))
    pd.DataFrame(rows).to_csv(out/'COMPARISON.csv',index=False,encoding='utf-8-sig')
    assert all(sha(Path(f))==h for f,h in before.items())
    gaps=sorted({g for r in rows for g in r['action_gaps']})
    summary=dict(status='verified' if not gaps else 'incomplete_action_coverage',rows=rows,action_gaps=gaps,protected_unchanged=True)
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
