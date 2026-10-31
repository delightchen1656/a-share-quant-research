from concurrent.futures import ProcessPoolExecutor
import json
import pandas as pd
from common import BASE,AUDIT,SPEC,dump,sha,install_development_guard
from portfolio import Quotes,simulate
from company_data import STORE,query,initialize,normalize


def collect(requests):
    found=[]
    missing=[]
    for symbol,year in requests:
        assert 2021<=year<=2023
        data=STORE/f'{symbol}_{year}.parquet'
        audit=STORE/f'{symbol}_{year}.json'
        if data.exists() and audit.exists():
            meta=json.loads(audit.read_text(encoding='utf-8'))
            if meta.get('ok') and sha(data)==meta['sha256']:
                found.append(meta)
                continue
        missing.append((symbol,year))
    print('Evidence cache hits',len(found),'additional historical queries',len(missing),flush=True)
    if missing:
        with ProcessPoolExecutor(max_workers=6,initializer=initialize) as pool:
            for i,result in enumerate(pool.map(query,missing,chunksize=8),1):
                found.append(result)
                if i%50==0:print('additional company evidence',i,'/',len(missing),flush=True)
    return sorted(found,key=lambda r:(r['symbol'],r['year']))


def main():
    install_development_guard()
    assert json.loads((AUDIT/'minimum_checks.json').read_text(encoding='utf-8'))['passed']
    scores=pd.read_parquet(AUDIT/'scores.parquet')
    events=json.loads((BASE/'audits/holdout_restricted/research_v1/company_events_conditional.json').read_text(encoding='utf-8'))
    quotes=Quotes()
    requested=set()
    previous=None
    for iteration in range(1,4):
        for method in ['long120','anchor11']:
            result=simulate(method,scores,quotes,events)
            requested.update(tuple(x) for x in result['requested'])
        dump(AUDIT/'company_query_requests.json',dict(requests=[list(x) for x in sorted(requested)],evidence_inventory_only=True,no_performance_reported_before_evidence=True))
        if requested==previous:
            break
        records=collect(sorted(requested))
        dump(AUDIT/'company_collection_audit.json',dict(requested=len(requested),successful=sum(r['ok'] for r in records),failed=[r for r in records if not r['ok']],
            sources=records,scope='same-project independent raw provider cache, not other strategy ledger',zero_rows_not_completeness_proof=True))
        events=normalize(records,quotes=quotes)
        dump(AUDIT/'company_events_conditional.json',events)
        previous=requested.copy()
    else:
        raise RuntimeError('Held-year evidence did not stabilize in3iterations')
    assert all(r['ok'] for r in records),'Missing company evidence remains unsupported'
    print('Held-year evidence stabilized; conditional events',len(events),flush=True)


if __name__=='__main__':
    main()
