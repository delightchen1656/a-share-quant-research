"""Root-only export of an explicit pre-2025 whitelist; downstream reads this directory only."""
from pathlib import Path
import hashlib,json
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
INPUT=HERE/'inputs_pre2025'
BOUNDARY='2024-12-31'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
def main():
    assert not INPUT.exists(),'Frozen whitelist must not be overwritten'
    source=ROOT/'leader_pattern_research/market_wide/holdout_restricted/CURRENT.json'
    bundle=json.loads(source.read_text(encoding='utf-8'))
    assert bundle['status']=='ok' and bundle['scope']=='SH_SZ_MAIN_BOARD_ONLY'
    for key in ['events','manifest','universe']:assert sha(bundle[key])==bundle[key+'_sha256']
    manifest=json.loads(Path(bundle['manifest']).read_text(encoding='utf-8'))
    columns=['event_id','code','name','signal_date','year','is_leader','base_start','base_end','box_low','box_high']
    e=pd.read_parquet(bundle['events'],columns=columns)
    e=e[e.signal_date.le(BOUNDARY)].sort_values(['signal_date','code'])
    assert e.code.str.match(r'^(600|601|603|605|000|001|002|003)\d{3}$').all()
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(bundle['calendar']).date));dates=dates[dates<=BOUNDARY]
    INPUT.mkdir();e.to_parquet(INPUT/'events.parquet',index=False)
    pd.DataFrame({'date':dates}).to_parquet(INPUT/'calendar.parquet',index=False)
    needed=set(e.code);files=[]
    for rec in manifest['files']:
        if rec['code'] not in needed:continue
        path=Path(rec['path']);assert sha(path)==rec['snapshot_sha256']
        f=pd.read_parquet(path);f=f[pd.to_datetime(f.date).le(BOUNDARY)]
        allowed=['date','open','high','low','close','preclose','volume','amount','pctChg','tradestatus','isST']
        f=f[[c for c in allowed if c in f]]
        target=INPUT/rec['mode']/(rec['code']+'.parquet');target.parent.mkdir(exist_ok=True)
        f.to_parquet(target,index=False)
        files.append(dict(code=rec['code'],mode=rec['mode'],relative_path=str(target.relative_to(INPUT)),sha256=sha(target)))
        if len(files)%300==0:print('Frozen',len(files),'files',flush=True)
    dump(INPUT/'MANIFEST.json',dict(boundary=BOUNDARY,scope='SH_SZ_MAIN_BOARD_ONLY; ALL box events, no leader or quality filter',
        events_sha256=sha(INPUT/'events.parquet'),calendar_sha256=sha(INPUT/'calendar.parquet'),files=files,
        source_events_sha256=bundle['events_sha256'],events=len(e),stocks=e.code.nunique(),
        allowed_event_columns=columns,raw_future_outcome_fields_exported=False,current_universe_retrospective_bias=True,
        context_already_contains_later_results=True,not_a_clean_isolated_agent=True,not_a_fresh_blind_test=True))
    print(json.dumps(dict(events=len(e),stocks=e.code.nunique(),years=e.year.value_counts().sort_index().to_dict()),ensure_ascii=False))
if __name__=='__main__':main()
