"""User-requested quiet decline -> narrow base -> volume expansion, one fixed specification."""
from pathlib import Path
import json,hashlib,datetime
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
STUDY=HERE/'holdout_restricted/patterns_v1'
OUT=STUDY/'quiet_base_volume_v1'

def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def finite(x):return float(x) if np.isfinite(x) else None

def detect(c,h,l,v,valid):
    """t is completed volume-release day; baseline and box always exclude t."""
    c=pd.Series(c).where(valid);h=pd.Series(h).where(valid);l=pd.Series(l).where(valid);v=pd.Series(v).where(valid)
    high=h.shift(1).rolling(15,min_periods=15).max()
    low=l.shift(1).rolling(15,min_periods=15).min()
    width=high/low-1
    flat_return=c.shift(1)/c.shift(15)-1
    # Base=t-15..t-1; decline=t-35..t-16; reference close=t-36.
    decline=c.shift(16)/c.shift(36)-1
    early_v=v.shift(26).rolling(10,min_periods=10).mean()
    late_v=v.shift(16).rolling(10,min_periods=10).mean()
    shrink=late_v/early_v
    base_v=v.shift(1).rolling(15,min_periods=15).mean()
    multiple=v/base_v
    full=pd.Series(valid).rolling(37,min_periods=37).sum().eq(37)
    # Keep the base quiet relative to the first half of its preceding decline.
    mask=full & decline.le(-.10) & shrink.le(.80) & width.le(.12) & flat_return.abs().le(.05) & base_v.le(early_v) & multiple.ge(2.)
    response=c/c.shift(1)-1
    return pd.DataFrame(dict(selected=mask,decline_return=decline,decline_volume_ratio=shrink,
        flat_width=width,flat_net_change=flat_return,volume_multiple=multiple,box_high=high,box_low=low,
        base_mean_volume=base_v,decline_first10_mean_volume=early_v,
        breakout=c.gt(high),intraday_breakout=h.gt(high),day_change=response))

def minimum_checks():
    c=np.full(85,20.);h=c+.10;l=c-.10;v=np.full(85,100.);valid=np.ones(85,bool);t=60
    c[24]=20.;c[25:45]=np.linspace(19.8,17.,20);c[45:60]=17.;c[60]=17.1
    h=c+.1;l=c-.1;v[25:35]=100.;v[35:45]=60.;v[45:60]=50.;v[60]=130.
    r=detect(c,h,l,v,valid);assert r.selected.iloc[t]
    assert not r.breakout.iloc[t] # equality to old box high is not a strict breakout
    assert abs(r.volume_multiple.iloc[t]-2.6)<1e-12
    # Current huge volume must not enter its own denominator.
    assert r.base_mean_volume.iloc[t]==50
    cc=c.copy();cc[t+1:]=10000.;vv=v.copy();vv[t+1:]=1e9
    assert detect(cc,h,l,vv,valid).selected.iloc[t]==r.selected.iloc[t]
    v_bad=v.copy();v_bad[t]=75.;assert not detect(c,h,l,v_bad,valid).selected.iloc[t]
    missing=valid.copy();missing[t-12]=False;assert not detect(c,h,l,v,missing).selected.iloc[t]
    flatbad=c.copy();flatbad[45:60]=np.linspace(17,19,15)
    assert not detect(flatbad,np.maximum(h,flatbad+.1),l,v,valid).selected.iloc[t]
    return dict(baseline_excludes_current=True,breakout_not_required=True,no_future_signal_use=True,
        volume_and_base_conditions=True,missing_sessions_break=True,strict_breakout_boundary=True)

