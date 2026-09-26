"""Extend factor warm-up without modifying original market files."""
import json
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import time
import socket
import pandas as pd
import baostock as bs
import execution_engine as bt

OUT=Path(__file__).resolve().parent/'monthly_A_alignment_20260924'/'warmup'
FIELDS='date,code,open,high,low,close,preclose,volume,amount,turn,tradestatus,pctChg,isST'

def login():
    socket.setdefaulttimeout(20)
    result=bs.login()
    if result.error_code!='0':raise RuntimeError(result.error_msg)

def download(symbol):
    result={'symbol':symbol}
    for kind,flag in [('raw','3'),('qfq','2')]:
        dest=OUT/kind/(symbol+'.parquet')
        if dest.exists():
            try:
                result[kind]=len(pd.read_parquet(dest));continue
            except Exception:
                pass  # Interrupted generated cache is repaired by redownloading.
        for attempt in range(3):
            try:
                query=bs.query_history_k_data_plus(symbol[-2:].lower()+'.'+symbol[:6],FIELDS,
                    start_date='2015-01-01',end_date='2018-01-10',frequency='d',adjustflag=flag)
                if query.error_code!='0':raise RuntimeError(query.error_msg)
                frame=query.get_data()
                if query.error_code!='0':raise RuntimeError(query.error_msg)
                for c in ('open','high','low','close','preclose','volume','amount','turn','pctChg'):frame[c]=pd.to_numeric(frame[c],errors='coerce')
                frame['date']=pd.to_datetime(frame.date)
                frame.to_parquet(dest,index=False);result[kind]=len(frame);break
            except Exception as e:
                if attempt==2:return dict(symbol=symbol,error=str(e))
                # Re-authenticate on retry; never silently accept missing history.
                login()
                time.sleep(1+attempt)
    return result

def main():
    for kind in ('raw','qfq'):(OUT/kind).mkdir(parents=True,exist_ok=True)
    meta=pd.read_csv(bt.DATA/'metadata/historical_mainboard_universe.csv',dtype=str)
    universe=set(bt.load_universe())
    symbols=sorted(meta.loc[meta.symbol.isin(universe)&(meta.ipoDate<'2018-01-01'),'symbol'].unique())
    print('WARMUP symbols',len(symbols),flush=True)
    results=[]
    with ProcessPoolExecutor(max_workers=1,initializer=login) as pool:
        futures=[pool.submit(download,s) for s in symbols]
        for f in as_completed(futures):
            results.append(f.result())
            if len(results)%100==0:
                (OUT/'progress.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
                print('WARMUP',len(results),'/',len(symbols),'errors',sum('error' in r for r in results),flush=True)
    (OUT/'manifest.json').write_text(json.dumps(dict(source='BaoStock history API',start='2015-01-01',end='2018-01-10',results=results),ensure_ascii=False,indent=2),encoding='utf-8')
    assert all('error' not in r for r in results),'Warmup download errors: inspect manifest, rerun resumably'
    print('WARMUP DONE',len(results),flush=True)

if __name__=='__main__':main()
