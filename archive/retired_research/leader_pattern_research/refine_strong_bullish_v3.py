"""User refinement: reject bullish candles pulled well back from intraday highs."""
from pathlib import Path
import json,hashlib
import pandas as pd
import numpy as np

HERE=Path(__file__).resolve().parent
STUDY=HERE/'holdout_restricted/patterns_v1'
OUT=STUDY/'base_volume_strong_bullish_v3'
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def candle(o,h,l,c):
    span=h-l
    if not np.isfinite([o,h,l,c]).all() or span<=0 or min(o,c)<l-1e-9 or max(o,c)>h+1e-9:
        return dict(strong_bullish=False,body_range_ratio=None,upper_shadow_ratio=None,close_location=None)
    body=(c-o)/span;upper=(h-c)/span
    return dict(strong_bullish=bool(c>o and body>=.6-1e-10 and upper<=.2+1e-10),
        body_range_ratio=float(body),upper_shadow_ratio=float(upper),close_location=float((c-l)/span))

def checks():
    assert candle(10,10.85,9.95,10.8)['strong_bullish']
    assert not candle(10,11,9.9,10.2)['strong_bullish']
    assert candle(10,10.8,9.8,10.6)['strong_bullish']
    assert not candle(10,10.8001,9.8,10.6)['strong_bullish']
    assert not candle(10,10,10,10)['strong_bullish']
    assert not candle(10.8,10.9,9.9,10)['strong_bullish']
    return dict(long_upper_shadow_rejected=True,body_dominance_checked=True,
        threshold_boundary_checked=True,bearish_doji_and_zero_range_rejected=True,raw_same_day_OHLC_used=True)

def main():
    assert not OUT.exists(),'Preserve registered outputs'
    test=checks();OUT.mkdir(parents=True)
    source=STUDY/'base_volume_bullish_v2/selected_events.parquet'
    dump(OUT/'SPEC.json',dict(registered_before_outcomes=True,
        user_refinement='阳线实线，这种被压回来的不算',
        extra_rules={'close_gt_open':True,'body_over_high_low_min':.60,'upper_shadow_over_high_low_max':.20},
        numeric_origin='Operational morphology defaults announced before calculation, not chosen by future returns.',
        other_stages_unchanged=True,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        source='base_volume_bullish_v2',price_basis='Raw OHLC for signal candle geometry',
        no_absolute_minimum_body_percent=True,no_future_or_return_filter=True))
    e=pd.read_parquet(source)
    manifest=json.loads((STUDY/'inputs_daily/manifest.json').read_text(encoding='utf-8'))
    hashes={r['code']:r['snapshot_sha256'] for r in manifest['files'] if r['mode']=='raw'}
    records=[]
    for code,g in e.groupby('code'):
        p=STUDY/'inputs_daily/raw'/f'{code}.parquet';assert hashlib.sha256(p.read_bytes()).hexdigest()==hashes[code]
        q=pd.read_parquet(p).set_index('date')
        for row in g.itertuples():
            bar=q.loc[pd.Timestamp(row.signal_date)]
            f=candle(float(bar.open),float(bar.high),float(bar.low),float(bar.close))
            records.append(dict(event_id=row.event_id,**f,signal_raw_open=float(bar.open),signal_raw_high=float(bar.high),
                                signal_raw_low=float(bar.low),signal_raw_close=float(bar.close)))
    tagged=e.merge(pd.DataFrame(records),on='event_id',validate='one_to_one')
    selected=tagged[tagged.strong_bullish].copy().sort_values(['signal_date','code'],ascending=[False,True])
    selected['rule']='base_volume_strong_bullish_v3'
    tagged.to_parquet(OUT/'all_previous_candidates_tagged.parquet',index=False)
    selected.to_parquet(OUT/'selected_events.parquet',index=False)
    assert len(selected)<len(e) and len(selected)>0
    inside=selected.signal_close.between(selected.box_low,selected.box_high)
    example=tagged[tagged.code.eq('603392')&tagged.signal_date.eq('2026-01-14')]
    assert len(example)==1 and not example.strong_bullish.iloc[0]
    summary=dict(previous_candidates=len(e),signals=len(selected),stocks=int(selected.code.nunique()),
        removed=int((~tagged.strong_bullish).sum()),inside_box=int(inside.sum()),inside_stocks=int(selected.loc[inside,'code'].nunique()),
        above_box=int(selected.breakout.sum()),below_box=int((selected.signal_close<selected.box_low).sum()),checks=test,
        user_screenshot_example=example[['code','name','signal_date','signal_raw_open','signal_raw_high','signal_raw_low','signal_raw_close','body_range_ratio','upper_shadow_ratio','strong_bullish']].to_dict('records'),
        latest=selected[['code','name','signal_date','body_range_ratio','upper_shadow_ratio']].head(6).to_dict('records'))
    dump(OUT/'SUMMARY.json',summary);dump(OUT/'MINIMUM_CHECKS.json',test)
    print(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False))

if __name__=='__main__':main()
