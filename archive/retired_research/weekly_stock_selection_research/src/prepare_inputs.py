from concurrent.futures import ThreadPoolExecutor
import sys
import json
import datetime
import numpy as np
import pandas as pd
from common import BASE,ROOT,AUDIT,SPEC,sha,dump


def main():
    reg=json.loads((AUDIT/'registration.json').read_text(encoding='utf-8'))
    assert sha(AUDIT/'spec.json')==reg['spec_sha256']
    dest=BASE/'inputs_pre2025/kline_dev_v1'
    assert not (dest/'manifest.json').exists(),'Existing snapshot retained'
    dest.mkdir(parents=True,exist_ok=True)
    src=ROOT/'sh_sz_market_research/data_pipeline/data/raw'
    files=sorted(src.rglob('*.parquet'))
    def worker(path):
        symbol=path.stem
        if symbol[:3] not in SPEC['pool']['prefixes']:
            return None
        before=sha(path)
        frame=pd.read_parquet(path,filters=[('date','<=',pd.Timestamp('2023-12-31')),('date','>=',pd.Timestamp('2018-01-01'))])
        assert before==sha(path),'Source changed during snapshot'
        if frame.empty:
            return dict(symbol=symbol,rows=0,source_sha256=before,observed_pre2024=False)
        frame['date']=pd.to_datetime(frame.date)
        assert frame.date.is_monotonic_increasing and not frame.date.duplicated().any()
        assert frame.date.between('2018-01-01','2023-12-31').all()
        target=dest/f'{symbol}.parquet'
        frame.to_parquet(target,index=False)
        return dict(symbol=symbol,rows=len(frame),source_sha256=before,snapshot_sha256=sha(target),
                    snapshot_file=target.name,first_date=str(frame.date.min().date()),last_date=str(frame.date.max().date()),observed_pre2024=True)
    records=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,item in enumerate(pool.map(worker,files),1):
            if item:
                records.append(item)
            if i%500==0:
                print(f'snapshot {i}/{len(files)}',flush=True)
    calendar_src=ROOT/'sh_sz_market_research/data_pipeline/data/metadata/trade_calendar_20261026.csv'
    calendar=pd.read_csv(calendar_src,parse_dates=['calendar_date'])
    calendar=calendar.loc[calendar.calendar_date.between('2018-01-01','2023-12-31')].copy()
    dest_calendar=BASE/'inputs_pre2025/calendar_dev_v1.parquet'
    calendar.to_parquet(dest_calendar,index=False)
    # Independent index source collection, no reuse of old research snapshots.
    sys.path.insert(0,str(ROOT))
    from tools import daily_market_update as updater
    updater.safe_login()
    try:
        index=updater.query_history('sh.000001','2017-12-29','2023-12-31','3')
    finally:
        updater.bs.logout()
    index['date']=pd.to_datetime(index.date)
    for column in ['open','high','low','close','preclose','volume','amount','pctChg']:
        index[column]=pd.to_numeric(index[column],errors='raise')
    index_path=BASE/'inputs_pre2025/sse_dev_v1.parquet'
    index.to_parquet(index_path,index=False)
    days=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
    assert pd.DatetimeIndex(index.loc[index.date.ge('2018-01-01'),'date']).equals(days)
    manifest=dict(boundary_version='public-pre2025-v2',data_start='2018-01-01',data_end='2023-12-31',
                  source_currently_committed=True,source_may_have_later_vendor_revisions=True,
                  current_status_or_delisting_metadata_used_for_past_pool=False,
                  no_post2023_rows_loaded_into_frames=True,source_files=len(files),
                  files=records,nonempty_files=sum(r['rows']>0 for r in records),rows=sum(r['rows'] for r in records),
                  calendar_sha256=sha(dest_calendar),index_sha256=sha(index_path),
                  stock_universe_is_observed_not_complete=True,created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    dump(dest/'manifest.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
