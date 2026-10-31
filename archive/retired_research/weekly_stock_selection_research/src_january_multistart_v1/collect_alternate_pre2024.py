"""Bounded public corporate-event queries, separate from protected market prices."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import datetime
import json
import time
import requests
from common import BASE,AUDIT,sha,dump,install_development_guard

STORE=BASE/'inputs_pre2025/corporate_eastmoney_january_v1'
URL='https://datacenter-web.eastmoney.com/api/data/v1/get'
COLS='SECURITY_CODE,SECUCODE,SECURITY_NAME_ABBR,BONUS_IT_RATIO,BONUS_RATIO,IT_RATIO,PRETAX_BONUS_RMB,EQUITY_RECORD_DATE,EX_DIVIDEND_DATE,REPORT_DATE,ASSIGN_PROGRESS,IMPL_PLAN_PROFILE,NOTICE_DATE'

def query(task):
    symbol,year=task
    assert 2018<=year<=2023
    target=STORE/f'{symbol}_{year}.json';meta=STORE/f'{symbol}_{year}.meta.json'
    if target.exists() and meta.exists():
        r=json.loads(meta.read_text(encoding='utf-8'))
        if r.get('ok') and sha(target)==r['sha256']:return r
    params=dict(reportName='RPT_SHAREBONUS_DET',columns=COLS,
        filter=f'(SECURITY_CODE="{symbol[:6]}")(EX_DIVIDEND_DATE>=\'{year}-01-01\')(EX_DIVIDEND_DATE<=\'{year}-12-31\')',
        pageSize=100,pageNumber=1,source='WEB',client='WEB')
    error=None
    for attempt in range(2):
        try:
            response=requests.get(URL,params=params,timeout=20)
            response.raise_for_status();payload=response.json()
            result=payload.get('result')
            if result is None:
                assert payload.get('message')=='返回数据为空',payload.get('message')
                rows=[]
            else:
                assert payload.get('success') and result.get('pages',1)<=1
                rows=result.get('data',[])
            for row in rows:
                assert row['SECURITY_CODE']==symbol[:6] and row['EX_DIVIDEND_DATE'].startswith(str(year))
            dump(target,dict(query=params,source_url=URL,data=rows,
                before2024_only=True,no_price_or_performance_fields_requested=True))
            r=dict(symbol=symbol,year=year,ok=True,rows=len(rows),sha256=sha(target),file=target.name,
                source='Eastmoney_public_bounded_event_table',queried_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                zero_rows_not_proof_of_complete_company_action_history=True,
                pay_and_listing_dates_require_primary_evidence_for_actual_entitlements=True)
            dump(meta,r);return r
        except Exception as exc:
            error=repr(exc)
            if attempt==0:time.sleep(.5)
    return dict(symbol=symbol,year=year,ok=False,error=error)

def main():
    install_development_guard();STORE.mkdir(parents=True,exist_ok=True)
    requests_=json.loads((AUDIT/'development_evidence_inventory.json').read_text(encoding='utf-8'))['missing']
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for n,r in enumerate(pool.map(query,requests_),1):
            records.append(r)
            if n%50==0:print('Bounded pre2024 event queries',n,'/',len(requests_),flush=True)
    dump(STORE/'manifest.json',dict(boundary_version='public-pre2025-v2',all_queries_end_before2024=True,
        purpose='Missing held-year event evidence only; never train on these event flags',files=records))
    dump(AUDIT/'alternate_company_collection.json',dict(sources=records,ok=sum(r['ok'] for r in records),
        failed=[r for r in records if not r['ok']],no_market_price_refresh=True))
    print('Alternate event sources:',sum(r['ok'] for r in records),'/',len(records),flush=True)

if __name__=='__main__':main()
