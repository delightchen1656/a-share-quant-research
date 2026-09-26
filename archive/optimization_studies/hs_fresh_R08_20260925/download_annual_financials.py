"""Public paginated annual financials, cached raw responses, one request/sec."""
import datetime,hashlib,json,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'public_sources/annual_performance'

def main():
    OUT.mkdir(exist_ok=True)
    # Public batch performance-report endpoint documented by AKShare
    # stock_yjbb_em; F10 per-stock endpoint does not support REPORT_DATE filter.
    url='https://datacenter-web.eastmoney.com/api/data/v1/get';manifest=[]
    for year in range(2017,2026):
        page=1;rows=[];pages=1;expected=None
        while page<=pages:
            dest=OUT/('%d_%03d.json'%(year,page));meta=dest.with_name(dest.stem+'_audit.json')
            if dest.exists() and meta.exists():
                raw=dest.read_bytes();audit=json.loads(meta.read_text(encoding='utf-8'))
                assert hashlib.sha256(raw).hexdigest()==audit['sha256']
                data=json.loads(raw)
            else:
                params=dict(filter="(REPORTDATE='%d-12-31')"%year,pageNumber=str(page),pageSize='500',
                    sortColumns='SECURITY_CODE',sortTypes='1',reportName='RPT_LICO_FN_CPD',columns='ALL')
                response=requests.get(url,params=params,timeout=25)
                response.raise_for_status();data=response.json()
                assert data.get('success') is not False,data.get('message')
                assert data.get('result') and data['result'].get('data'),'Missing page: stop, no bypass'
                audit=dict(url=response.url,retrieved=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    sha256=hashlib.sha256(response.content).hexdigest())
                dest.write_bytes(response.content);meta.write_text(json.dumps(audit,indent=2),encoding='utf-8')
                time.sleep(1)
            result=data['result'];pages=int(result['pages']);expected=int(result['count'])
            assert 0<pages<=30,'Unexpected request scope; stop'
            rows.extend(result['data']);manifest.append(dict(year=year,page=page,**audit))
            print('PAGE',year,page,pages,len(rows),expected,flush=True);page+=1
        assert len(rows)==expected,(year,len(rows),expected)
        assert len({x['SECURITY_CODE'] for x in rows})==len(rows),'Duplicate symbols within report year'
        assert all(x['REPORTDATE'].startswith(str(year)+'-12-31') for x in rows)
    (OUT/'download_summary.json').write_text(json.dumps(dict(pages=manifest,
        status='Current-vintage data; requires conservative release/update lag and source audit, NOT approved PIT'),indent=2),encoding='utf-8')

if __name__=='__main__':main()