def main():
    assert not OUT.exists(),'Keep registered outcomes; do not overwrite or tune in place'
    checks=minimum_checks();OUT.mkdir(parents=True)
    dump(OUT/'SPEC.json',dict(registered_before_outcomes=True,user_confirmation='不必突破，先找横盘里的放量',
        scope='Same185frozen current stocks; daily snapshots2018-2026-10-26; signal dates2019onward.',
        numeric_origin='Operational first-pass defaults announced before outcomes; not optimized thresholds.',
        decline='20session close return<=-10%, ending immediately before base; last10meanvolume<=80%first10meanvolume.',
        base='Previous15sessions high/low-1<=12%; abs(lastclose/firstclose-1)<=5%; mean volume<=first10meanvolume of prior decline.',
        signal='Completed day volume>=2*previous15session base mean; no close direction or box breakout requirement.',
        breakout='Record strict close>prior base high separately; never use it as the required trigger.',
        all37sessions_valid=True,returns='Separate forward40session vendor-adjusted price observation, not account or real execution P&L.',
        pool_bias='Retrospective current universe; not a historical point-in-time pool or blind test.',
        parameters_not_selected_by_returns=True))
    calendar=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(STUDY/'event_results_v1r2/exchange_sessions.csv').date))
    pool=pd.read_parquet(STUDY/'frozen_pool_185.parquet')
    m=json.loads((STUDY/'inputs_daily/manifest.json').read_text(encoding='utf-8'))
    hashes={(r['code'],r['mode']):r['snapshot_sha256'] for r in m['files']}
    events=[]
    for stock in pool.itertuples():
        frames={}
        for mode in ['raw','qfq']:
            p=STUDY/'inputs_daily'/mode/f'{stock.code}.parquet'
            assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[(stock.code,mode)]
            frames[mode]=pd.read_parquet(p).set_index('date').reindex(calendar)
        q=frames['qfq'];raw=frames['raw']
        c=q.close.to_numpy(float);h=q.high.to_numpy(float);l=q.low.to_numpy(float);v=raw.volume.to_numpy(float)
        valid=raw.tradestatus.astype(str).eq('1').to_numpy() & np.isfinite(v)&(v>0)
        for arr in [c,h,l,q.open.to_numpy(float)]:valid &= np.isfinite(arr)&(arr>0)
        features=detect(c,h,l,v,valid)
        ma60=pd.Series(np.where(valid,c,np.nan)).rolling(60,min_periods=60).mean().to_numpy()
        for t in np.flatnonzero(features.selected.to_numpy() & (calendar>='2019-01-01')):
            f=features.iloc[t];end=t+40;last=min(end,len(calendar)-1)
            complete=end<len(calendar) and valid[t:end+1].all()
            target_ok=end<len(calendar) and valid[end]
            highs=np.where(valid[t+1:last+1],h[t+1:last+1],np.nan)
            lows=np.where(valid[t+1:last+1],l[t+1:last+1],np.nan)
            raw_return=raw.close.to_numpy(float)[t-35:t+1]/raw.close.to_numpy(float)[t-36:t]-1
            adj_return=c[t-35:t+1]/c[t-36:t]-1
            events.append(dict(event_id=f'volume_{stock.code}_{calendar[t]:%Y%m%d}',rule='quiet_base_volume',code=stock.code,name=stock.name,
                signal_date=calendar[t].strftime('%Y-%m-%d'),year=int(calendar[t].year),entry_date=calendar[t].strftime('%Y-%m-%d'),
                signal_close=float(c[t]),adjusted_reference_price=float(c[t]),raw_reference_price=float(raw.close.iloc[t]),
                ma60=finite(ma60[t]),close_relative_ma60=finite(c[t]/ma60[t]-1),
                adjusted_price_change=finite(c[end]/c[t]-1) if target_ok else None,
                expected_exit_date=calendar[end].strftime('%Y-%m-%d') if end<len(calendar) else None,
                future_censored=end>=len(calendar),complete_path=bool(complete),exit_quote_available=bool(target_ok),
                max_high_change=finite(np.nanmax(highs)/c[t]-1) if len(highs) and np.isfinite(highs).any() else None,
                min_low_change=finite(np.nanmin(lows)/c[t]-1) if len(lows) and np.isfinite(lows).any() else None,
                **{k:float(f[k]) for k in ['decline_return','decline_volume_ratio','flat_width','flat_net_change','volume_multiple','box_high','box_low','base_mean_volume','day_change']},
                breakout=bool(f.breakout),intraday_breakout=bool(f.intraday_breakout),
                base_start=calendar[t-15].strftime('%Y-%m-%d'),base_end=calendar[t-1].strftime('%Y-%m-%d'),
                decline_start=calendar[t-35].strftime('%Y-%m-%d'),decline_end=calendar[t-16].strftime('%Y-%m-%d'),
                price_response='放量上涨' if f.day_change>=.02 else '放量下跌' if f.day_change<=-.02 else '放量平盘',
                raw_adjusted_return_discrepancy=bool(np.any(np.abs(raw_return-adj_return)>.005))))
    e=pd.DataFrame(events);assert len(e)>0 and e.event_id.is_unique
    e=e.sort_values(['signal_date','code'],ascending=[False,True]);e.to_parquet(OUT/'selected_events.parquet',index=False)
    summary=dict(signals=len(e),stocks=int(e.code.nunique()),breakout=int(e.breakout.sum()),no_breakout=int((~e.breakout).sum()),
        price_response=e.price_response.value_counts().to_dict(),
        by_year={str(k):int(v) for k,v in e.year.value_counts().sort_index().items()},
        latest=e[['event_id','code','name','signal_date','volume_multiple','decline_return','flat_width','breakout','price_response']].head(12).to_dict('records'),
        historical_observations_only=True,checks=checks)
    dump(OUT/'SUMMARY.json',summary);dump(OUT/'MINIMUM_CHECKS.json',checks)
    print(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
