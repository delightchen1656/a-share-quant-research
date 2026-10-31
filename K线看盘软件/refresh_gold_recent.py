"""Append documented spot OHLC only when UTC boundaries equal London boundaries.

No fake resampling of UTC daily bars in BST. No shifting/scaling prices.
"""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,os,zipfile
import pandas as pd
import numpy as np
import requests
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent/'K线数据/黄金'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,obj):p.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf8')
def aligned(start):
    t=pd.Timestamp(start);end=t+pd.Timedelta(days=1)
    a=t.tz_convert('Europe/London');b=end.tz_convert('Europe/London')
    return a.strftime('%H:%M:%S')=='00:00:00' and b.strftime('%H:%M:%S')=='00:00:00' and a.date()+pd.Timedelta(days=1)==b.date()
def fetch(session,path,params,record):
    r=session.get('https://api.goldprice.dev/v1/'+path,params=params,timeout=30);r.raise_for_status();obj=r.json()
    save(record,dict(url=r.url,retrieved_at=datetime.now(timezone.utc).isoformat(),response=obj));return obj
def main():
    pointer=ROOT/'CURRENT.json';before=sha(pointer);link=json.loads(pointer.read_text(encoding='utf8'));mp=ROOT/link['manifest'];assert sha(mp)==link['sha256']
    old=json.loads(mp.read_text(encoding='utf8'));dp=ROOT/old['data_path'];assert sha(dp)==old['data_sha256'];frame=pd.read_parquet(dp)
    now=pd.Timestamp.now(tz='Europe/London');stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');raw=ROOT/'raw';raw.mkdir(exist_ok=True)
    history_file=raw/f'goldprice_dev_daily_{stamp}.json';latest_file=raw/f'goldprice_dev_latest_{stamp}.json'
    with requests.Session()as session:
        data=fetch(session,'bars',dict(symbol='XAU-USD-SPOT',interval='1d',**{'from':(now-pd.Timedelta(days=20)).strftime('%Y-%m-%d'),'to':now.strftime('%Y-%m-%d'),'limit':100}),history_file)
        latest=fetch(session,'bars/latest',dict(symbol='XAU-USD-SPOT',interval='1d'),latest_file)
    assert data['symbol']=='XAU-USD-SPOT' and data['interval']=='1d' and data.get('next_cursor')is None
    bars=data['bars']; lb=latest.get('bar')
    if lb and not any(x['bar_start']==lb['bar_start']for x in bars):bars.append(lb)
    q=pd.DataFrame(bars);assert not q.empty
    q['start']=pd.to_datetime(q.bar_start,utc=True);q=q.sort_values('start');assert q.start.is_unique
    for c in ['open','high','low','close']:q[c]=pd.to_numeric(q[c],errors='raise')
    assert np.isfinite(q[['open','high','low','close']]).all().all() and q[['open','high','low','close']].gt(0).all().all()
    assert(q.high>=q[['open','close','low']].max(axis=1)).all()and(q.low<=q[['open','close','high']].min(axis=1)).all()
    assert q.volume.isna().all()
    q['date']=q.start.dt.strftime('%Y-%m-%d')
    # Compare matching UTC days from original minutes, NOT differently-cut BST bars.
    parts=[]
    for item in old['sources']:
        if item['year']==now.year and item.get('month')in {now.month,(now-pd.Timedelta(days=20)).month}:
            zp=ROOT/item['path'];assert sha(zp)==item['sha256']
            with zipfile.ZipFile(zp)as z:
                name=next(n for n in z.namelist()if n.endswith('.csv'))
                with z.open(name)as f:r=pd.read_csv(f,sep=';',header=None,names=['stamp','open','high','low','close','volume'])
            r['utc']=pd.to_datetime(r.stamp,format='%Y%m%d %H%M%S')+pd.Timedelta(hours=5);r['date']=r.utc.dt.strftime('%Y-%m-%d');parts.append(r)
    m=pd.concat(parts).sort_values('utc',kind='stable').groupby('date').agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'))if parts else pd.DataFrame(columns=['open','high','low','close'])
    # Once a source is accepted, validate rolling responses against its already
    # verified same-cut bars; the initial HistData overlap must not expire the updater.
    if 'source'in frame:
        prior=frame[frame.source.eq('Gold Price API 现货')].set_index('date')[['open','high','low','close']]
        m=pd.concat([m,prior]);m=m[~m.index.duplicated(keep='last')]
    overlap=q[q.is_closed.eq(True)].set_index('date').join(m,rsuffix='_hist',how='inner');assert len(overlap)>=3
    comparisons=[]
    for day,r in overlap.iterrows():
        row=dict(date=day)
        for c in ['open','high','low','close']:row[c+'_difference_usd']=float(r[c]-r[c+'_hist']);row[c+'_difference_fraction']=float(r[c]/r[c+'_hist']-1)
        comparisons.append(row)
    close_errors=np.abs([r['close_difference_fraction']for r in comparisons]);assert np.median(close_errors)<=.002 and close_errors.max()<=.005,'Sources differ too much; no commit'
    append=q[q.date.gt(old['last']) & q.is_closed.eq(True) & q.start.map(aligned) & q.date.lt(now.strftime('%Y-%m-%d'))].copy()
    rejected=q[q.date.gt(old['last']) & ~q.start.map(aligned)].date.tolist()
    if append.empty:print(json.dumps(dict(status='no_new_aligned_closed_bars',last=old['last'],rejected_UTC_days=rejected,latest_provider_closed_date=q.loc[q.is_closed.eq(True),'date'].max())));return
    if 'source'not in frame:frame['source']='HistData BID'
    new=[]
    for r in append.itertuples():new.append(dict(date=r.date,open=r.open,high=r.high,low=r.low,close=r.close,quote_minutes=None,first_utc=pd.NaT,last_utc=pd.NaT,source='Gold Price API 现货'))
    result=pd.concat([frame,pd.DataFrame(new)],ignore_index=True).sort_values('date').reset_index(drop=True)
    assert result.date.is_unique
    # Check historical actual OHLC are identical; only derived tail indicators are recomputed.
    pd.testing.assert_frame_equal(frame[['date','open','high','low','close']].reset_index(drop=True),result.iloc[:len(frame)][['date','open','high','low','close']].reset_index(drop=True))
    result['change']=result.close.pct_change()
    for n in [5,10,20,60]:result['ma'+str(n)]=result.close.rolling(n,min_periods=n).mean()
    snap=ROOT/'snapshots'/stamp;snap.mkdir(parents=True);out=snap/'daily.parquet';result.to_parquet(out,index=False)
    meta=dict(old);ext=dict(provider='Gold Price API',symbol='XAU-USD-SPOT',price_basis='Canonical spot reference; not guaranteed BID',interval='1d',cut='UTC daily accepted only when both boundaries are exact Europe/London midnights',added_dates=append.date.tolist(),source_file=str(history_file.relative_to(ROOT)),source_sha256=sha(history_file),latest_file=str(latest_file.relative_to(ROOT)),latest_sha256=sha(latest_file),retrieved_at=datetime.now(timezone.utc).isoformat(),overlap_UTC_days=comparisons,median_absolute_close_difference_fraction=float(np.median(close_errors)),max_absolute_close_difference_fraction=float(close_errors.max()),prices_shifted_or_scaled=False,documentation='https://goldprice.dev/docs/historical',native_missing_dates=['2026-10-25']if old['last']=='2026-10-23'else[],note='Provider publishes weekday bars; missing Sunday short session is not invented. Current open London day is excluded.')
    meta.update(provider='HistData + Gold Price API',price_side='历史BID / 近期现货参考',last=result.date.max(),bars=len(result),last_quote_utc=None,latest_complete_date=result.date.max(),downloaded_at=datetime.now(timezone.utc).isoformat(),data_path=str(out.relative_to(ROOT)),data_sha256=sha(out),not_live=True,current_day_excluded=True,extensions=old.get('extensions',[])+[ext])
    save(snap/'MANIFEST.json',meta);save(snap/'OVERLAP_AUDIT.json',ext)
    assert sha(pointer)==before,'Another updater changed gold CURRENT; abort commit'
    temp=ROOT/'CURRENT.tmp';save(temp,dict(manifest=str((snap/'MANIFEST.json').relative_to(ROOT)),sha256=sha(snap/'MANIFEST.json')));os.replace(temp,pointer)
    print(json.dumps(dict(first=meta['first'],last=meta['last'],bars=meta['bars'],added_dates=ext['added_dates'],overlap_days=len(overlap),max_close_difference_pct=float(close_errors.max()*100),rejected_UTC_dates=rejected),ensure_ascii=False))
if __name__=='__main__':main()
