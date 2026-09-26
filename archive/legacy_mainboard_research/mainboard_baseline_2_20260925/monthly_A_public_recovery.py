"""Alternate public data, no retries against the rejected BaoStock service.
Tencent supplies unadjusted bars; adjustment factors are reconstructed from
Eastmoney disclosed cash/bonus records, NOT mixed with additive qfq quotes.
"""
import json
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
import pandas as pd
import requests
import execution_engine as bt

OUT=Path(__file__).resolve().parent/'monthly_A_alignment_20260924'
PUB=OUT/'public_recovery'

def get(url,params):
    for attempt in range(3):
        try:
            response=requests.get(url,params=params,timeout=20)
            response.raise_for_status();return response.json()
        except Exception:
            if attempt==2:raise
            time.sleep(2*(attempt+1))

def ledger():
    target=PUB/'dividends.json'
    if target.exists():return json.loads(target.read_text(encoding='utf-8'))
    url='https://datacenter-web.eastmoney.com/api/data/v1/get'
    params=dict(reportName='RPT_SHAREBONUS_DET',columns='ALL',pageSize=500,pageNumber=1,
        sortColumns='EX_DIVIDEND_DATE,SECURITY_CODE,REPORT_DATE',sortTypes='1,1,1')
    data=[];page=1;pages=1
    while page<=pages:
        cache=PUB/('dividends_page_%03d.json'%page)
        if cache.exists():j=json.loads(cache.read_text(encoding='utf-8'))
        else:
            params['pageNumber']=page;j=get(url,params)
            assert j.get('success') and j.get('result'),j
            cache.write_text(json.dumps(j,ensure_ascii=False),encoding='utf-8');time.sleep(.3)
        pages=j['result']['pages'];data.extend(j['result']['data'])
        print('PUBLIC LEDGER',page,'/',pages,flush=True);page+=1
    target.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return data

def action_map(records):
    result={};seen={}
    for r in records:
        symbol=r['SECUCODE'];date=pd.Timestamp(r['EX_DIVIDEND_DATE'])
        if pd.isna(date) or not pd.Timestamp('2015-01-01')<=date<=pd.Timestamp('2026-09-11'):continue
        cash=float(r.get('PRETAX_BONUS_RMB') or 0)/10.
        bonus=float(r.get('BONUS_IT_RATIO') or 0)/10.
        event=dict(date=date,cash=cash,bonus=bonus)
        key=(symbol,date)
        period_key=(symbol,date,r.get('REPORT_DATE'))
        if period_key in seen:
            if seen[period_key]!=event:raise ValueError('Conflicting dividend records '+str(period_key))
            continue
        seen[period_key]=event
        # Distinct financial periods can pay on the same ex-date; preserve both.
        if key not in result:result[key]=dict(date=date,cash=0.,bonus=0.)
        result[key]['cash']+=cash;result[key]['bonus']+=bonus
    return result

def reconstruct(raw,events):
    raw=raw.sort_values('date').copy();factor=[];level=1.;prev=None;prevdate=None
    for row in raw.itertuples():
        if prev is not None:
            theoretical=prev
            for ev in events:
                if prevdate<ev['date']<=row.date:theoretical=(theoretical-ev['cash'])/(1+ev['bonus'])
            if theoretical<=0:raise ValueError('Invalid corporate action denominator')
            level*=prev/theoretical
        factor.append(level);prev=float(row.close);prevdate=row.date
    adj=raw.copy()
    for col in ('open','high','low','close'):adj[col]=raw[col].to_numpy()*np.asarray(factor)
    return adj

