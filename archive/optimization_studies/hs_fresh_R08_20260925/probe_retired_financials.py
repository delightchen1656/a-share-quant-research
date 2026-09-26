"""Check historical retired issuers explicitly; no retries or bypass."""
import hashlib,json,time
from pathlib import Path
import requests
from probe_public_fundamentals import QUERIES
OUT=Path(__file__).resolve().parent/'public_sources/retired_financial_probe'

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    _,url,template=QUERIES[1]
    for symbol in ('600068.SH','600069.SH','000005.SZ'):
        path=OUT/(symbol+'.json')
        if path.exists():data=json.loads(path.read_text(encoding='utf-8'))
        else:
            response=requests.get(url,params=dict(template,filter='(SECUCODE="%s")'%symbol),timeout=25)
            response.raise_for_status();data=response.json();path.write_bytes(response.content)
            path.with_name(symbol+'_audit.json').write_text(json.dumps(dict(url=response.url,
                sha256=hashlib.sha256(response.content).hexdigest()),indent=2),encoding='utf-8')
            time.sleep(1)
        rows=(data.get('result') or {}).get('data') or []
        print(symbol,'rows',len(rows),'success',data.get('success'),'message',data.get('message'),flush=True)
