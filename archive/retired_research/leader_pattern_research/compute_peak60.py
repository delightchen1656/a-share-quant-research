"""Observe each frozen signal's next60exchange-session intraday high, no new screening."""
from pathlib import Path
import hashlib,json
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;STUDY=HERE/'holdout_restricted/patterns_v1';OUT=STUDY/'future60_high_v1'
def clean(x):return float(x) if np.isfinite(x) else None
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def peak(high,valid,dates,t,reference):
    end=t+60;stop=min(end,len(high)-1);q=np.arange(t+1,stop+1)
    good=valid[q]&np.isfinite(high[q])&(high[q]>0)
    full=end<len(high) and len(q)==60 and good.all()
    result=dict(peak_status60='完整' if full else '未满60日' if end>=len(high) else '观察期缺价',
        peak_complete60=bool(full),window_end_date60=dates[end].strftime('%Y-%m-%d') if end<len(dates) else None,
        peak_observed_days60=int(good.sum()),peak_return60=None,peak_price60=None,peak_date60=None,peak_day60=None,
        peak40_same_cohort=None)
    if full:
        best=q[int(np.argmax(high[q]))]
        result.update(peak_return60=float(high[best]/reference-1),peak_price60=float(high[best]),
            peak_date60=dates[best].strftime('%Y-%m-%d'),peak_day60=int(best-t),
            peak40_same_cohort=float(np.max(high[t+1:t+41])/reference-1))
    return result

def checks():
    dates=pd.bdate_range('2020-01-01',periods=63);h=np.full(63,10.);valid=np.ones(63,bool)
    h[0]=999;h[60]=20;h[61]=888
    a=peak(h,valid,dates,0,10);assert a['peak_return60']==1 and a['peak_day60']==60
    assert a['peak_date60']==dates[60].strftime('%Y-%m-%d') and a['peak40_same_cohort']==0
    missing=valid.copy();missing[15]=False;b=peak(h,missing,dates,0,10);assert b['peak_return60'] is None and b['peak_status60']=='观察期缺价'
    b=peak(h,valid,dates,4,10);assert b['peak_return60'] is None and b['peak_status60']=='未满60日'
    h[1]=20;a=peak(h,valid,dates,0,10);assert a['peak_day60']==1
    return dict(signal_high_excluded=True,D60_included_D61_excluded=True,high_not_close=True,
        missing_quotes_not_filled=True,unfinished_not_reported_as_full_peak=True,earliest_tied_peak_used=True)

def main():
    assert not OUT.exists(),'Preserve observation snapshots'
    tests=checks();OUT.mkdir(parents=True)
    sources={'first':STUDY/'event_results_v1r2/events.parquet',
        'ma60':STUDY/'first_below_ma60_v1/selected_events.parquet',
        'volume':STUDY/'base_volume_strong_bullish_v3/selected_events.parquet'}
    groups={k:pd.read_parquet(p) for k,p in sources.items()};groups['first']=groups['first'][groups['first'].rule.eq('first')]
    dump(OUT/'SPEC.json',dict(user_request='改成未来60交易日最高点',registered_before_outcomes=True,
        formula='max(adjusted high of D+1..D+60)/adjusted signal close -1',
        horizon=60,signal_day_excluded=True,calendar='Frozen official exchange-session index',
        incomplete='If fewer than60future sessions or any missing active quote, withhold full-window peak.',
        screening_unchanged=True,source_sha256={k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in sources.items()},
        caution='Ex-post price maximum, not executable realized profit; no fees; retrospective current stock pool.'))
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(STUDY/'event_results_v1r2/exchange_sessions.csv').date))
    all_events=pd.concat(groups.values()).drop_duplicates('event_id')
    manifest=json.loads((STUDY/'inputs_daily/manifest.json').read_text(encoding='utf-8'))
    hashes={(r['code'],r['mode']):r['snapshot_sha256'] for r in manifest['files']}
    rows=[]
    for code,g in all_events.groupby('code'):
        fs={}
        for mode in ['qfq','raw']:
            p=STUDY/'inputs_daily'/mode/f'{code}.parquet';assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[(code,mode)]
            fs[mode]=pd.read_parquet(p).set_index('date').reindex(dates)
        q=fs['qfq'];r=fs['raw'];h=q.high.to_numpy(float)
        valid=r.tradestatus.astype(str).eq('1').to_numpy()&r.volume.gt(0).to_numpy()
        for col in ['open','high','low','close']:
            a=q[col].to_numpy(float);valid &= np.isfinite(a)&(a>0)
        for e in g.itertuples():
            t=dates.get_loc(pd.Timestamp(e.signal_date));reference=float(e.adjusted_reference_price)
            assert abs(reference-q.close.iloc[t])<1e-10
            rows.append(dict(event_id=e.event_id,code=code,signal_date=e.signal_date,signal_close=reference,**peak(h,valid,dates,t,reference)))
    data=pd.DataFrame(rows);data.to_parquet(OUT/'event_metrics.parquet',index=False)
    summaries=[]
    for name,g in groups.items():
        joined=g[['event_id']].merge(data,on='event_id',validate='one_to_one');full=joined[joined.peak_complete60]
        summaries.append(dict(group=name,signals=len(joined),complete60=len(full),
            unfinished=int(joined.peak_status60.eq('未满60日').sum()),missing=int(joined.peak_status60.eq('观察期缺价').sum()),
            mean_peak60=clean(full.peak_return60.mean()),median_peak60=clean(full.peak_return60.median()),
            mean_peak40_same_cohort=clean(full.peak40_same_cohort.mean()),median_peak40_same_cohort=clean(full.peak40_same_cohort.median()),
            touch10=float(full.peak_return60.ge(.1).mean()),touch20=float(full.peak_return60.ge(.2).mean())))
    dump(OUT/'SUMMARY.json',dict(cutoff='2026-10-26',summaries=summaries,checks=tests))
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
