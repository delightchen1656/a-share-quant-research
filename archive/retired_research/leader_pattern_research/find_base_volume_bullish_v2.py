"""Corrected user structure: decline -> higher-volume base -> volume bullish candle."""
from pathlib import Path
import hashlib,json
import pandas as pd
import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE/'holdout_restricted/patterns_v1'
OUT=STUDY/'base_volume_bullish_v2'
def finite(x):return float(x) if np.isfinite(x) else None
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def detect(c,h,l,v,valid,raw_o,raw_c,min_volume_multiple=2.):
    c=pd.Series(c).where(valid);h=pd.Series(h).where(valid);l=pd.Series(l).where(valid);v=pd.Series(v).where(valid)
    top=h.shift(1).rolling(15,min_periods=15).max();bottom=l.shift(1).rolling(15,min_periods=15).min()
    decline=c.shift(16)/c.shift(36)-1
    decline_v=v.shift(16).rolling(20,min_periods=20).mean()
    base_v=v.shift(1).rolling(15,min_periods=15).mean()
    base_ratio=base_v/decline_v;spike_ratio=v/base_v
    body=(pd.Series(raw_c)-pd.Series(raw_o))/pd.Series(raw_o)
    width=top/bottom-1;net=c.shift(1)/c.shift(15)-1
    full=pd.Series(valid).rolling(37,min_periods=37).sum().eq(37)
    selected=full & decline.le(-.10) & width.le(.12) & net.abs().le(.05) & base_ratio.gt(1.) & spike_ratio.ge(min_volume_multiple) & body.gt(0)
    return pd.DataFrame(dict(selected=selected,decline_return=decline,decline_mean_volume=decline_v,
        base_mean_volume=base_v,base_decline_volume_ratio=base_ratio,volume_multiple=spike_ratio,
        bullish_body_pct=body,flat_width=width,flat_net_change=net,box_high=top,box_low=bottom,
        day_change=c/c.shift(1)-1,breakout=c.gt(top),intraday_breakout=h.gt(top)))

def minimum_checks():
    c=np.full(90,20.);v=np.full(90,100.);valid=np.ones(90,bool);t=60
    c[24]=20;c[25:45]=np.linspace(19.8,17,20);c[45:60]=17;c[60]=17.1
    o=c-.02;h=np.maximum(c,o)+.1;l=np.minimum(c,o)-.1
    v[25:45]=50;v[45:60]=80;v[60]=180
    r=detect(c,h,l,v,valid,o,c);assert r.selected.iloc[t]
    assert abs(r.base_decline_volume_ratio.iloc[t]-1.6)<1e-12 and abs(r.volume_multiple.iloc[t]-2.25)<1e-12
    equal=v.copy();equal[45:60]=50;assert not detect(c,h,l,equal,valid,o,c).selected.iloc[t]
    old_quiet=v.copy();old_quiet[45:60]=40;assert not detect(c,h,l,old_quiet,valid,o,c).selected.iloc[t]
    red_o=o.copy();red_o[t]=c[t]+.1;assert not detect(c,h,l,v,valid,red_o,c).selected.iloc[t]
    doji=o.copy();doji[t]=c[t];assert not detect(c,h,l,v,valid,doji,c).selected.iloc[t]
    small=v.copy();small[t]=150;assert not detect(c,h,l,small,valid,o,c).selected.iloc[t]
    missing=valid.copy();missing[t-12]=False;assert not detect(c,h,l,v,missing,o,c).selected.iloc[t]
    future=c.copy();future[t+1:]=999;vf=v.copy();vf[t+1:]=1e9
    assert detect(future,h,l,vf,valid,o,future).selected.iloc[t]
    assert r.base_mean_volume.iloc[t]==80 and r.decline_mean_volume.iloc[t]==50
    return dict(base_mean_strictly_exceeds_decline_mean=True,old_quiet_base_rejected=True,
        bearish_and_doji_rejected=True,current_signal_not_in_baselines=True,no_future_signal_use=True,
        raw_body_ratio_not_changed_by_future_price_adjustment=True,missing_session_breaks=True)

