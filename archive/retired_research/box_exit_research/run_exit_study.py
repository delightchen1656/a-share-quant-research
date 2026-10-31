"""Exploratory ideal adjusted-price exits; NOT a cash/share account backtest."""
from pathlib import Path
from decimal import Decimal,ROUND_HALF_UP
import hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;INPUT=HERE/'inputs_pre2025';OUT=HERE/'holdout_restricted/exit_v1'
STOPS=['fixed5','fixed8','box_cap8'];METHODS=['none','profit70','atr25','ma5','ma10']

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def finite(x):return float(x) if np.isfinite(x) else None
def limit_down(preclose,is_st):
    rate=Decimal('0.95') if str(is_st)=='1' else Decimal('0.90')
    return float((Decimal(str(preclose))*rate).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))

def simulate(f,t,box_low,stop_kind,method):
    entry=float(f.close.iloc[t]);end=t+60;assert end<len(f)
    initial=entry*(.95 if stop_kind=='fixed5' else .92)
    if stop_kind=='box_cap8':initial=max(initial,float(box_low)*.995)
    assert initial<entry
    future=f.iloc[t+1:end+1];active=future[future.active]
    if future.unknown.any():return dict(status='unknown_quote',entry=entry)
    if active.empty:return dict(status='no_observable_path',entry=entry)
    benchmark=float(active.high.max()/entry-1)
    stop=initial;highest=entry;pending=None;blocked=0;blocked_at_limit=0;lowest=entry;last_close=entry;exit_price=None;exit_day=None;reason=None;gap_cross=False
    for j in range(t+1,end+1):
        previous_stop=stop
        if highest>=entry*1.10-1e-10:
            if method=='profit70':stop=max(stop,entry+.70*(highest-entry))
            if method=='atr25' and np.isfinite(f.atr14.iloc[j-1]):stop=max(stop,highest-2.5*f.atr14.iloc[j-1])
        assert stop>=previous_stop
        day=f.iloc[j]
        if not day.active:continue
        lowest=min(lowest,float(day.low));last_close=float(day.close)
        locked=abs(day.raw_high-day.raw_low)<.005 and day.raw_close<day.preclose-.005
        theoretical_lower=limit_down(day.preclose,day.isST)
        at_lower=abs(day.raw_close-theoretical_lower)<.005
        hit=day.low<=stop+1e-10
        if pending or hit:
            if locked:
                blocked+=1;blocked_at_limit+=int(at_lower);pending=pending or 'stop_pending_limit';highest=max(highest,float(day.high));continue
            if pending:
                exit_price=float(day.open);reason=pending;gap_cross=day.open<stop-1e-10
            else:
                exit_price=float(min(day.open,stop));reason='gap_stop' if day.open<stop-1e-10 else 'stop_touch';gap_cross=reason=='gap_stop'
            exit_day=j;break
        if j==end:
            if locked:pending='time_pending_limit';blocked+=1;blocked_at_limit+=int(at_lower);highest=max(highest,float(day.high));continue
            exit_price=float(day.close);exit_day=j;reason='time60';break
        if method in ['ma5','ma10'] and highest>=entry*1.10-1e-10:
            ma=day[method]
            if np.isfinite(ma) and day.close<ma:pending='close_'+method+'_next_open'
        highest=max(highest,float(day.high))
    unresolved=exit_price is None
    result=dict(status='unresolved' if unresolved else 'estimated_exit',entry=entry,benchmark_gain60=benchmark,
        exit_return=None if unresolved else float(exit_price/entry-1),mark_return=float(last_close/entry-1),
        exit_day=None if unresolved else int(exit_day-t),exit_price=exit_price,exit_reason=reason,
        initial_stop_return=float(initial/entry-1),blocked_days=blocked,blocked_at_limit=blocked_at_limit,gap_cross=bool(gap_cross),
        stop_overshoot=False if unresolved else bool(exit_price<initial-1e-8),
        adverse_full_exit_day=float(lowest/entry-1),last_stop=float(stop))
    return result

def prepare_frame(raw,q,dates):
    r=raw.set_index('date').reindex(dates);q=q.set_index('date').reindex(dates)
    f=pd.DataFrame(index=dates)
    for col in ['open','high','low','close']:f[col]=pd.to_numeric(q[col],errors='coerce');f['raw_'+col]=pd.to_numeric(r[col],errors='coerce')
    f['preclose']=pd.to_numeric(r.preclose,errors='coerce');f['isST']=r.isST.astype(str)
    active=r.tradestatus.astype(str).eq('1')&pd.to_numeric(r.volume,errors='coerce').gt(0)
    for col in ['open','high','low','close','raw_open','raw_high','raw_low','raw_close','preclose']:active &= np.isfinite(f[col])&f[col].gt(0)
    f['active']=active;f['unknown']=~active&~r.tradestatus.astype(str).eq('0')
    c=f.close.where(active);tr=pd.concat([f.high-f.low,(f.high-c.shift()).abs(),(f.low-c.shift()).abs()],axis=1).max(axis=1).where(active)
    f['atr14']=tr.rolling(14,min_periods=14).mean()
    for n in [5,10]:f['ma'+str(n)]=c.rolling(n,min_periods=n).mean()
    return f

