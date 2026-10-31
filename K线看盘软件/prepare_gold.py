"""Separate XAUUSD quote import; never reads/writes the A-share pipeline."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,zipfile,io,os,time
import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent/'K线数据/黄金'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    now=pd.Timestamp.now(tz='Europe/London');ROOT.mkdir(exist_ok=True);raw=ROOT/'raw';raw.mkdir(exist_ok=True)
    daily=[];sources=[]
    periods=[(y,None)for y in range(2015,now.year)]+[(now.year,m)for m in range(1,now.month+1)]
    for year,month in periods:
        key=str(year)+(f'{month:02}'if month else '')
        p=raw/f'XAUUSD_M1_{key}.zip';page=f'https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd/{year}'+(f'/{month}'if month else '')
        # Historical immutable downloads are reused; current year is explicitly refreshed.
        if not p.exists() or (year==now.year and month==now.month):
            with requests.Session()as session:
                r=session.get(page,timeout=35);r.raise_for_status();soup=BeautifulSoup(r.text,'html.parser');form=soup.select_one('#file_down')
                if form is None:raise RuntimeError(f'No published download for {year}')
                values={x['name']:x.get('value','')for x in form.select('input[name]')}
                r=session.post('https://www.histdata.com/get.php',data=values,headers={'Referer':page},timeout=80);r.raise_for_status()
                if not r.content.startswith(b'PK'):raise RuntimeError(f'Not a ZIP download: {year}')
                temp=p.with_suffix('.tmp');temp.write_bytes(r.content)
                with zipfile.ZipFile(temp)as z:assert z.testzip()is None
                os.replace(temp,p)
        with zipfile.ZipFile(p)as z:
            names=[n for n in z.namelist()if n.lower().endswith('.csv')];assert len(names)==1
            with z.open(names[0])as f:frame=pd.read_csv(f,sep=';',header=None,names=['stamp','open','high','low','close','provider_volume'])
        stamp=pd.to_datetime(frame.pop('stamp'),format='%Y%m%d %H%M%S',errors='raise').dt.tz_localize('Etc/GMT+5').dt.tz_convert('UTC')
        duplicates=int(stamp.duplicated().sum());backwards=int((stamp.diff().dt.total_seconds()<0).sum())
        frame['utc']=stamp;frame['date']=stamp.dt.tz_convert('Europe/London').dt.strftime('%Y-%m-%d')
        flagged_dates=sorted(frame.loc[stamp.duplicated(keep=False),'date'].unique().tolist())
        frame=frame.sort_values('utc',kind='stable') # Retain all duplicate observations in OHLC extrema; never silently drop conflicting quotes.
        for c in ['open','high','low','close']:frame[c]=pd.to_numeric(frame[c],errors='raise')
        assert np.isfinite(frame[['open','high','low','close']]).all().all()and frame[['open','high','low','close']].gt(0).all().all()
        assert (frame.high>=frame[['open','close','low']].max(axis=1)).all()and(frame.low<=frame[['open','close','high']].min(axis=1)).all()
        group=frame.groupby('date',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),quote_minutes=('close','size'),first_utc=('utc','first'),last_utc=('utc','last')).reset_index();daily.append(group)
        sources.append(dict(year=year,month=month,path=str(p.relative_to(ROOT)),sha256=sha(p),url=page,minute_bars=len(frame),first_utc=stamp.min().isoformat(),last_utc=stamp.max().isoformat(),duplicate_timestamps=duplicates,backwards_timestamp_steps=backwards,source_timestamp_issue_dates=flagged_dates,duplicate_policy='retain all quotes in stable timestamp order; day OHLC preserves observed extremes, no deduplication or invented prices'))
        print(json.dumps(dict(year=year,minutes=len(frame),last=str(stamp.max()))),flush=True)
    result=pd.concat(daily).sort_values('first_utc').groupby('date',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),quote_minutes=('quote_minutes','sum'),first_utc=('first_utc','min'),last_utc=('last_utc','max')).reset_index()
    # Do not invent holidays or claim the still-open London day is complete.
    result=result[result.date.ge('2015-01-01')&result.date.lt(now.strftime('%Y-%m-%d'))].copy()
    result['change']=result.close.pct_change()
    for n in [5,10,20,60]:result[f'ma{n}']=result.close.rolling(n,min_periods=n).mean()
    assert result.date.is_unique and len(result)>2000 and result.date.max()[:4]==str(now.year)
    prior_pointer=ROOT/'CURRENT.json'
    if prior_pointer.exists():
        prior=json.loads(prior_pointer.read_text(encoding='utf8'));previous=json.loads((ROOT/prior['manifest']).read_text(encoding='utf8'))
        if previous['last']>result.date.max():raise RuntimeError('HistData is older than the current combined gold snapshot. Preserve CURRENT; run refresh_gold_recent.py instead.')
    snapshot=ROOT/'snapshots'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');snapshot.mkdir(parents=True)
    datafile=snapshot/'daily.parquet';result.to_parquet(datafile,index=False)
    meta=dict(instrument='XAUUSD',name='伦敦金现货',currency='USD',unit='USD / troy oz',price_side='BID',provider='HistData.com',provider_timezone='EST fixed UTC-05, no DST',timezone='Europe/London',daily_boundary='00:00 Europe/London; GMT/BST automatic',first=result.date.min(),last=result.date.max(),bars=len(result),last_quote_utc=max(s['last_utc']for s in sources),downloaded_at=datetime.now(timezone.utc).isoformat(),not_live=True,centralized_volume_available=False,sunday_short_sessions='Retain real quoted London calendar dates including short Sundays; no Chinese or UK bank-holiday date filling',sources=sources,data_sha256=sha(datafile),data_path=str(datafile.relative_to(ROOT)),current_day_excluded=True)
    (snapshot/'MANIFEST.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
    pointer=ROOT/'CURRENT.json';temp=ROOT/'CURRENT.tmp';temp.write_text(json.dumps(dict(manifest=str((snapshot/'MANIFEST.json').relative_to(ROOT)),sha256=sha(snapshot/'MANIFEST.json')),indent=2),encoding='utf8');os.replace(temp,pointer)
    print(json.dumps({k:meta[k]for k in ['first','last','bars','last_quote_utc']},ensure_ascii=False),flush=True)
if __name__=='__main__':main()
