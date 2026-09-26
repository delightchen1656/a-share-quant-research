"""Small public data probe. Raw responses only; NOT approved PIT factor data."""
import datetime,hashlib,json
from pathlib import Path
import requests
HERE=Path(__file__).resolve().parent/'public_sources/fundamental_probe'
QUERIES=[('valuation_600036','https://datacenter-web.eastmoney.com/api/data/v1/get',
    dict(sortColumns='TRADE_DATE',sortTypes='-1',pageSize='5000',pageNumber='1',
         reportName='RPT_VALUEANALYSIS_DET',columns='ALL',source='WEB',client='WEB',filter='(SECURITY_CODE="600036")')),
    ('financial_600036','https://datacenter.eastmoney.com/securities/api/data/get',
    dict(type='RPT_F10_FINANCE_MAINFINADATA',sty='APP_F10_MAINFINADATA',quoteColumns='',
         filter='(SECUCODE="600036.SH")',p='1',ps='200',sr='-1',st='REPORT_DATE',source='HSF10',client='PC'))]

if __name__=='__main__':
    HERE.mkdir(exist_ok=True,parents=True)
    for name,url,params in QUERIES:
        dest=HERE/(name+'.json')
        if dest.exists():print('EXISTS',name,flush=True);continue
        try:
            response=requests.get(url,params=params,timeout=25)
            response.raise_for_status()
            data=response.json();dest.write_bytes(response.content)
            rows=(data.get('result') or {}).get('data') or []
            audit=dict(url=response.url,retrieved=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                sha256=hashlib.sha256(response.content).hexdigest(),rows=len(rows),
                fields=list(rows[0]) if rows else [],status='unvalidated; source historical revisions and release timestamps must be audited')
            (HERE/(name+'_audit.json')).write_text(json.dumps(audit,indent=2),encoding='utf-8')
            print(json.dumps(audit),flush=True)
        except Exception as error:
            print('FAILED',name,type(error).__name__,str(error),flush=True)
