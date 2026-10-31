"""Immutable daily inputs: committed local bars plus bounded public supplements."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json,sys,requests,hashlib,datetime,time
import pandas as pd
import numpy as np

BASE=Path(__file__).resolve().parent;ROOT=BASE.parent
OUT=BASE/'holdout_restricted/patterns_v1'
STORE=OUT/'inputs_daily';PARTS=STORE/'provider_year_parts'
for p in [STORE,PARTS,STORE/'raw',STORE/'qfq']:p.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT))
from tools import daily_market_update as unified
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def validate(f,symbol):
    assert f.date.is_monotonic_increasing and not f.date.duplicated().any()
    assert f.date.between('2018-01-01','2026-10-26').all()
    if len(f):unified.validate_frame(f,code=symbol,target=pd.Timestamp('2026-10-26'))

def query(task):
    code,mode,year=task
    p=PARTS/f'{code}_{mode}_{year}.parquet';m=p.with_suffix('.json')
    if p.exists() and m.exists():
        old=json.loads(m.read_text(encoding='utf-8'))
        if old.get('ok') and old['sha256']==sha(p):return old
    start=pd.Timestamp(f'{year}-01-01')-pd.Timedelta(days=35)
    start=max(start,pd.Timestamp('2018-01-01'))
    end=min(pd.Timestamp(f'{year}-12-31'),pd.Timestamp('2026-10-26'))
    symbol=('sh' if code.startswith('6') else 'sz')+code
    param=f'{symbol},day,{start.date()},{end.date()},420,'+('qfq' if mode=='qfq' else '')
    error=None
    for attempt in range(2):
        try:
            j=requests.get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',params={'param':param},timeout=25).json()
            assert j.get('code')==0
            d=(j.get('data') or {}).get(symbol) or {}
            key='qfqday' if mode=='qfq' and d.get('qfqday') is not None else 'day'
            rows=d.get(key) or []
            f=pd.DataFrame([r[:6] for r in rows],columns=['date','open','close','high','low','volume_hands'])
            f['date']=pd.to_datetime(f.date)
            for col in f.columns[1:]:f[col]=pd.to_numeric(f[col],errors='raise')
            assert f.date.between(start,end).all()
            f['volume']=f.pop('volume_hands')*100
            f['tradestatus']=np.where(f.volume.gt(0),'1','0')
            # These missing fields are not official ex-price/ST evidence.
            f['preclose']=np.nan;f['pctChg']=np.nan;f['isST']=None;f['amount']=np.nan
            validate(f,symbol)
            f.to_parquet(p,index=False)
            r=dict(ok=True,code=code,mode=mode,year=year,rows=len(f),sha256=sha(p),query=param,returned_key=key,
                source='Tencent_bounded_public_daily',has_official_preclose_or_historicalST=False,zero_rows_not_proof_of_unlisted_status=True)
            dump(m,r);return r
        except Exception as exc:
            error=repr(exc)
            if attempt==0:time.sleep(.3)
    return dict(ok=False,code=code,mode=mode,year=year,error=error)

def main():
    assert not (STORE/'manifest.json').exists(),'Preserve completed data snapshots'
    inv=json.loads((OUT/'daily_data_inventory.json').read_text(encoding='utf-8'))
    records=[];missing=[]
    for r in inv['stocks']:
        for mode in ['raw','qfq']:
            if r[mode]['available']:
                source=Path(r[mode]['path']);source_hash=sha(source)
                f=pd.read_parquet(source)
                f=f.loc[pd.to_datetime(f.date).between('2018-01-01','2026-10-26')].copy()
                f['date']=pd.to_datetime(f.date)
                for col in ['open','high','low','close','preclose','volume','amount','pctChg']:
                    if col in f:f[col]=pd.to_numeric(f[col],errors='coerce')
                validate(f,r['symbol'])
                target=STORE/mode/f"{r['code']}.parquet";f.to_parquet(target,index=False)
                records.append(dict(code=r['code'],mode=mode,rows=len(f),source=str(source),source_sha256=source_hash,
                    source_type='Protected_committed_daily_readonly',snapshot_sha256=sha(target),has_official_preclose_or_historicalST=True))
            else:missing.append((r['code'],mode))
    print('Local daily snapshots',len(records),'missing code-mode pairs',len(missing),flush=True)
    results=[]
    tasks=[(c,m,y) for c,m in missing for y in range(2018,2027)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for n,r in enumerate(pool.map(query,tasks),1):
            results.append(r)
            if n%100==0:print('Bounded historical daily supplements',n,'/',len(tasks),flush=True)
    dump(OUT/'daily_supplement_requests.json',dict(sources=results,failed=[r for r in results if not r['ok']]))
    assert all(r['ok'] for r in results),'Retain failures before any signal outcomes'
    overlap_checks=[]
    for code,mode in missing:
        combined=None
        for year in range(2018,2027):
            f=pd.read_parquet(PARTS/f'{code}_{mode}_{year}.parquet')
            if combined is None:combined=f;continue
            overlap=combined.merge(f,on='date',suffixes=('_old','_new'))
            if len(overlap):
                # Overlapping calendar chunks must share one quote scale.
                for col in ['open','high','low','close']:
                    np.testing.assert_allclose(overlap[col+'_old'],overlap[col+'_new'],atol=.0011,rtol=0)
                overlap_checks.append(dict(code=code,mode=mode,year=year,rows=len(overlap)))
            combined=pd.concat([combined,f.loc[~f.date.isin(combined.date)]],ignore_index=True).sort_values('date').reset_index(drop=True)
        assert combined is not None and len(combined)>0,(code,mode)
        validate(combined,code)
        target=STORE/mode/f'{code}.parquet';combined.to_parquet(target,index=False)
        records.append(dict(code=code,mode=mode,rows=len(combined),source_type='Tencent_uniform_per_stock_year_chunks',
            snapshot_sha256=sha(target),has_official_preclose_or_historicalST=False))
    dump(STORE/'manifest.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        cutoff='2026-10-26',data_start='2018-01-01',snapshots=len(records),required_snapshots=370,
        original_assets_unchanged=True,year_chunk_adjusted_scale_overlap_checked=True,overlap_checks=overlap_checks,files=records))
    assert len(records)==370
    print('Daily input complete185stocks x2price modes; no signals evaluated.',flush=True)

if __name__=='__main__':main()
