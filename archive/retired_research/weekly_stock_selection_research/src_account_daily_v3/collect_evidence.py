"""Cover changed development holdings, never refresh original daily prices."""
import json
from common import AUDIT,sha,dump,install_development_guard
import company_data as company
from portfolio import Quotes

def main():
    install_development_guard()
    inv=json.loads((AUDIT/'held_year_inventory.json').read_text(encoding='utf-8'))
    missing=inv['missing']
    assert all(int(y)<=2023 for _,y in missing)
    collection=json.loads((AUDIT/'company_collection_audit.json').read_text(encoding='utf-8'))
    records={(r['symbol'],r['year']):r for r in collection['sources']}
    network=[]
    for s,y in missing:
        p=company.STORE/f'{s}_{y}.parquet';a=company.STORE/f'{s}_{y}.json'
        if p.is_file() and a.is_file():
            r=json.loads(a.read_text(encoding='utf-8'))
            if r.get('ok') and r['sha256']==sha(p):
                records[s,y]=r
                continue
        network.append((s,y))
    print('Additional local-cache records:',len(missing)-len(network),'provider queries:',len(network),flush=True)
    if network:
        company.initialize()
        try:
            for j,task in enumerate(network,1):
                r=company.query(task)
                assert r['ok'],r
                records[task]=r
                print('Development company evidence query',j,'/',len(network),flush=True)
        finally:
            company.UPDATER.bs.logout()
    sources=list(records.values())
    dump(AUDIT/'company_collection_audit.json',dict(requested=len(sources),successful=sum(r['ok'] for r in sources),
        failed=[r for r in sources if not r['ok']],sources=sources,additional_development_held_years=len(missing),
        reused_same_project_provider_cache=True,not_certified_complete_company_action_history=True))
    events=company.normalize(sources,quotes=Quotes())
    dump(AUDIT/'company_events_conditional.json',events)
    print('Development company inventory and normalized events complete.',flush=True)

if __name__=='__main__':main()