def main():
    assert not OUT.exists(),'Keep prior registered results'
    checks=minimum_checks();OUT.mkdir(parents=True)
    dump(OUT/'SPEC.json',dict(registered_before_outcomes=True,user_corrected_definition=[
        '前段下跌结束并进入横盘','横盘整体成交量高于前段下跌过程','信号日为放量实体阳线'],
        operational_defaults=dict(decline_sessions=20,decline_return_max=-.10,base_sessions=15,
            base_high_low_width_max=.12,base_absolute_close_change_max=.05,
            base_volume_over_decline_mean_strictly_greater_than=1.,signal_volume_over_base_mean_min=2.,
            bullish_body='raw close>raw open; no extra minimum body percentage',
            no_required_shrinking_volume_within_decline=True,no_required_upward_box_breakout=True),
        baselines_exclude_signal_day=True,uses_only_completed_past_and_current_bars=True,
        decline_end='Observed narrow range used as operational transition, no future bottom confirmation.',
        fixed_universe=185,signal_period='2019-01-01 to2026-10-26',
        prior_v1_is_superseded_not_current=True,no_return_parameter_search=True,
        prices='Vendor adjusted price observation, not economic account P&L; current pool retrospective bias.'))
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(STUDY/'event_results_v1r2/exchange_sessions.csv').date))
    pool=pd.read_parquet(STUDY/'frozen_pool_185.parquet')
    manifest=json.loads((STUDY/'inputs_daily/manifest.json').read_text(encoding='utf-8'))
    hashes={(r['code'],r['mode']):r['snapshot_sha256'] for r in manifest['files']}
    events=[]
    for s in pool.itertuples():
        fs={}
        for mode in ['raw','qfq']:
            p=STUDY/'inputs_daily'/mode/f'{s.code}.parquet';assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[(s.code,mode)]
            fs[mode]=pd.read_parquet(p).set_index('date').reindex(dates)
        q=fs['qfq'];r=fs['raw'];c=q.close.to_numpy(float);h=q.high.to_numpy(float);l=q.low.to_numpy(float);v=r.volume.to_numpy(float)
        valid=r.tradestatus.astype(str).eq('1').to_numpy()&np.isfinite(v)&(v>0)
        for a in [c,h,l,q.open.to_numpy(float),r.open.to_numpy(float),r.close.to_numpy(float)]:valid &= np.isfinite(a)&(a>0)
        f=detect(c,h,l,v,valid,r.open.to_numpy(float),r.close.to_numpy(float))
        ma=pd.Series(np.where(valid,c,np.nan)).rolling(60,min_periods=60).mean().to_numpy()
        for t in np.flatnonzero(f.selected.to_numpy()&(dates>='2019-01-01')):
            a=f.iloc[t];end=t+40;stop=min(end,len(dates)-1);ok=end<len(dates) and valid[end]
            highs=np.where(valid[t+1:stop+1],h[t+1:stop+1],np.nan);lows=np.where(valid[t+1:stop+1],l[t+1:stop+1],np.nan)
            rawret=r.close.to_numpy(float)[t-35:t+1]/r.close.to_numpy(float)[t-36:t]-1
            adjret=c[t-35:t+1]/c[t-36:t]-1
            events.append(dict(event_id=f'basebull_{s.code}_{dates[t]:%Y%m%d}',rule='base_volume_bullish_v2',code=s.code,name=s.name,
                signal_date=dates[t].strftime('%Y-%m-%d'),year=int(dates[t].year),entry_date=dates[t].strftime('%Y-%m-%d'),
                signal_close=float(c[t]),adjusted_reference_price=float(c[t]),raw_reference_price=float(r.close.iloc[t]),
                ma60=finite(ma[t]),close_relative_ma60=finite(c[t]/ma[t]-1),adjusted_price_change=finite(c[end]/c[t]-1) if ok else None,
                expected_exit_date=dates[end].strftime('%Y-%m-%d') if end<len(dates) else None,
                future_censored=end>=len(dates),complete_path=bool(end<len(dates) and valid[t:end+1].all()),exit_quote_available=bool(ok),
                max_high_change=finite(np.nanmax(highs)/c[t]-1) if len(highs) and np.isfinite(highs).any() else None,
                min_low_change=finite(np.nanmin(lows)/c[t]-1) if len(lows) and np.isfinite(lows).any() else None,
                **{k:float(a[k]) for k in ['decline_return','decline_mean_volume','base_mean_volume','base_decline_volume_ratio','volume_multiple','bullish_body_pct','flat_width','flat_net_change','box_high','box_low','day_change']},
                breakout=bool(a.breakout),intraday_breakout=bool(a.intraday_breakout),
                base_start=dates[t-15].strftime('%Y-%m-%d'),base_end=dates[t-1].strftime('%Y-%m-%d'),
                decline_start=dates[t-35].strftime('%Y-%m-%d'),decline_end=dates[t-16].strftime('%Y-%m-%d'),
                price_response='放量上涨' if a.day_change>=.02 else '放量下跌' if a.day_change<=-.02 else '放量平盘',
                raw_adjusted_return_discrepancy=bool(np.any(np.abs(rawret-adjret)>.005))))
    e=pd.DataFrame(events).sort_values(['signal_date','code'],ascending=[False,True]);assert e.event_id.is_unique and len(e)
    assert e.base_decline_volume_ratio.gt(1).all() and e.bullish_body_pct.gt(0).all() and e.volume_multiple.ge(2).all()
    e.to_parquet(OUT/'selected_events.parquet',index=False)
    inside=e.signal_close.between(e.box_low,e.box_high)
    summary=dict(signals=len(e),stocks=int(e.code.nunique()),inside_box=int(inside.sum()),inside_stocks=int(e.loc[inside,'code'].nunique()),
        above_box=int(e.breakout.sum()),below_box=int((e.signal_close<e.box_low).sum()),checks=checks,
        latest=e[['code','name','signal_date','base_decline_volume_ratio','volume_multiple','bullish_body_pct']].head(8).to_dict('records'))
    dump(OUT/'SUMMARY.json',summary);dump(OUT/'MINIMUM_CHECKS.json',checks)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
