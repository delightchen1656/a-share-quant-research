"""Match only the frozen base-box structure over verified main-board quotes."""
from pathlib import Path
import argparse,json,hashlib,datetime
import numpy as np
import pandas as pd
from find_base_volume_bullish_v2 import detect
from dedup_same_box_v4 import dedup
from observe_next_open60 import observe,OBSERVATION_VERSION,MATCH_DIRECTORY

HERE=Path(__file__).resolve().parent
CURRENT=HERE/'market_wide/holdout_restricted/CURRENT.json'
MIN_VOLUME_MULTIPLE=1.2
STRUCTURE_VERSION='base_volume_strong_bullish_one_box_v5_volume12'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_suffix(p.suffix+'.tmp')
    temp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(p)
def finite(x):return float(x) if np.isfinite(x) else None

def build(base,publish=True):
    base=Path(base).resolve();mfile=base/'inputs_daily/manifest.json'
    m=json.loads(mfile.read_text(encoding='utf-8'));out=base/MATCH_DIRECTORY;ready=out/'READY.json'
    assert m.get('scope')=='SH_SZ_MAIN_BOARD_ONLY','Only SH/SZ main-board inputs are permitted'
    if ready.exists():
        bundle=json.loads(ready.read_text(encoding='utf-8'));assert bundle['manifest_sha256']==sha(mfile)
        assert bundle['observation_version']==OBSERVATION_VERSION
        if publish:dump(CURRENT,bundle)
        print('Reused verified existing matches.',flush=True);return bundle
    out.mkdir(exist_ok=True)
    universe=pd.read_parquet(base/'universe.parquet');assert universe.code.is_unique
    assert universe.code.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(base/'exchange_sessions.csv').date))
    dates=dates[dates<=m['cutoff']]
    lookup={(r['code'],r['mode']):r for r in m['files']}
    assert set(universe.code)=={r['code'] for r in m['files']}
    dump(out/'SPEC.json',dict(period_start='2019-01-01',cutoff=m['cutoff'],stocks=len(universe),
        leader_marker='Frozen current union of original leaders and selectedTHSF10column; provenance retained; not historical point-in-time membership.',
        second_source=STRUCTURE_VERSION,min_volume_multiple=MIN_VOLUME_MULTIPLE,
        second='20daydecline<=-10%;15daybase width<=12%,netchange<=5%;base meanvolume>decline20mean;signalvolume>=1.2*basemean;rawbull body/range>=60%,upper/range<=20%.',
        onebox='Same code, overlapping known base-window time, price intersection>=80%smaller width; chronological first only.',
        observation='D1..D60 max adjusted high and min adjusted low relative strict D1 adjusted OPEN; max_drop=max(0,1-minlow/D1open); complete60 valid sessions only; no missing-entry roll forward.',
        observation_version=OBSERVATION_VERSION,
        no_parameter_optimization=True,no_account_or_order_execution=True,current_universe_retrospective_bias=True))
    events=[];coverage=[]
    for n,s in enumerate(universe.itertuples(),1):
        fs={}
        for mode in ['raw','qfq']:
            rec=lookup[(s.code,mode)];p=Path(rec['path']);assert sha(p)==rec['snapshot_sha256'],s.code
            fs[mode]=pd.read_parquet(p).set_index('date').reindex(dates)
        raw=fs['raw'];q=fs['qfq']
        ro=raw.open.to_numpy(float);rc=raw.close.to_numpy(float);rh=raw.high.to_numpy(float);rl=raw.low.to_numpy(float)
        c=q.close.to_numpy(float);o=q.open.to_numpy(float);h=q.high.to_numpy(float);l=q.low.to_numpy(float);v=raw.volume.to_numpy(float)
        valid=raw.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(v)&(v>0)
        for a in [ro,rc,rh,rl,o,c,h,l]:valid &= np.isfinite(a)&(a>0)
        ma=pd.Series(np.where(valid,c,np.nan)).rolling(60,min_periods=60).mean().to_numpy()
        f=detect(c,h,l,v,valid,ro,rc,min_volume_multiple=MIN_VOLUME_MULTIPLE)
        span=rh-rl
        body=np.divide(rc-ro,span,out=np.zeros(len(span)),where=span>0)
        upper=np.divide(rh-rc,span,out=np.ones(len(span)),where=span>0)
        second=f.selected.to_numpy()&(body>=.6-1e-10)&(upper<=.2+1e-10)&(dates>='2019-01-01')
        for group,mask in [('volume',second)]:
            for t in np.flatnonzero(mask):
                end=t+40;target=end<len(dates) and valid[end]
                row=dict(event_id=f'basebull_{s.code}_{dates[t]:%Y%m%d}',group=group,
                    code=s.code,name=s.name,is_leader=bool(s.is_leader),board=s.board,signal_date=dates[t].strftime('%Y-%m-%d'),year=int(dates[t].year),
                    is_original_leader=bool(getattr(s,'is_original_leader',s.is_leader)),
                    is_ths_leader=bool(getattr(s,'is_ths_leader',False)),leader_source=getattr(s,'leader_source','原龙头' if s.is_leader else ''),
                    signal_close=float(c[t]),raw_signal_close=float(rc[t]),
                    ma60=finite(ma[t]),close_relative_ma60=finite(c[t]/ma[t]-1),below_ma60=bool(np.isfinite(ma[t]) and c[t]<ma[t]),
                    expected_exit_date=dates[end].strftime('%Y-%m-%d') if end<len(dates) else None,
                    future_censored=end>=len(dates),**observe(o,h,l,c,ro,valid,dates,t))
                if group=='volume':
                    a=f.iloc[t]
                    row.update(**{k:float(a[k]) for k in ['decline_return','decline_mean_volume','base_mean_volume','base_decline_volume_ratio','volume_multiple','bullish_body_pct','flat_width','flat_net_change','box_high','box_low','day_change']},
                        body_range_ratio=float(body[t]),upper_shadow_ratio=float(upper[t]),breakout=bool(a.breakout),intraday_breakout=bool(a.intraday_breakout),
                        base_start=dates[t-15].strftime('%Y-%m-%d'),base_end=dates[t-1].strftime('%Y-%m-%d'),
                        price_response='放量上涨' if a.day_change>=.02 else '放量下跌' if a.day_change<=-.02 else '放量平盘',
                        raw_adjusted_return_discrepancy=bool(np.any(np.abs(rc[t-35:t+1]/rc[t-36:t]-c[t-35:t+1]/c[t-36:t])>.005)))
                events.append(row)
        idx=np.flatnonzero(valid)
        coverage.append(dict(code=s.code,name=s.name,is_leader=bool(s.is_leader),board=s.board,valid_sessions=len(idx),
            is_original_leader=bool(getattr(s,'is_original_leader',s.is_leader)),
            is_ths_leader=bool(getattr(s,'is_ths_leader',False)),leader_source=getattr(s,'leader_source','原龙头' if s.is_leader else ''),
            first=dates[idx[0]].strftime('%Y-%m-%d') if len(idx) else None,last=dates[idx[-1]].strftime('%Y-%m-%d') if len(idx) else None,
            has_cutoff_quote=bool(valid[-1]),quote_status='当日有有效报价' if valid[-1] else '当日无有效报价'))
        if n%250==0:print('Matched',n,'/',len(universe),'candidates',len(events),flush=True)
    all_events=pd.DataFrame(events)
    volume_tagged=dedup(all_events[all_events.group.eq('volume')].copy())
    volume=volume_tagged[volume_tagged.keep_first_in_box].copy()
    final=volume.sort_values(['signal_date','code'],ascending=[False,True])
    assert final.event_id.is_unique
    # Lowering the threshold preserves old candidates before chronological dedup.
    # An earlier newly qualified signal can replace the former first signal.
    old=base/'matches_v4_box_only'
    if (old/'events.parquet').exists():
        old_candidates=pd.concat([pd.read_parquet(old/'events.parquet'),pd.read_parquet(old/'duplicate_signals.parquet')])
        assert set(old_candidates.event_id).issubset(set(all_events.event_id))
    final.to_parquet(out/'events.parquet',index=False)
    volume_tagged[~volume_tagged.keep_first_in_box].to_parquet(out/'duplicate_signals.parquet',index=False)
    pd.DataFrame(coverage).to_parquet(out/'coverage.parquet',index=False)
    summary={}
    for group,g in [('volume',volume)]:
        full=g[g.peak_complete60]
        summary[group]=dict(signals=len(g),stocks=int(g.code.nunique()),leader_signals=int(g.is_leader.sum()),complete60=len(full),
            mean_peak60=finite(full.peak_return60.mean()),median_peak60=finite(full.peak_return60.median()))
    dump(out/'SUMMARY.json',dict(stocks=len(universe),leaders=int(universe.is_leader.sum()),cutoff=m['cutoff'],groups=summary,
        without_cutoff_quote=sum(not r['has_cutoff_quote'] for r in coverage),no_core_assets_modified=True))
    generation=m['cutoff']+'_'+sha(out/'events.parquet')[:14]
    bundle=dict(status='ok',generation=generation,cutoff=m['cutoff'],universe=str((base/'universe.parquet').resolve()),
        calendar=str((base/'exchange_sessions.csv').resolve()),manifest=str(mfile),manifest_sha256=sha(mfile),
        events=str((out/'events.parquet').resolve()),events_sha256=sha(out/'events.parquet'),
        coverage=str((out/'coverage.parquet').resolve()),summary=str((out/'SUMMARY.json').resolve()),
        matched_at=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
        universe_sha256=sha(base/'universe.parquet'),scope=m.get('scope','SH_SZ_MAIN_BOARD_ONLY'),modules=['volume'],
        structure_version=STRUCTURE_VERSION,min_volume_multiple=MIN_VOLUME_MULTIPLE,observation_version=OBSERVATION_VERSION,return_basis='next_session_open',
        leader_pool_manifest=m.get('leader_pool_manifest'),leader_pool_manifest_sha256=m.get('leader_pool_manifest_sha256'))
    dump(ready,bundle)
    if publish:dump(CURRENT,bundle)
    print(json.dumps(dict(generation=generation,stocks=len(universe),summary=summary),ensure_ascii=False,indent=2),flush=True)
    return bundle

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default=str(HERE/'market_wide/holdout_restricted/mainboard_v1'));parser.add_argument('--no-publish',action='store_true');args=parser.parse_args()
    build(args.base,not args.no_publish)
