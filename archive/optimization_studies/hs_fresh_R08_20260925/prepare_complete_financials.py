"""Supplement batch financials with explicitly labelled F10 retired histories."""
import hashlib,json
import pandas as pd
import research as r
import prepare_broad_financials as base

FEATURES=r.HERE/'features_broad_financials_complete.parquet'
DIRECTORY=r.HERE/'public_sources/retired_financial_probe'
MAP={'REPORTDATE':'REPORT_DATE','NOTICE_DATE':'NOTICE_DATE','UPDATE_DATE':'UPDATE_DATE',
     'WEIGHTAVG_ROE':'ROEJQ','PARENT_NETPROFIT':'PARENTNETPROFIT','TOTAL_OPERATE_INCOME':'TOTALOPERATEREVE',
     'MGJYXJJE':'MGJYXJJE','BASIC_EPS':'EPSJB','SJLTZ':'PARENTNETPROFITTZ'}

def convert(row):
    out={dest:row.get(source) for dest,source in MAP.items()}
    out.update(EITIME=None,_source_schema='F10')
    return out

def main():
    summary=json.loads((DIRECTORY/'download_summary.json').read_text(encoding='utf-8'))
    assert not summary['empty'],summary['empty']
    universe=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    retired=set(universe.loc[universe.outDate.notna(),'symbol'])
    assert set(summary['expected'])==retired
    supplement={}
    for item in summary['downloaded']:
        raw=(DIRECTORY/(item['symbol']+'.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        rows=json.loads(raw)['result']['data']
        assert all(x['SECUCODE']==item['symbol'] for x in rows)
        # Same report-year domain as batch data, no 2026 interim/new rows.
        supplement[item['symbol']]=[convert(x) for x in rows if x['REPORT_DATE'][:10] in
            {str(year)+'-12-31' for year in range(2017,2026)}]
    base.FEATURES=FEATURES
    base.main(supplement,dict(source_manifest_sha256=hashlib.sha256((DIRECTORY/'download_summary.json').read_bytes()).hexdigest(),
        symbols=len(supplement),no_annual_2017_2025=sorted(s for s,v in supplement.items() if not v),
        ingestion_time='not supplied by F10, remains missing; max NOTICE_DATE/UPDATE_DATE only for supplementary source',
        current_vintage_caveat='Mixed source and weaker retired timestamp evidence; exploratory only; original-filing validation gate remains false'))

if __name__=='__main__':main()
