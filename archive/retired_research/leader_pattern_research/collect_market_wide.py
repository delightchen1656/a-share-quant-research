"""Read-only core snapshots and public daily supplements for all current SH/SZ A stocks."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib,json,threading,requests,time,sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
BASE=HERE/'market_wide/holdout_restricted/v1';DATA=BASE/'inputs_daily';PARTS=DATA/'provider_parts'
for p in [BASE,DATA,DATA/'raw',DATA/'qfq',PARTS]:p.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT));from tools import daily_market_update as unified
local=threading.local()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):
    p=Path(p);temp=p.with_suffix(p.suffix+'.tmp');temp.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');temp.replace(p)
def session():
    if not hasattr(local,'http'):local.http=requests.Session()
    return local.http
def validate(f,code,cutoff):
    assert f.date.is_monotonic_increasing and not f.date.duplicated().any()
    assert f.date.between('2018-01-01',cutoff).all()
    if len(f):unified.validate_frame(f,code=code,target=pd.Timestamp(cutoff))

def query(task):
    code,mode,k,start,end,cutoff=task
    p=PARTS/f'{code}_{mode}_{k}.parquet';meta=p.with_suffix('.json')
    if p.exists() and meta.exists():
        j=json.loads(meta.read_text(encoding='utf-8'))
        if j.get('ok') and j['sha256']==sha(p):return j
    symbol=('sh' if code.startswith('6') else 'sz')+code
    param=f'{symbol},day,{start},{end},640,'+('qfq' if mode=='qfq' else '')
    error=None
    for attempt in range(3):
        try:
            response=session().get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',params={'param':param},timeout=25)
            response.raise_for_status();j=response.json();assert j.get('code')==0,str(j.get('msg'))[:100]
            d=(j.get('data') or {}).get(symbol,{})
            rows=d.get('qfqday' if mode=='qfq' and 'qfqday' in d else 'day') or []
            f=pd.DataFrame([r[:6] for r in rows],columns=['date','open','close','high','low','volume'])
            f['date']=pd.to_datetime(f.date)
            for col in ['open','close','high','low','volume']:f[col]=pd.to_numeric(f[col],errors='raise')
            assert f.date.between(start,end).all()
            assert len(f)<640,'Potential truncation at provider limit'
            f['volume']*=100;f['tradestatus']=np.where(f.volume.gt(0),'1','0')
            f['preclose']=np.nan;f['pctChg']=np.nan;f['isST']=None;f['amount']=np.nan
            validate(f,symbol,cutoff);f.to_parquet(p,index=False)
            result=dict(ok=True,code=code,mode=mode,part=k,rows=len(f),query=param,sha256=sha(p),path=str(p))
            dump(meta,result);return result
        except Exception as exc:
            error=repr(exc)
            if attempt<2:time.sleep(.4*(attempt+1))
    return dict(ok=False,code=code,mode=mode,part=k,error=error)

def freeze(task):
    code,mode,source,kind,cutoff=task;source=Path(source);out=DATA/mode/f'{code}.parquet';meta=out.with_suffix('.json')
    if out.exists() and meta.exists():
        j=json.loads(meta.read_text(encoding='utf-8'))
        if j.get('ok') and sha(out)==j['snapshot_sha256']:return j
    before=sha(source);f=pd.read_parquet(source)
    f['date']=pd.to_datetime(f.date);f=f[f.date.between('2018-01-01',cutoff)].copy()
    for col in ['open','high','low','close','preclose','volume','amount','pctChg']:
        if col in f:f[col]=pd.to_numeric(f[col],errors='coerce')
    validate(f,code,cutoff);assert before==sha(source),'Protected source changed while copying'
    # Freeze only observational quote columns; original source remains untouched.
    fields=[c for c in ['date','open','high','low','close','preclose','volume','amount','pctChg','tradestatus','isST'] if c in f]
    f[fields].to_parquet(out,index=False)
    j=dict(ok=True,code=code,mode=mode,source=str(source),source_sha256=before,source_type=kind,
        path=str(out.resolve()),snapshot_sha256=sha(out),rows=len(f),first=str(f.date.min().date()) if len(f) else None,last=str(f.date.max().date()) if len(f) else None)
    dump(meta,j);return j

def main():
    manifest_path=DATA/'manifest.json'
    if manifest_path.exists():print('Complete market snapshot already exists; reuse.',flush=True);return
    cutoff='2026-10-26'
    audit=ROOT/'data_updates'/cutoff.replace('-','')/'audit.json'
    assert json.loads(audit.read_text(encoding='utf-8'))['status']=='ok'
    membership=ROOT/'outputs/industry_linkage_screen_20261027/holdout_restricted/membership.json'
    j=json.loads(membership.read_text(encoding='utf-8'));c=pd.DataFrame(j['companies'])
    universe=c[['SECURITY_CODE','SECURITY_NAME_ABBR','SECUCODE']].rename(columns={'SECURITY_CODE':'code','SECURITY_NAME_ABBR':'name','SECUCODE':'symbol'})
    assert universe.code.is_unique and universe.code.str.match(r'^[036]\d{5}$').all()
    leaders=pd.read_parquet(HERE/'holdout_restricted/patterns_v1/frozen_pool_185.parquet')
    universe['is_leader']=universe.code.isin(leaders.code);assert universe.is_leader.sum()==185
    universe['board']=np.where(universe.code.str.startswith('688'),'科创板',np.where(universe.code.str.startswith('3'),'创业板','主板'))
    universe.to_parquet(BASE/'universe.parquet',index=False)
    dates=pd.DatetimeIndex(pd.to_datetime(pd.read_csv(HERE/'holdout_restricted/patterns_v1/event_results_v1r2/exchange_sessions.csv').date))
    pd.DataFrame({'date':dates}).to_csv(BASE/'exchange_sessions.csv',index=False)
    chunks=[];start=0
    while start<len(dates):
        stop=min(start+599,len(dates)-1);chunks.append((str(dates[start].date()),str(dates[stop].date())))
        if stop==len(dates)-1:break
        start=stop-19
    records=[];todo=[];missing=set()
    frozen=HERE/'holdout_restricted/patterns_v1/inputs_daily'
    index={}
    for data_root in [ROOT/'sh_sz_market_research/data_pipeline/data',ROOT/'evening_accumulation/data']:
        for mode in ['raw','qfq']:
            for p in (data_root/mode).rglob('*.parquet'):index[(p.stem.split('.')[0],mode)]=p
    for row in universe.itertuples():
        for mode in ['raw','qfq']:
            existing=frozen/mode/f'{row.code}.parquet'
            if existing.exists():
                f=pd.read_parquet(existing,columns=['date'])
                records.append(dict(ok=True,code=row.code,mode=mode,source_type='Exact_frozen_leader_quote',path=str(existing.resolve()),snapshot_sha256=sha(existing),rows=len(f),first=str(f.date.min().date()),last=str(f.date.max().date())))
            elif (row.code,mode) in index:todo.append((row.code,mode,index[(row.code,mode)],'Protected_committed_readonly',cutoff))
            else:missing.add(row.code)
    dump(BASE/'REQUEST.json',dict(scope='Current all5222SHSZAstocks, mainboard+STAR+Growthboard, no ST exclusion.',
        membership_asof=j['asof'],current_universe_not_historical_point_in_time=True,cutoff=cutoff,
        current_stocks=len(universe),leader_stocks=185,existing_frozen_pairs=len(records),local_pairs_to_freeze=len(todo),
        missing_stocks=len(missing),bounded_chunks=chunks,quote_unit='shares;publicproviderhands multiplied100',
        membership_sha256=sha(membership),universe_sha256=sha(BASE/'universe.parquet'),protected_audit_sha256=sha(audit)))
    print('Universe',len(universe),'leaders185; local pairs',len(todo),'missing stocks',len(missing),'chunks',len(chunks),flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(freeze,t) for t in todo]
        for n,future in enumerate(as_completed(futures),1):
            records.append(future.result())
            if n%1000==0:print('Local snapshots',n,'/',len(todo),flush=True)
    tasks=[(code,mode,k,a,b,cutoff) for code in sorted(missing) for mode in ['raw','qfq'] for k,(a,b) in enumerate(chunks)]
    results=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures=[pool.submit(query,t) for t in tasks]
        for n,future in enumerate(as_completed(futures),1):
            results.append(future.result())
            if n%200==0 or n==len(tasks):
                progress=dict(stage='supplements',completed=n,total=len(tasks),failed=sum(not r['ok'] for r in results));dump(BASE/'COLLECTION_PROGRESS.json',progress);print(progress,flush=True)
    dump(BASE/'SUPPLEMENT_REQUESTS.json',dict(total=len(results),failures=[r for r in results if not r['ok']]))
    assert all(r['ok'] for r in results),'Supplement failures retained; rerun resumes successful parts'
    overlap=[]
    for code in sorted(missing):
        for mode in ['raw','qfq']:
            combined=None
            for k,_ in enumerate(chunks):
                f=pd.read_parquet(PARTS/f'{code}_{mode}_{k}.parquet')
                if combined is None:combined=f;continue
                common=combined.merge(f,on='date',suffixes=('_old','_new'))
                for col in ['open','high','low','close']:np.testing.assert_allclose(common[col+'_old'],common[col+'_new'],atol=.0011,rtol=0)
                overlap.append(dict(code=code,mode=mode,part=k,rows=len(common)))
                combined=pd.concat([combined,f[~f.date.isin(combined.date)]],ignore_index=True).sort_values('date').reset_index(drop=True)
            validate(combined,code,cutoff);p=DATA/mode/f'{code}.parquet';combined.to_parquet(p,index=False)
            records.append(dict(ok=True,code=code,mode=mode,source_type='Tencent_bounded640_with_session_overlap',path=str(p.resolve()),
                snapshot_sha256=sha(p),rows=len(combined),first=str(combined.date.min().date()) if len(combined) else None,last=str(combined.date.max().date()) if len(combined) else None))
    assert len(records)==len(universe)*2
    dump(manifest_path,dict(cutoff=cutoff,stocks=len(universe),required_stocks=len(universe),snapshots=len(records),files=records,
        all_protected_assets_readonly=True,overlap_checks=overlap,universe_sha256=sha(BASE/'universe.parquet')))
    dump(BASE/'COLLECTION_PROGRESS.json',dict(stage='complete',stocks=len(universe),snapshots=len(records),failed=0))
    print('Full market input snapshots complete.',flush=True)

if __name__=='__main__':main()
