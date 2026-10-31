"""Chronological, future-blind deduplication: earliest qualified signal per base box."""
from pathlib import Path
import hashlib,json
import pandas as pd

HERE=Path(__file__).resolve().parent;STUDY=HERE/'holdout_restricted/patterns_v1'
OUT=STUDY/'base_volume_strong_bullish_one_box_v4'
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def overlap_ratio(a_low,a_high,b_low,b_high):
    overlap=max(0.,min(a_high,b_high)-max(a_low,b_low));smaller=min(a_high-a_low,b_high-b_low)
    if smaller<=1e-12:return 1. if abs(a_low-b_low)<=1e-10 and abs(a_high-b_high)<=1e-10 else 0.
    return overlap/smaller

def dedup(frame):
    annotations=[]
    for code,g in frame.sort_values(['code','signal_date','event_id']).groupby('code',sort=False):
        boxes=[]
        for r in g.itertuples():
            start=pd.Timestamp(r.base_start);end=pd.Timestamp(r.base_end);match=None;ratio=None
            for b in boxes:
                if start>b['end'] or end<b['start']:continue
                score=overlap_ratio(float(r.box_low),float(r.box_high),b['low'],b['high'])
                if score>=.80-1e-10:match=b;ratio=score;break
            keep=match is None
            if keep:
                match=dict(id=f'box_{code}_{r.signal_date.replace("-","")}',first=r.event_id,first_date=r.signal_date,
                    start=start,end=end,low=float(r.box_low),high=float(r.box_high))
                boxes.append(match);ratio=1.
            else:
                # Extend known temporal coverage only; frozen first-box prices never drift.
                match['end']=max(match['end'],end)
            annotations.append(dict(event_id=r.event_id,box_id=match['id'],keep_first_in_box=keep,
                first_signal_id=match['first'],first_signal_date=match['first_date'],
                duplicate_of=None if keep else match['first'],box_price_overlap_ratio=float(ratio)))
    return frame.merge(pd.DataFrame(annotations),on='event_id',validate='one_to_one')

def checks():
    def row(event,date,start,end,low=10.,high=11.,code='A'):
        return dict(event_id=event,code=code,signal_date=date,base_start=start,base_end=end,box_low=low,box_high=high)
    sample=pd.DataFrame([
        row('later','2020-12-18','2020-11-27','2020-12-17',10.,11.1),
        row('first','2020-12-17','2020-11-26','2020-12-16'),
        row('new_price','2020-12-21','2020-11-30','2020-12-18',15.,16.),
        row('new_time','2021-02-01','2021-01-01','2021-01-29'),
        row('other_stock','2020-12-18','2020-11-27','2020-12-17',code='B')])
    a=dedup(sample).set_index('event_id')
    assert a.loc['first','keep_first_in_box'] and not a.loc['later','keep_first_in_box']
    assert a.loc['later','duplicate_of']=='first'
    for k in ['new_price','new_time','other_stock']:assert a.loc[k,'keep_first_in_box']
    with_outcomes=sample.copy();with_outcomes['future_return']=[999,-999,0,0,0]
    b=dedup(with_outcomes).set_index('event_id')
    assert a.keep_first_in_box.equals(b.keep_first_in_box)
    assert abs(overlap_ratio(10,11,10.2,11.2)-.8)<1e-10
    return dict(chronologically_earliest_not_input_order=True,different_stocks_separate=True,
        distinct_time_or_price_boxes_separate=True,future_returns_cannot_affect_choice=True,
        first_box_price_anchor_never_moved=True)

def main():
    assert not OUT.exists(),'Keep historical versions'
    tests=checks();OUT.mkdir(parents=True)
    source=STUDY/'base_volume_strong_bullish_v3/selected_events.parquet'
    dump(OUT/'SPEC.json',dict(registered_before_new_summary=True,user_request='同一个箱体只给一个信号，以前一个为准',
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        same_box='Same stock; overlapping known15day base-window intervals; intersection of price ranges >=80% of narrower range.',
        threshold_origin='Operational box identity default; not optimized by returns.',
        processing='Chronological order, earliest qualified signal anchors fixed price bounds; duplicate windows may extend known time coverage, not price bounds.',
        no_future_representative_selection=True,other_structure_filters_and_D1_D60_metric_unchanged=True,
        applies_only_structure2=True))
    tagged=dedup(pd.read_parquet(source));kept=tagged[tagged.keep_first_in_box].copy().sort_values(['signal_date','code'],ascending=[False,True])
    kept['rule']='base_volume_strong_bullish_one_box_v4'
    removed=tagged[~tagged.keep_first_in_box].copy()
    assert kept.box_id.is_unique and kept.event_id.is_unique
    tagged.to_parquet(OUT/'all_candidates_tagged.parquet',index=False)
    kept.to_parquet(OUT/'selected_events.parquet',index=False)
    removed.to_parquet(OUT/'duplicate_signals.parquet',index=False)
    # Current user-supplied example must keep17Dec and suppress18Dec regardless of later performance.
    assert 'basebull_603728_20201217' in set(kept.event_id)
    assert 'basebull_603728_20201218' not in set(kept.event_id)
    metrics=pd.read_parquet(STUDY/'future60_high_v1/event_metrics.parquet')
    full=kept[['event_id']].merge(metrics,on='event_id',validate='one_to_one');complete=full[full.peak_complete60]
    inside=kept.signal_close.between(kept.box_low,kept.box_high)
    summary=dict(before=len(tagged),signals=len(kept),stocks=int(kept.code.nunique()),removed=len(removed),
        inside_box=int(inside.sum()),above_box=int(kept.breakout.sum()),below_box=int((kept.signal_close<kept.box_low).sum()),
        complete60=len(complete),unfinished=int(full.peak_status60.eq('未满60日').sum()),missing=int(full.peak_status60.eq('观察期缺价').sum()),
        mean_peak60=float(complete.peak_return60.mean()),median_peak60=float(complete.peak_return60.median()),
        mean_peak40_same_cohort=float(complete.peak40_same_cohort.mean()),
        removed_examples=removed[['code','name','signal_date','first_signal_date','duplicate_of','box_price_overlap_ratio']].to_dict('records'),checks=tests)
    dump(OUT/'SUMMARY.json',summary);dump(OUT/'MINIMUM_CHECKS.json',tests)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
