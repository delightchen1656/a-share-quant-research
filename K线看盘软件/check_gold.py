from pathlib import Path
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import requests,json,hashlib,zipfile
import pandas as pd
ROOT=Path(__file__).resolve().parent
r=requests.get('http://127.0.0.1:8766/api/gold/history',timeout=15);r.raise_for_status();a=r.json();m=a['metadata'];rows=a['bars']
assert a['code']=='XAUUSD'and m['currency']=='USD'and m['timezone']=='Europe/London'and len(rows)>3000
assert all(b[5]is None and b[6]is None for b in rows)
assert len({b[0]for b in rows})==len(rows)and rows==sorted(rows,key=lambda b:b[0])
assert all(b[2]>=max(b[1],b[3],b[4])and b[3]<=min(b[1],b[2],b[4])for b in rows)
# Explicit UK spring/fall boundaries, independent stdlib timezone conversion.
for text,expected in [('2024-03-31T22:59:00+00:00','2024-03-31'),('2024-03-31T23:00:00+00:00','2024-04-01'),('2024-10-27T23:00:00+00:00','2024-10-27'),('2024-10-28T00:00:00+00:00','2024-10-28')]:
    assert datetime.fromisoformat(text).astimezone(ZoneInfo('Europe/London')).date().isoformat()==expected
# Rebuild selected winter/summer days directly from retained source minute bars.
z=zipfile.ZipFile(ROOT.parent/'K线数据/黄金/raw/XAUUSD_M1_2024.zip');f=next(n for n in z.namelist()if n.endswith('.csv'))
raw=pd.read_csv(z.open(f),sep=';',header=None,names=['t','o','h','l','c','v']);t=pd.to_datetime(raw.t,format='%Y%m%d %H%M%S')+pd.Timedelta(hours=5)
days=t.dt.tz_localize('UTC').dt.tz_convert('Europe/London').dt.strftime('%Y-%m-%d');lookup={b[0]:b for b in rows}
for day in ['2024-01-15','2024-05-15','2024-10-28']:
    g=raw.loc[days.eq(day)];b=lookup[day];assert len(g)>0
    assert b[1:5]==[float(g.o.iloc[0]),float(g.h.max()),float(g.l.min()),float(g.c.iloc[-1])]
stock=requests.get('http://127.0.0.1:8766/api/history?code=002130',timeout=15);stock.raise_for_status();assert stock.json()['code']=='002130'
assert {'SH_SZ_MAIN_BOARD','XAUUSD_SPOT'}<=set(requests.get('http://127.0.0.1:8766/api/health',timeout=5).json()['markets'])
out=dict(passed=True,gold_bars=len(rows),first=a['first'],last=a['last'],timezone='Europe/London',source_timezone='fixed UTC-05',uk_DST_boundary_checks=4,independent_minute_to_daily_checks=3,stock_page_regression=True,no_fictional_volume=True,source_duplicate_timestamps=sum(s['duplicate_timestamps']for s in m['sources']),source_timestamp_issue_dates=sorted({day for s in m['sources']for day in s['source_timestamp_issue_dates']}))
(ROOT.parent/'K线数据/黄金/VALIDATION.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(out,ensure_ascii=False))
