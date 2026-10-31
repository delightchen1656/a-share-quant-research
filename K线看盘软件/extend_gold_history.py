"""Prepend available HistData minutes without rewriting existing gold OHLC."""
from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import json, os, zipfile, msvcrt
import requests
import pandas as pd
import numpy as np
from bs4 import BeautifulSoup
from prepare_gold import sha

ROOT=Path(__file__).resolve().parent.parent/'K线数据/黄金'
OHLC=['open','high','low','close']

def main():
    with (ROOT/'refresh.lock').open('a+b') as lock:
        if lock.tell()==0: lock.write(b'0'); lock.flush()
        lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        try: extend()
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)

def extend():
    pointer=ROOT/'CURRENT.json'; before=pointer.read_bytes()
    link=json.loads(before); mp=ROOT/link['manifest']; assert sha(mp)==link['sha256']
    meta=json.loads(mp.read_text(encoding='utf8')); oldpath=ROOT/meta['data_path']
    assert sha(oldpath)==meta['data_sha256']; old=pd.read_parquet(oldpath)
    index_url='https://www.histdata.com/download-free-forex-historical-data/?/ascii/1-minute-bar-quotes/xauusd'
    session=requests.Session(); r=session.get(index_url,timeout=35); r.raise_for_status()
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    index_file=ROOT/'raw'/f'histdata_index_{stamp}.html';index_file.write_text(r.text,encoding='utf8')
    soup=BeautifulSoup(r.text,'html.parser')
    available={y for y in range(2000,2015) if f'{y} - .Zip with Full {y} Year Data' in soup.get_text(' ',strip=True)}
    parts=[]; sources=[]; checks=[]
    for year in sorted(available):
        page=index_url+'/'+str(year); p=ROOT/'raw'/f'XAUUSD_M1_{year}.zip'
        if not p.exists():
            r=session.get(page,timeout=35);r.raise_for_status()
            form=BeautifulSoup(r.text,'html.parser').select_one('#file_down')
            if form is None:raise RuntimeError(f'No download form for {year}')
            values={x['name']:x.get('value','') for x in form.select('input[name]')}
            r=session.post('https://www.histdata.com/get.php',data=values,headers={'Referer':page},timeout=100)
            r.raise_for_status(); assert r.content.startswith(b'PK')
            temp=p.with_suffix('.tmp');temp.write_bytes(r.content)
            with zipfile.ZipFile(temp) as z:assert z.testzip() is None
            os.replace(temp,p)
        with zipfile.ZipFile(p) as z:
            names=[n for n in z.namelist() if n.lower().endswith('.csv')];assert len(names)==1
            with z.open(names[0]) as f:q=pd.read_csv(f,sep=';',header=None,names=['stamp']+OHLC+['volume'])
        t=pd.to_datetime(q.stamp,format='%Y%m%d %H%M%S').dt.tz_localize('Etc/GMT+5').dt.tz_convert('UTC')
        q['utc']=t;q['date']=t.dt.tz_convert('Europe/London').dt.strftime('%Y-%m-%d')
        assert np.isfinite(q[OHLC]).all().all() and q[OHLC].gt(0).all().all()
        assert (q.high>=q[['open','close','low']].max(axis=1)).all()
        assert (q.low<=q[['open','close','high']].min(axis=1)).all()
        duplicates=int(t.duplicated().sum());backwards=int((t.diff().dt.total_seconds()<0).sum())
        flagged=sorted(q.loc[t.duplicated(keep=False),'date'].unique().tolist())
        q=q.sort_values('utc',kind='stable')
        g=q.groupby('date',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),quote_minutes=('close','size'),first_utc=('utc','first'),last_utc=('utc','last')).reset_index()
        parts.append(g)
        # Independent stdlib conversion and extrema checks for winter and summer.
        for month in ['01','07']:
            candidates=g[g.date.str.startswith(f'{year}-{month}')]
            if candidates.empty:continue
            day=candidates.iloc[len(candidates)//2].date
            rows=q[q.date.eq(day)]; row=g[g.date.eq(day)].iloc[0]
            for value in rows.stamp.iloc[[0,-1]]:
                d=datetime.strptime(value,'%Y%m%d %H%M%S').replace(tzinfo=timezone(pd.Timedelta(hours=-5))).astimezone(ZoneInfo('Europe/London'))
                assert d.date().isoformat()==day
            assert [float(row[c]) for c in OHLC]==[float(rows.open.iloc[0]),float(rows.high.max()),float(rows.low.min()),float(rows.close.iloc[-1])]
            checks.append(day)
        sources.append(dict(year=year,month=None,path=str(p.relative_to(ROOT)),sha256=sha(p),url=page,minute_bars=len(q),first_utc=t.min().isoformat(),last_utc=t.max().isoformat(),duplicate_timestamps=duplicates,backwards_timestamp_steps=backwards,source_timestamp_issue_dates=flagged,duplicate_policy='retain all quotes in stable timestamp order; preserve all extrema'))
        print(json.dumps(dict(year=year,minutes=len(q),first=g.date.min(),last=g.date.max())),flush=True)
    assert parts, 'No available older minute data'
    history=pd.concat(parts).sort_values('first_utc',kind='stable').groupby('date',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),quote_minutes=('quote_minutes','sum'),first_utc=('first_utc','min'),last_utc=('last_utc','max')).reset_index()
    history=history[history.date.lt(old.date.min())].copy();history['source']='HistData BID'
    if history.empty:print(json.dumps(dict(status='already_extended',first=old.date.min())));return
    result=pd.concat([history,old],ignore_index=True).sort_values('date').reset_index(drop=True)
    assert result.date.is_unique and result.date.is_monotonic_increasing
    pd.testing.assert_frame_equal(result.loc[result.date.ge(old.date.min()),['date']+OHLC].reset_index(drop=True),old[['date']+OHLC].reset_index(drop=True))
    result['change']=result.close.pct_change()
    for n in [5,10,20,60]:result[f'ma{n}']=result.close.rolling(n,min_periods=n).mean()
    snapshot=ROOT/'snapshots'/stamp;snapshot.mkdir(parents=True)
    data=snapshot/'daily.parquet';result.to_parquet(data,index=False)
    audit=dict(passed=True,requested_start='2000-01-01',available_years=sorted(available),unavailable_years=sorted(set(range(2000,2015))-available),added_bars=len(history),first=result.date.min(),last=result.date.max(),bars=len(result),original_ohlc_unchanged=True,existing_snapshot=link,independent_sample_dates=checks,index_path=str(index_file.relative_to(ROOT)),index_sha256=sha(index_file),timezone='Europe/London',missing_history_not_fabricated=True)
    (snapshot/'HISTORY_EXTENSION_AUDIT.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
    meta.update(first=result.date.min(),bars=len(result),data_path=str(data.relative_to(ROOT)),data_sha256=sha(data),sources=sources+meta['sources'],history_extension=audit,history_extended_at=datetime.now(timezone.utc).isoformat())
    manifest=snapshot/'MANIFEST.json';manifest.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf8')
    assert pointer.read_bytes()==before,'CURRENT changed concurrently; no commit'
    temp=ROOT/'CURRENT.history.tmp';temp.write_text(json.dumps(dict(manifest=str(manifest.relative_to(ROOT)),sha256=sha(manifest)),indent=2),encoding='utf8');os.replace(temp,pointer)
    print(json.dumps(audit,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