def warm_one(symbol,events):
    rawdest=OUT/'warmup/raw'/(symbol+'.parquet');qdest=OUT/'warmup/qfq'/(symbol+'.parquet')
    if rawdest.exists() and qdest.exists():
        try:
            a=pd.read_parquet(rawdest);b=pd.read_parquet(qdest)
            return dict(symbol=symbol,raw=len(a),qfq=len(b),source='existing_cache')
        except Exception:pass
    cache=PUB/(symbol+'_raw.json')
    try:
        if cache.exists():j=json.loads(cache.read_text(encoding='utf-8'))
        else:
            code=symbol[-2:].lower()+symbol[:6]
            j=get('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get',dict(param=code+',day,2015-01-01,2018-01-10,800,'))
            assert j.get('code')==0,j
            cache.write_text(json.dumps(j,ensure_ascii=False),encoding='utf-8');time.sleep(.25)
        code=symbol[-2:].lower()+symbol[:6];bars=j.get('data',{}).get(code,{}).get('day',[])
        if not bars:raise ValueError('Missing unadjusted history for old listing')
        raw=pd.DataFrame([r[:6] for r in bars],columns=['date','open','close','high','low','volume'])
        raw['date']=pd.to_datetime(raw.date)
        for c in ('open','high','low','close','volume'):raw[c]=pd.to_numeric(raw[c])
        raw=raw[raw.volume>0].copy();raw['volume']*=100
        raw['code']=symbol[-2:].lower()+'.'+symbol[:6];raw['tradestatus']='1';raw['isST']='0'
        raw['amount']=np.nan;raw['turn']=np.nan;raw['preclose']=raw.close.shift(1);raw['pctChg']=np.nan
        raw=raw.sort_values('date');assert raw.date.is_unique and raw.date.between('2015-01-01','2018-01-10').all()
        old=pd.read_parquet(bt.raw_path(symbol));old['date']=pd.to_datetime(old.date)
        both=raw.merge(old[['date','close']],on='date',suffixes=('_public','_old'))
        suspended_bridge=False
        if both.empty:
            bridge=old[(old.date>raw.date.max())&(old.date<=pd.Timestamp('2018-01-10'))]
            # Tencent omits suspended sessions, whereas the local vendor carries
            # the last close. Bridge only a price-identical, action-free halt.
            if (bridge.empty or not bridge.tradestatus.astype(str).eq('0').all()
                or (bridge.close-float(raw.close.iloc[-1])).abs().max()>.011
                or any(raw.date.max()<ev['date']<=bridge.date.max() for ev in events)):
                raise ValueError('No independently consistent overlap or suspended bridge')
            raw=pd.concat([raw,bridge],ignore_index=True).sort_values('date')
            both=raw.merge(old[['date','close']],on='date',suffixes=('_public','_old'))
            suspended_bridge=True
        raw_error=float((both.close_public-both.close_old).abs().max())
        if raw_error>.011:raise ValueError('Raw overlap differs '+str(raw_error))
        adj=reconstruct(raw,events)
        if rawdest.exists():
            # Preserve earlier successful raw vendor file, but reconstruct on its dates.
            existing=pd.read_parquet(rawdest)
            if len(existing):raw=existing;adj=reconstruct(raw,events)
        else:raw.to_parquet(rawdest,index=False)
        adj.to_parquet(qdest,index=False)
        return dict(symbol=symbol,raw=len(raw),qfq=len(adj),source='Tencent raw + Eastmoney cash/bonus multiplicative reconstruction',raw_overlap_error=raw_error,suspended_bridge=suspended_bridge)
    except Exception as exc:return dict(symbol=symbol,error=str(exc))

