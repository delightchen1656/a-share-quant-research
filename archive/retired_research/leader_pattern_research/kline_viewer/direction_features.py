"""Frozen signal-time feature transforms; no training or future labels."""

import numpy as np

import pandas as pd

ALL_FEATURES=['decline_return', 'base_return', 'base_width', 'base_volume_ratio', 'signal_volume_ratio', 'base_bull_max_to_signal', 'base_bear_max_to_signal', 'base_up_volume_share', 'base_up_day_share', 'base_volume_cv', 'base_late_volume_ratio', 'base_range_compression', 'signal_body_ratio', 'signal_upper_shadow', 'signal_return', 'signal_gap', 'signal_box_position', 'signal_range_expansion', 'dist_ma20', 'dist_ma60', 'ma20_slope', 'ma60_slope', 'ma20_ma60_gap', 'pre_return60', 'pre_return120', 'dist_high120', 'dist_low120', 'atr14_pct', 'volatility20', 'base_below_ma60_share', 'log_amount20', 'gap_up_count', 'gap_down_count', 'gap_unfilled_count', 'bull_bear_max_ratio', 'bull_volume_excess', 'base_return_in_width', 'signal_volume_efficiency', 'late_volume_compression', 'ma20_distance_atr', 'pre120_vol_scaled']

def ratio(a,b):return float(a/b) if np.isfinite(a) and np.isfinite(b) and b!=0 else np.nan

def features(q,r,t):
    # Truncate FIRST. The function cannot consume a future bar even accidentally.
    q=q.iloc[:t+1];r=r.iloc[:t+1];v=pd.to_numeric(r.volume,errors='coerce')
    c=q.close.astype(float);h=q.high.astype(float);l=q.low.astype(float);o=q.open.astype(float)
    base=slice(t-15,t);decl=slice(t-35,t-15)
    b=q.iloc[base];rv=r.iloc[base];bv=v.iloc[base];up=rv.close>rv.open
    span=float(r.high.iloc[t]-r.low.iloc[t]);raw_body=float(r.close.iloc[t]-r.open.iloc[t])
    ma20=c.rolling(20,min_periods=20).mean();ma60=c.rolling(60,min_periods=60).mean()
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    def width(frame):return ratio(frame.high.max(),frame.low.min())-1
    result=dict(decline_return=ratio(c.iloc[t-16],c.iloc[t-36])-1,base_return=ratio(c.iloc[t-1],c.iloc[t-15])-1,
        base_width=width(b),base_volume_ratio=ratio(bv.mean(),v.iloc[decl].mean()),signal_volume_ratio=ratio(v.iloc[t],bv.mean()),
        base_bull_max_to_signal=ratio(bv[up].max() if up.any() else 0,v.iloc[t]),
        base_bear_max_to_signal=ratio(bv[~up].max() if (~up).any() else 0,v.iloc[t]),
        base_up_volume_share=ratio(bv[up].sum(),bv.sum()),base_up_day_share=float(up.mean()),base_volume_cv=ratio(bv.std(),bv.mean()),
        base_late_volume_ratio=ratio(bv.iloc[-7:].mean(),bv.iloc[:8].mean()),base_range_compression=ratio(width(b.iloc[-5:]),width(b.iloc[:5])),
        signal_body_ratio=ratio(raw_body,span),signal_upper_shadow=ratio(r.high.iloc[t]-r.close.iloc[t],span),
        signal_return=ratio(r.close.iloc[t],r.preclose.iloc[t])-1,signal_gap=ratio(r.open.iloc[t],r.preclose.iloc[t])-1,
        signal_box_position=ratio(c.iloc[t]-b.low.min(),b.high.max()-b.low.min()),
        signal_range_expansion=ratio(h.iloc[t]-l.iloc[t],(b.high-b.low).mean()),
        dist_ma20=ratio(c.iloc[t],ma20.iloc[t])-1,dist_ma60=ratio(c.iloc[t],ma60.iloc[t])-1,
        ma20_slope=ratio(ma20.iloc[t],ma20.iloc[t-5])-1,ma60_slope=ratio(ma60.iloc[t],ma60.iloc[t-10])-1,
        ma20_ma60_gap=ratio(ma20.iloc[t],ma60.iloc[t])-1,pre_return60=ratio(c.iloc[t-1],c.iloc[t-61])-1,
        pre_return120=ratio(c.iloc[t-1],c.iloc[t-121])-1,
        dist_high120=ratio(c.iloc[t],h.iloc[max(0,t-120):t].max())-1,
        dist_low120=ratio(c.iloc[t],l.iloc[max(0,t-120):t].min())-1,
        atr14_pct=ratio(tr.iloc[t-13:t+1].mean(),c.iloc[t]),volatility20=float(c.pct_change(fill_method=None).iloc[t-20:t].std()),
        base_below_ma60_share=float((c.iloc[base]<ma60.iloc[base]).mean()),
        log_amount20=float(np.log1p(pd.to_numeric(r.amount,errors='coerce').iloc[t-20:t].mean())))
    gu=gd=unfilled=0
    for j in range(t-14,t):
        if l.iloc[j]>h.iloc[j-1]+1e-8 and r.low.iloc[j]>r.high.iloc[j-1]+1e-8:
            gu+=1;unfilled+=int(l.iloc[j:t+1].min()>h.iloc[j-1]+1e-8)
        if h.iloc[j]<l.iloc[j-1]-1e-8 and r.high.iloc[j]<r.low.iloc[j-1]-1e-8:
            gd+=1;unfilled+=int(h.iloc[j:t+1].max()<l.iloc[j-1]-1e-8)
    result.update(gap_up_count=gu,gap_down_count=gd,gap_unfilled_count=unfilled)
    return {k:float(x) if np.isfinite(x) else np.nan for k,x in result.items()}

DERIVED=['bull_bear_max_ratio','bull_volume_excess','base_return_in_width','signal_volume_efficiency',
         'late_volume_compression','ma20_distance_atr','pre120_vol_scaled']

def enrich(data):
    d=data.copy()
    d['bull_bear_max_ratio']=d.base_bull_max_to_signal/d.base_bear_max_to_signal
    d['bull_volume_excess']=d.base_up_volume_share-d.base_up_day_share
    d['base_return_in_width']=d.base_return/d.base_width
    d['signal_volume_efficiency']=d.signal_volume_ratio/d.signal_range_expansion
    d['late_volume_compression']=d.base_late_volume_ratio/d.base_range_compression
    d['ma20_distance_atr']=d.dist_ma20/d.atr14_pct
    d['pre120_vol_scaled']=d.pre_return120/(d.volatility20*np.sqrt(120))
    d[ALL_FEATURES]=d[ALL_FEATURES].replace([np.inf,-np.inf],np.nan)
    return d
