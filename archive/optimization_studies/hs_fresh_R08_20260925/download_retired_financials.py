"""Recover all 199 historically retired mainboard issuers via public F10 reports."""
import datetime,hashlib,json,time
import pandas as pd
import requests
import research as r
from probe_public_fundamentals import QUERIES
OUT=r.HERE/'public_sources/retired_financial_probe'

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    u=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    symbols=sorted(u.loc[u.outDate.notna(),'symbol']);assert len(symbols)==199
    _,url,template=QUERIES[1];audit=[]
    for i,symbol in enumerate(symbols):
        path=OUT/(symbol+'.json');meta=OUT/(symbol+'_audit.json')
        if path.exists() and meta.exists():
            raw=path.read_bytes();item=json.loads(meta.read_text(encoding='utf-8'))
            assert hashlib.sha256(raw).hexdigest()==item['sha256'];data=json.loads(raw)
        else:
            response=requests.get(url,params=dict(template,filter='(SECUCODE="%s")'%symbol),timeout=25)
            response.raise_for_status();data=response.json()
            assert data.get('success') is not False,data.get('message')
            item=dict(url=response.url,sha256=hashlib.sha256(response.content).hexdigest(),
                retrieved=datetime.datetime.now(datetime.timezone.utc).isoformat())
            path.write_bytes(response.content);meta.write_text(json.dumps(item,indent=2),encoding='utf-8');time.sleep(1)
        rows=(data.get('result') or {}).get('data') or []
        audit.append(dict(symbol=symbol,rows=len(rows),**item))
        print('RETIRED',i+1,len(symbols),symbol,len(rows),flush=True)
    r.save(OUT/'download_summary.json',dict(expected=symbols,downloaded=audit,
        empty=[x['symbol'] for x in audit if x['rows']==0],
        warning='F10 current-vintage, no EITIME in schema; max notice/update available conservative approximation, original filing audit still required'))
