"""Reconstruct Q1-2020 paths and classify actual conditional-order outcomes."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from datetime import datetime
from bisect import bisect_right
import json,pickle,sys
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from replay_hushen2_local import ROOT,STRATEGY,APP,GAME,CASES,sha,load

G={}

def initialize(end_text):
    with (CASES/'INPUT_PACK.pkl').open('rb') as f:p=pickle.load(f)
    end=pd.Timestamp(end_text);frozen_end=pd.Timestamp(p['end'])
    assert end>=frozen_end and end-pd.Timedelta(days=37)<=p['signals'].date.max()
    if end>frozen_end:
        sys.path.insert(0,str(APP/'runtime'));sys.path.insert(0,str(APP/'tracker'))
        market=load('audit_buywait_market',APP/'tracker/market.py')
        latest_sessions=[pd.Timestamp(d) for d in market.calendar_extended(APP/'tracker/data')]
        symbols=sorted(p['signals'].loc[p['signals'].date.between('2020-01-01',end-pd.Timedelta(days=37)),'symbol'].unique())
        for symbol in symbols:
            path=market.DATA/'raw'/symbol[-2:]/f'{symbol}.parquet'
            if not path.exists():continue
            dtype=pq.read_schema(path).field('date').type
            lo,hi=(frozen_end,end) if pa.types.is_timestamp(dtype) else (frozen_end.strftime('%Y-%m-%d'),end.strftime('%Y-%m-%d'))
            b=pd.read_parquet(path,filters=[('date','>',lo),('date','<=',hi)])
            if b.empty:continue
            b.date=pd.to_datetime(b.date);b=b.set_index('date')
            frozen=p['bars'][symbol]
            for k in ['open','high','low','close','preclose','volume','amount']:b[k]=pd.to_numeric(b[k],errors='raise')
            p['bars'][symbol]=pd.concat([frozen,b[frozen.columns]]).sort_index()
        p['calendar']=sorted(set(p['calendar'])|{d for d in latest_sessions if frozen_end<d<=end})
    p['end']=end
    original=load('buywait_frozen_core',GAME/'runtime/run_batch.py')
    adapter=load('buywait_fixed_ioc',GAME/'runtime/baseline_fixed_ioc.py')
    core=adapter.fixed_ioc_engine(original,manual_expiry_open=False,filled_slots=False)
    source=core.adapted_source
    old='trades: list[dict] = []';assert source.count(old)==1
    source=source.replace(old,old+'\n    created_order_records=[]\n    expired_order_records=[]')
    old='pending_orders_created += 1';assert source.count(old)==1
    source=source.replace(old,old+'\n            created_order_records.append(dict(symbol=symbol,signal_date=date,quantity=pending[-1].quantity,target=pending[-1].target))')
    old='expired_entries += 1';assert source.count(old)==1
    source=source.replace(old,old+'\n                expired_order_records.append(dict(symbol=p.symbol,signal_date=p.signal_date))')
    old='result["fixed_order_attempts"] = fixed_order_attempts';assert source.count(old)==1
    source=source.replace(old,old+'\n    result["created_order_records"]=created_order_records\n    result["expired_order_records"]=expired_order_records')
    exec(compile(source,'<order_timing_diagnostics_only>','exec'),core.__dict__)
    G.update(pack=p,core=core,source=source)

def run(job):
    i,start=job;p=G['pack'];end=p['end'];core=G['core'];last=end-pd.Timedelta(days=37)
    core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=last;core.YEARS=list(range(2020,end.year+1))
    gaps=set();curve=[]
    r,t=core.simulate(p['signals'].loc[p['signals'].date.between(start,last)],p['bars'],[d for d in p['calendar'] if d<=end],
        'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,keep_trades=True,actions=p['actions'],known_action_keys=p['known'],
        coverage_sink=gaps,delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
    f=pd.DataFrame(r['created_order_records']);assert len(f)==r['pending_orders_created']
    a=pd.DataFrame(r['fixed_order_attempts']);a['signal_date']=pd.to_datetime(a.signal_date);a['date']=pd.to_datetime(a.date)
    assert not a.duplicated(['signal_date','symbol']).any()
    f=f.merge(a[['symbol','signal_date','date','filled_quantity','status']],on=['symbol','signal_date'],how='left',validate='one_to_one')
    expiry={(pd.Timestamp(x['signal_date']),x['symbol']) for x in r['expired_order_records']}
    f['status']=f.status.fillna('expired_without_trigger')
    assert int(f.status.eq('expired_without_trigger').sum())==len(expiry)==r['expired_entry_orders']
    assert all((pd.Timestamp(x.signal_date),x.symbol) in expiry for x in f.loc[f.status.eq('expired_without_trigger')].itertuples())
    f['start_ordinal']=i;f['start_date']=start
    f['first_eligible_session']=[p['calendar'][bisect_right(p['calendar'],d)] for d in f.signal_date]
    f['calendar_days_to_attempt']=(f.date-f.signal_date).dt.days
    filled=f.filled_quantity.fillna(0).gt(0)
    assert f.loc[filled,'calendar_days_to_attempt'].between(1,7).all()
    f['category']='failed'
    first=filled&f.date.eq(f.first_eligible_session)
    f.loc[first,'category']='filled_first_trading_session'
    f.loc[filled&~first,'category']='filled_later_within_7calendar'
    assert r['filled_orders']==int(filled.sum())==len(t)+r['open_positions_at_end']
    assert not r['pending_orders_at_end'] and not r['open_positions_at_end']
    assert abs(curve[-1]['equity']-100000-t.pnl.sum())<1e-6
    assert np.allclose(t['return'],t.pnl/t.entry_cost,rtol=0,atol=1e-12)
    f=f.merge(t[['symbol','signal_date','entry_date','exit_date','return','reason','pnl','entry_cost']],
        on=['symbol','signal_date'],how='left',validate='one_to_one')
    assert f.loc[filled,'return'].notna().all() and f.loc[~filled,'return'].isna().all()
    assert f.loc[filled,'date'].eq(f.loc[filled,'entry_date']).all()
    return i,f,dict(start_ordinal=i,start_date=str(start.date()),created=len(f),filled=int(filled.sum()),first_trading=int(first.sum()),
        later=int((filled&~first).sum()),failed=int((~filled).sum()),expired=r['expired_entry_orders'],cash_rejected=int(f.status.eq('insufficient_cash_rejected').sum()),
        other_failed=int((~filled&~f.status.isin(['expired_without_trigger','insufficient_cash_rejected'])).sum()),
        ending_equity=curve[-1]['equity'],action_gaps=sorted(gaps))

def main():
    sys.path.insert(0,str(APP/'runtime'));sys.path.insert(0,str(APP/'tracker'))
    market=load('audit_buywait_parent_market',APP/'tracker/market.py');health=market.health(APP/'tracker/data');end=health['market_date']
    manifest=json.loads((GAME/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    for group in ['runtime','inputs']:
        for relative,expected in manifest[group].items():assert sha(GAME/relative)==expected
    selection=json.loads((STRATEGY/'CURRENT_SELECTION.json').read_text(encoding='utf-8'))
    assert selection['selection']['signal_filter']['minimum_atr']==.025 and not selection['selection']['signal_filter']['refill']
    protected=[STRATEGY/'CURRENT_SELECTION.json',APP/'CURRENT_SELECTION.json',APP/'tracker/data/ledger.sqlite3',APP/'tracker/data/market_status.json',
        GAME/'runtime/run_batch.py',GAME/'runtime/baseline_fixed_ioc.py',CASES/'INPUT_PACK.pkl',STRATEGY/'model/manifest.json',APP/'tracker/service.py']
    before={str(p):sha(p) for p in protected}
    starts=[pd.Timestamp(d) for d in health['sessions'] if d.startswith('2020-') and d[5:7]<='03'];assert len(starts)==58
    out=ROOT/'archive/reports/holdout_restricted/hushen2_buy_wait'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True)
    print('OUTPUT',out,'STARTS',len(starts),'END',end,flush=True)
    frames=[];paths=[]
    with ProcessPoolExecutor(max_workers=3,initializer=initialize,initargs=(end,)) as pool:
        for i,future in enumerate(as_completed([pool.submit(run,(i,s)) for i,s in enumerate(starts,1)]),1):
            _,f,m=future.result();frames.append(f);paths.append(m)
            if i%10==0 or i==len(starts):print('COMPLETE',i,len(starts),'GAPS',sorted({g for x in paths for g in x['action_gaps']}),flush=True)
    f=pd.concat(frames,ignore_index=True).sort_values(['start_ordinal','signal_date','symbol']);m=pd.DataFrame(paths).sort_values('start_ordinal')
    f.to_parquet(out/'ORDER_OUTCOMES.parquet',index=False);m.to_parquet(out/'PATH_COUNTS.parquet',index=False)
    filled=f.filled_quantity.fillna(0).gt(0);n=len(f)
    categories={k:dict(total=int(f.category.eq(k).sum()),mean_per_path=float(f.category.eq(k).sum()/58),fraction=float(f.category.eq(k).mean())) for k in sorted(f.category.unique())}
    days={str(d):dict(total=int((filled&f.calendar_days_to_attempt.eq(d)).sum()),mean_per_path=float((filled&f.calendar_days_to_attempt.eq(d)).sum()/58)) for d in range(1,8)}
    def returns_summary(mask):
        g=f.loc[mask];r=g['return'];assert r.notna().all()
        return dict(trades=len(g),mean_net_return=float(r.mean()),median_net_return=float(r.median()),
            positive_fraction=float(r.gt(0).mean()),take_count=int(g.reason.eq('take').sum()),stop_count=int(g.reason.eq('stop').sum()),
            expiry_count=int(g.reason.eq('expiry').sum()),equal_path_mean_net_return=float(g.groupby('start_ordinal')['return'].mean().mean()))
    returns_groups=dict(calendar_day1=returns_summary(filled&f.calendar_days_to_attempt.eq(1)),
        calendar_days2_7=returns_summary(filled&f.calendar_days_to_attempt.between(2,7)),
        first_trading_session=returns_summary(f.category.eq('filled_first_trading_session')),
        later_trading_sessions=returns_summary(f.category.eq('filled_later_within_7calendar')))
    previous=ROOT/'archive/reports/holdout_restricted/hushen2_buy_wait/attempt_20261026_030015/ORDER_OUTCOMES.parquet'
    if previous.exists():
        old=pd.read_parquet(previous).sort_values(['start_ordinal','signal_date','symbol']).reset_index(drop=True)
        current=f.reset_index(drop=True)
        for k in old.columns:pd.testing.assert_series_equal(old[k],current[k],check_names=False,check_dtype=False)
    gaps=sorted({g for x in paths for g in x['action_gaps']});unchanged={p:sha(p)==h for p,h in before.items()}
    assert all(unchanged.values()) and market.health(APP/'tracker/data')['audit_sha256']==health['audit_sha256']
    report=dict(status='verified' if not gaps else 'incomplete_action_coverage',paths=58,end=end,total_created_orders=n,categories=categories,
        failure_status_counts=f.loc[~filled].status.value_counts().to_dict(),calendar_day_success_counts=days,trade_return_groups=returns_groups,
        average_path_counts={k:float(m[k].mean()) for k in ['created','filled','first_trading','later','failed','expired','cash_rejected','other_failed']},
        action_gaps=gaps,protected_unchanged=unchanged,input_pack_sha256=before[str(CASES/'INPUT_PACK.pkl')],market_audit=health['audit'],
        protocol='Reconstructed58 Q1-2020 starts to latest committed local endpoint. Same frozen Oct22 signal vintage and execution; append committed raw tail only. Count only actually created orders,not skipped no-slot/duplicate signals. First day=first eligible exchange session following signal,not necessarily next calendar day. Also record natural-day1..7 success counts. All fixedIOC fees/capacity/slot/ATR025/no-refill/expiryclose/37daytail unchanged. Overlapping paths are sensitivity observations,not independent samples. No production/account writes.')
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(output=str(out),**report),ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
