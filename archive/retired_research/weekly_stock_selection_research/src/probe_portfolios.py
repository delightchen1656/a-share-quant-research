import json
import pandas as pd
from common import AUDIT,SPEC,dump,sha
from portfolio import Quotes,simulate


def main():
    scores=pd.read_parquet(AUDIT/'selection_scores_top30.parquet')
    quotes=Quotes()
    requests=set()
    exceptions=[]
    for method in SPEC['methods']:
        result=simulate(method['id'],scores,quotes,[])
        requests.update(tuple(x) for x in result['requested'])
        exceptions.extend(dict(method=method['id'],**x) for x in result['bad'])
        print('accounting evidence inventory',method['id'],'stockyears',len(result['requested']),flush=True)
    dump(AUDIT/'company_query_requests.json',dict(requests=[list(x) for x in sorted(requests)],
         purpose='Evidence inventory only; no valid economic account performance asserted before actual actions admitted',
         fixed_selection_sha256=sha(AUDIT/'selection_scores_top30.parquet')))
    dump(AUDIT/'reference_exceptions_before_event_evidence.json',exceptions)
    print('unique company stock-year evidence queries',len(requests),flush=True)


if __name__=='__main__':
    main()
