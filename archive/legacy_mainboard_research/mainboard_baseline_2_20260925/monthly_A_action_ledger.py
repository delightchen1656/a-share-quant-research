"""Independent official-provider action records for large adjustment stock-years."""
from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path
import json
import time
import socket
import pandas as pd
import baostock as bs
import execution_engine as bt

OUT=Path(__file__).resolve().parent/'monthly_A_alignment_20260924'/'action_ledger'

def login():
    socket.setdefaulttimeout(20)
    r=bs.login()
    if r.error_code!='0':raise RuntimeError(r.error_msg)

def fetch(key):
    symbol,year=key;p=OUT/(symbol+'_'+year+'.json')
    if p.exists():return json.loads(p.read_text(encoding='utf-8'))
    for attempt in range(3):
        try:
            q=bs.query_dividend_data(symbol[-2:].lower()+'.'+symbol[:6],year=year,yearType='operate')
            if q.error_code!='0':raise RuntimeError(q.error_msg)
            frame=q.get_data()
            if q.error_code!='0':raise RuntimeError(q.error_msg)
            r=dict(symbol=symbol,year=year,rows=frame.to_dict('records'))
            p.write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8');return r
        except Exception as exc:
            if attempt==2:return dict(symbol=symbol,year=year,error=str(exc))
            login()
            time.sleep(1+attempt)

def main():
    OUT.mkdir(exist_ok=True);keys=set()
    for symbol in bt.load_universe():
        p=bt.raw_path(symbol)
        if not p.exists():continue
        x=pd.read_parquet(p,columns=['date','close','preclose']).sort_values('date')
        ratio=x.close.shift(1)/x.preclose
        x=x[(pd.to_datetime(x.date)>='2020-01-01')&((ratio>=1.05)|(ratio<=.95))]
        keys.update((symbol,str(d)[:4]) for d in x.date)
    print('LEDGER tasks',len(keys),flush=True);results=[]
    with ProcessPoolExecutor(max_workers=1,initializer=login) as pool:
        futures=[pool.submit(fetch,k) for k in sorted(keys)]
        for f in as_completed(futures):
            results.append(f.result())
            if len(results)%100==0:print('LEDGER',len(results),'/',len(keys),'errors',sum('error' in r for r in results),flush=True)
    (OUT/'manifest.json').write_text(json.dumps(dict(source='BaoStock query_dividend_data yearType=operate; selected by independent raw-price adjustment >=5% (or <=-5%), not by platform holdings',results=results),ensure_ascii=False,indent=2),encoding='utf-8')
    assert all('error' not in r for r in results)
    print('LEDGER DONE',len(results),flush=True)

if __name__=='__main__':main()
