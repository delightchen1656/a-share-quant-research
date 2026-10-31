from pathlib import Path
import json,hashlib
import pandas as pd
import requests
from refresh_gold_recent import aligned
ROOT=Path(__file__).resolve().parent.parent/'K线数据/黄金'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
link=json.loads((ROOT/'CURRENT.json').read_text(encoding='utf8'));p=ROOT/link['manifest'];assert sha(p)==link['sha256'];m=json.loads(p.read_text(encoding='utf8'));data=ROOT/m['data_path'];assert sha(data)==m['data_sha256'];frame=pd.read_parquet(data)
ext=m['extensions'][-1];rp=ROOT/ext['source_file'];assert sha(rp)==ext['source_sha256'];raw=json.loads(rp.read_text(encoding='utf8'))['response']
assert raw['symbol']=='XAU-USD-SPOT'and raw['interval']=='1d'
lookup={pd.Timestamp(b['bar_start']).strftime('%Y-%m-%d'):b for b in raw['bars']}
for day in ext['added_dates']:
    row=frame.set_index('date').loc[day];b=lookup[day]
    assert b['is_closed']is True and aligned(b['bar_start'])
    for c in ['open','high','low','close']:assert row[c]==float(b[c])
    assert row.source=='Gold Price API 现货' and pd.isna(row.quote_minutes) and pd.isna(row.first_utc)and pd.isna(row.last_utc)
assert aligned('2026-10-26T00:00:00Z')and aligned('2026-10-29T00:00:00Z')
assert not aligned('2026-10-23T00:00:00Z')and not aligned('2026-10-25T00:00:00Z')and not aligned('2027-03-28T00:00:00Z')and not aligned('2027-06-01T00:00:00Z')
baseline=ROOT/'snapshots/20261030T041932Z/daily.parquet';old=pd.read_parquet(baseline)
pd.testing.assert_frame_equal(old[['date','open','high','low','close']].reset_index(drop=True),frame.loc[frame.date.isin(old.date),['date','open','high','low','close']].reset_index(drop=True))
api=requests.get('http://127.0.0.1:8766/api/gold/history',timeout=15);api.raise_for_status();a=api.json();assert a['last']==m['last']and a['fields'][-1]=='source'
assert a['bars'][-1][12]=='Gold Price API 现货'and a['bars'][0][12]=='HistData BID'
assert frame.date.max()<pd.Timestamp.now(tz='Europe/London').strftime('%Y-%m-%d')
assert ext['prices_shifted_or_scaled']is False
result=dict(passed=True,last_complete_date=m['last'],bars=len(frame),added_dates=ext['added_dates'],source_ohlc_matched_exactly=True,history_unchanged=True,London_GMT_acceptance_and_BST_rejection=True,current_day_not_imported=True,missing_Sunday_not_invented=ext['native_missing_dates'],overlap_days=len(ext['overlap_UTC_days']),max_close_difference_pct=ext['max_absolute_close_difference_fraction']*100,per_bar_provenance_verified=True)
(ROOT/'RECENT_VALIDATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
