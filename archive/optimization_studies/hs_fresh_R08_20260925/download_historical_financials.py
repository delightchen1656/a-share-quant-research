"""Bounded 98-symbol financial data download, one request/sec, no retries/bypass."""
import datetime,hashlib,json,time
from pathlib import Path
import requests
from probe_public_fundamentals import QUERIES
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'public_sources/historical_financials'

def main():
    OUT.mkdir(exist_ok=True)
    holdings=json.loads((ROOT/'public_sources/dividend_holdings_2019.json').read_text(encoding='utf-8'))
    symbols=sorted(x['symbol'] for x in holdings['rows'])
    _,url,template=QUERIES[1]
    audit=[];failures=0
    for n,symbol in enumerate(symbols):
        dest=OUT/(symbol+'.json');meta=OUT/(symbol+'_audit.json')
        if dest.exists() and meta.exists():
            audit.append(json.loads(meta.read_text(encoding='utf-8')));continue
        params=dict(template,filter='(SECUCODE="%s")'%symbol)
        try:
            response=requests.get(url,params=params,timeout=25)
            response.raise_for_status();data=response.json()
            rows=(data.get('result') or {}).get('data') or []
            if data.get('success') is False:raise ValueError(str(data.get('message')))
            dest.write_bytes(response.content)
            item=dict(symbol=symbol,url=response.url,rows=len(rows),
                retrieved=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                sha256=hashlib.sha256(response.content).hexdigest(),
                classification='raw current-vintage historical financials; NOT original-vintage PIT; must use strictly after max(NOTICE_DATE,UPDATE_DATE), audit missing dates; no latest values backfill')
            meta.write_text(json.dumps(item,indent=2),encoding='utf-8');audit.append(item);failures=0
            print('DOWNLOADED',n+1,len(symbols),symbol,len(rows),flush=True)
        except Exception as error:
            failures+=1;print('FAIL',symbol,type(error).__name__,str(error),flush=True)
            if failures>=3:raise RuntimeError('Three consecutive failures: stop, do not bypass')
        time.sleep(1)
    (OUT/'download_summary.json').write_text(json.dumps(dict(expected=symbols,downloaded=audit,
        missing=sorted(set(symbols)-{x['symbol'] for x in audit})),indent=2),encoding='utf-8')

if __name__=='__main__':main()
