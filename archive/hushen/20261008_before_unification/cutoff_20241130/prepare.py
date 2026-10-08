from pathlib import Path
import json, hashlib, socket
import pandas as pd
import pyarrow.parquet as pq
import baostock as bs

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'snapshot'
CUT=pd.Timestamp('2024-11-30')
COLS=['date','open','high','low','close','preclose','volume','amount','turn','tradestatus','isST']
def bounded(frame):
    x=frame.copy();x['date']=pd.to_datetime(x.date)
    return x.loc[x.date<CUT,COLS].sort_values('date').reset_index(drop=True)
def main():
    OUT.mkdir(parents=True,exist_ok=True);manifest=[]
    for path in sorted((ROOT/'sh_sz_market_research/data_pipeline/data/raw').rglob('*.parquet')):
        x=pq.read_table(path,columns=COLS,filters=[('date','<',CUT.to_pydatetime())]).to_pandas()
        x=bounded(x)
        if x.empty:continue
        assert x.date.max()<CUT and not x.date.duplicated().any()
        target=OUT/(path.stem+'.parquet');x.to_parquet(target,index=False)
        manifest.append(dict(symbol=path.stem,rows=len(x),first=str(x.date.min().date()),last=str(x.date.max().date()),sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    socket.setdefaulttimeout(40)
    login=bs.login();assert login.error_code=='0'
    r=bs.query_history_k_data_plus('sh.000905','date,close',start_date='2018-01-01',end_date='2024-11-29',frequency='d',adjustflag='3')
    rows=[]
    while r.error_code=='0' and r.next():rows.append(r.get_row_data())
    assert r.error_code=='0',r.error_msg
    b=pd.DataFrame(rows,columns=r.fields);b['date']=pd.to_datetime(b.date);b['close']=pd.to_numeric(b.close)
    assert b.date.max()==pd.Timestamp('2024-11-29')
    b.to_parquet(OUT/'benchmark.parquet',index=False);bs.logout()
    protocol=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest()
    report=dict(cutoff_exclusive=str(CUT.date()),maximum_observation_date=max(x['last'] for x in manifest),symbols=len(manifest),
        input_fields=COLS,protocol_sha256=protocol,files=manifest,benchmark_sha256=hashlib.sha256((OUT/'benchmark.parquet').read_bytes()).hexdigest())
    (HERE/'snapshot_manifest.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Bounded snapshot',len(manifest),report['maximum_observation_date'],flush=True)
if __name__=='__main__':main()