def main():
    PUB.mkdir(exist_ok=True)
    records=ledger();events=action_map(records)
    # Cross-check reconstructed factors on a bounded existing-provider sample.
    checks=[]
    for path in sorted((OUT/'warmup/raw').glob('*.parquet'))[:30]:
        qpath=OUT/'warmup/qfq'/path.name
        if not qpath.exists():continue
        raw=pd.read_parquet(path);reference=pd.read_parquet(qpath)
        if raw.empty or reference.empty:continue
        ev=sorted([v for (s,d),v in events.items() if s==path.stem and d<=pd.Timestamp('2018-01-10')],key=lambda v:v['date'])
        reconstructed=reconstruct(raw[raw.volume>0],ev)
        z=reconstructed[['date','close']].merge(reference[['date','close']],on='date',suffixes=('_new','_ref'))
        scale=float((z.close_ref/z.close_new).iloc[-1]);error=float((z.close_new*scale/z.close_ref-1).abs().max())
        checks.append(dict(symbol=path.stem,max_relative_error=error))
    (PUB/'reconstruction_checks.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
    print('RECONSTRUCTION',len(checks),'median',np.median([c['max_relative_error'] for c in checks]),'max',max(c['max_relative_error'] for c in checks),flush=True)
    assert len(checks)>=20 and np.quantile([c['max_relative_error'] for c in checks],.9)<.005,'Alternate reconstruction differs materially; do not continue'
    meta=pd.read_csv(bt.DATA/'metadata/historical_mainboard_universe.csv',dtype=str)
    symbols=sorted(meta.loc[meta.symbol.isin(set(bt.load_universe()))&(meta.ipoDate<'2018-01-01'),'symbol'].unique())
    by={s:[] for s in symbols}
    for (s,d),v in events.items():
        if s in by and d<=pd.Timestamp('2018-01-10'):by[s].append(v)
    for v in by.values():v.sort(key=lambda x:x['date'])
    results=[];network_failures=0
    for s in symbols:
        result=warm_one(s,by[s]);results.append(result)
        if 'error' in result:
            print('PUBLIC GAP',result,flush=True)
            network_failures+=int(any(x in result['error'].lower() for x in ('timeout','timed out','connection','server error','403','429','max retries')))
        else:network_failures=0
        if len(results)%50==0 or 'error' in result:
            (PUB/'warmup_progress.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        if network_failures>=3:raise RuntimeError('Repeated network failure; stopped acquisition. Cached history retained.')
        if len(results)%100==0:print('PUBLIC WARMUP',len(results),'/',len(symbols),'errors',sum('error' in r for r in results),flush=True)
    manifest=dict(source='Mixed existing BaoStock cache and independently checked Tencent raw plus Eastmoney actions; no additive-qfq splice',results=results)
    (OUT/'warmup/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    action_results=write_action_ledger(events)
    assert all('error' not in r for r in results),'Public warmup gaps remain; see manifest'
    print('PUBLIC RECOVERY DONE',len(results),len(action_results),flush=True)

def write_action_ledger(events):
    # Full event coverage for the trading period, using cached BaoStock dates when available.
    action_results=[];official={}
    for path in (OUT/'action_ledger').glob('*.json'):
        if path.name=='manifest.json':continue
        v=json.loads(path.read_text(encoding='utf-8'))
        for r in v.get('rows',[]):
            if r.get('dividOperateDate'):official[(v['symbol'],pd.Timestamp(r['dividOperateDate']))]=r
    universe=set(bt.load_universe())
    for (s,d),ev in events.items():
        if s not in universe or not pd.Timestamp('2020-01-01')<=d<=pd.Timestamp('2026-09-11'):continue
        old=official.get((s,d))
        if old and (abs(float(old.get('dividCashPsBeforeTax') or 0)-ev['cash'])>1e-5 or abs(float(old.get('dividStocksPs') or 0)+float(old.get('dividReserveToStockPs') or 0)-ev['bonus'])>1e-5):old=None
        row=old or dict(dividOperateDate=str(d.date()),dividPayDate=str(d.date()),dividStockMarketDate=str((d+pd.Timedelta(days=1)).date()),dividCashPsBeforeTax=ev['cash'],dividStocksPs=ev['bonus'],dividReserveToStockPs=0)
        action_results.append(dict(symbol=s,year=str(d.year),rows=[row],source='BaoStock cached' if old else 'Eastmoney; payment assumed exdate, bonus availability next calendar day'))
    (OUT/'action_ledger/manifest.json').write_text(json.dumps(dict(source='Independent full dividend cash/bonus events; payment/listing timing approximated when not supplied',results=action_results),ensure_ascii=False,indent=2),encoding='utf-8')
    return action_results

if __name__=='__main__':main()
