"""Freeze only pre-2025 price paths and signal-time fields for exploratory exit study."""
from pathlib import Path
import json,hashlib,sys
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1];HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'leader_pattern_research'))
from box_gap_scan import read_or_scan

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def main():
    area=HERE/'inputs_pre2025';assert not area.exists(),'Keep frozen inputs immutable'
    source=ROOT/'leader_pattern_research/market_wide/holdout_restricted/CURRENT.json';b=json.loads(source.read_text(encoding='utf-8'))
    assert sha(b['events'])==b['events_sha256'] and sha(b['manifest'])==b['manifest_sha256']
    manifest=json.loads(Path(b['manifest']).read_text(encoding='utf-8'))
    # Never import future peak/trough outcomes into research inputs.
    cols=['event_id','code','name','signal_date','year','is_leader','leader_source','box_low','box_high','base_start','base_end','signal_close']
    e=pd.read_parquet(b['events'],columns=cols);e=e[e.signal_date.le('2024-12-31')]
    gaps=pd.DataFrame(read_or_scan(b))[['event_id','gap_down_count','gap_unfilled_count']]
    e=e.merge(gaps,on='event_id',validate='one_to_one');e=e[e.is_leader&e.gap_down_count.eq(0)&e.gap_unfilled_count.eq(0)].copy()
    area.mkdir(parents=True);e.to_parquet(area/'events.parquet',index=False)
    dates=pd.to_datetime(pd.read_csv(b['calendar']).date);dates=dates[dates<='2024-12-31']
    pd.DataFrame({'date':dates}).to_json(area/'calendar.json',orient='records',date_format='iso')
    records=[]
    for r in manifest['files']:
        if r['code'] not in set(e.code):continue
        assert sha(r['path'])==r['snapshot_sha256']
        f=pd.read_parquet(r['path']);f=f[pd.to_datetime(f.date).le('2024-12-31')]
        target=area/r['mode']/f"{r['code']}.parquet";target.parent.mkdir(exist_ok=True)
        f.to_parquet(target,index=False)
        records.append(dict(code=r['code'],mode=r['mode'],path=str(target.resolve()),sha256=sha(target),
            first=str(f.date.min()),last=str(f.date.max()),source_snapshot_sha256=r['snapshot_sha256']))
    dump(area/'MANIFEST.json',dict(boundary='through 2024-12-31 only',events_sha256=sha(area/'events.parquet'),calendar_sha256=sha(area/'calendar.json'),
        source_events_sha256=b['events_sha256'],source_manifest_sha256=b['manifest_sha256'],files=records,
        signals=len(e),stocks=int(e.code.nunique()),no_future_outcome_fields=True,
        current_membership_retrospective_bias=True,previous_descriptive_results_seen=True,not_a_fresh_blind_test=True))
    print(json.dumps(dict(signals=len(e),stocks=int(e.code.nunique()),by_year=e.year.value_counts().sort_index().to_dict()),ensure_ascii=False))

if __name__=='__main__':main()