def summarize(data):
    exited=data[data.status.eq('estimated_exit')];positive=exited[exited.benchmark_gain60.gt(1e-12)]
    substantial=exited[exited.benchmark_gain60.ge(.10)]
    ratio=substantial.exit_return/substantial.benchmark_gain60
    return dict(paths=len(data),estimated_exits=len(exited),unknown_quotes=int(data.status.eq('unknown_quote').sum()),
        unresolved=int(data.status.eq('unresolved').sum()),
        mean_return=finite(exited.exit_return.mean()),median_return=finite(exited.exit_return.median()),
        negative_rate=finite(exited.exit_return.lt(0).mean()),worst_return=finite(exited.exit_return.min()),
        loss_ge10=int(exited.exit_return.le(-.10+1e-10).sum()),
        capture70_positive=finite((positive.exit_return>=.7*positive.benchmark_gain60-1e-10).mean()),positive_peak_n=len(positive),
        capture70_peak10=finite((substantial.exit_return>=.7*substantial.benchmark_gain60-1e-10).mean()),peak10_n=len(substantial),
        median_capture_peak10=finite(ratio.median()),mean_days=finite(exited.exit_day.mean()),
        overshoot=int(exited.stop_overshoot.sum()),blocked_paths=int(data.blocked_days.fillna(0).gt(0).sum()),
        average_adverse_full_exit_day=finite(exited.adverse_full_exit_day.mean()))

def main():
    assert not OUT.exists(),'Keep results snapshots immutable'
    registered=HERE/'REGISTERED_SPEC.json';assert registered.exists()
    manifest=json.loads((INPUT/'MANIFEST.json').read_text(encoding='utf-8'))
    assert sha(INPUT/'events.parquet')==manifest['events_sha256'] and sha(INPUT/'calendar.json')==manifest['calendar_sha256']
    e=pd.read_parquet(INPUT/'events.parquet');dates=pd.DatetimeIndex(pd.to_datetime(pd.read_json(INPUT/'calendar.json').date))
    assert dates.max()<=pd.Timestamp('2024-12-31') and e.signal_date.le('2024-12-31').all()
    lookup={(r['code'],r['mode']):r for r in manifest['files']};results=[];purged=[];cohort_counts={}
    for code,g in e.groupby('code'):
        frames={}
        for mode in ['raw','qfq']:
            rec=lookup[(code,mode)];assert sha(rec['path'])==rec['sha256'];frames[mode]=pd.read_parquet(rec['path'])
            assert pd.to_datetime(frames[mode].date).max()<=pd.Timestamp('2024-12-31')
        f=prepare_frame(frames['raw'],frames['qfq'],dates)
        for event in g.itertuples():
            t=dates.get_loc(pd.Timestamp(event.signal_date));end=t+60
            cohort='2019-2022' if event.year<=2022 else str(event.year)
            boundary=pd.Timestamp('2022-12-31' if event.year<=2022 else f'{event.year}-12-31')
            if end>=len(dates) or dates[end]>boundary:
                purged.append(dict(event_id=event.event_id,cohort=cohort,reason='D60 crosses cohort end'));continue
            assert f.active.iloc[t] and abs(f.close.iloc[t]-event.signal_close)<1e-8
            for stop in STOPS:
                for method in METHODS:
                    results.append(dict(event_id=event.event_id,code=code,name=event.name,signal_date=event.signal_date,cohort=cohort,
                        rule=stop+'__'+method,stop=stop,profit=method,**simulate(f,t,event.box_low,stop,method)))
    data=pd.DataFrame(results);summary=[]
    for cohort in ['all_pre2025','2019-2022','2023','2024']:
        d=data if cohort=='all_pre2025' else data[data.cohort.eq(cohort)]
        for rule,g in d.groupby('rule'):summary.append(dict(cohort=cohort,rule=rule,**summarize(g)))
    OUT.mkdir(parents=True);data.to_parquet(OUT/'event_exits.parquet',index=False)
    dump(OUT/'summary.json',summary);dump(OUT/'purged.json',purged)
    audit=dict(status='ok',source_signals=len(e),cohort_purged=len(purged),tested_signals=int(data.event_id.nunique()),
        rules=15,rows=len(data),registered_spec_sha256=sha(registered),input_manifest_sha256=sha(INPUT/'MANIFEST.json'),
        results_sha256=sha(OUT/'event_exits.parquet'),no_post2024_inputs=True,not_a_blind_test=True,
        unit='ideal adjusted-price paths; not portfolio or economic share accounting',cohort_counts=data[['event_id','cohort']].drop_duplicates().cohort.value_counts().to_dict())
    dump(OUT/'AUDIT.json',audit)
    print(json.dumps(audit,ensure_ascii=False),flush=True)
    print(json.dumps([r for r in summary if r['cohort']=='all_pre2025'],ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
