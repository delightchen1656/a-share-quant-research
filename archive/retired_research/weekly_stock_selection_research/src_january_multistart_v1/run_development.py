import os
os.environ['OMP_NUM_THREADS']='1';os.environ['OPENBLAS_NUM_THREADS']='1'
import json
from pathlib import Path
import pandas as pd
from common import BASE,AUDIT,sha,dump,install_development_guard
from portfolio import Quotes
from company_data import STORE,normalize
from multistart import evaluate

def main():
    install_development_guard()
    assert not (AUDIT/'development_summary.parquet').exists(),'Preserve completed runs'
    frozen=AUDIT/'frozen_engine_v1'
    reg=json.loads((frozen/'FREEZE_MANIFEST.json').read_text(encoding='utf-8'))
    for r in reg['files']:assert sha(frozen/r['path'])==r['sha256']
    scores=[]
    for year in range(2019,2024):
        f=pd.read_parquet(BASE/f'audits/holdout_restricted/monday_factor_v5/fold_scores_{year}.parquet')
        scores.append(f.loc[f.variant.eq('combine__long_momentum')&f['rank'].le(10)].assign(method='long120'))
    scores=pd.concat(scores,ignore_index=True)
    scores.to_parquet(AUDIT/'development_scores.parquet',index=False)
    plan=pd.read_parquet(BASE/'audits/holdout_restricted/research_v1/weekly_schedule.parquet')
    plan.to_parquet(AUDIT/'development_schedule.parquet',index=False)
    records=[]
    for path in sorted(STORE.glob('*.json')):
        r=json.loads(path.read_text(encoding='utf-8'))
        if not r.get('ok') or not 2018<=int(r.get('year',0))<=2023:continue
        target=STORE/f"{r['symbol']}_{r['year']}.parquet"
        assert target.exists() and sha(target)==r['sha256']
        records.append(r)
    dump(AUDIT/'development_company_collection.json',dict(sources=records,all_hashes_verified=True,only_pre2024=True))
    quotes=Quotes();events=normalize(records,quotes=quotes)
    alternate=[]
    if (AUDIT/'alternate_company_collection.json').exists():
        from alternate_events import events_from_sources
        alternate=json.loads((AUDIT/'alternate_company_collection.json').read_text(encoding='utf-8'))['sources']
        overrides=json.loads((AUDIT/'development_alternate_primary_overrides.json').read_text(encoding='utf-8'))
        events+=events_from_sources(alternate,overrides)
    dump(AUDIT/'development_company_events.json',events)
    results,summary,required=evaluate(scores,quotes,events,plan,range(2019,2024),'2023-12-31')
    covered={(r['symbol'],r['year']) for r in records+alternate if r.get('ok')}
    missing=sorted(set(map(tuple,required))-covered)
    problems={k:r['bad'] for k,r in results.items() if r['bad']}
    dump(AUDIT/'development_evidence_inventory.json',dict(required=required,missing=missing,exceptions=problems,
        all_accounts_replayed=len(results),independent_account_checks_passed=True,
        publishable=not missing and not problems))
    print('Development accounts replayed',len(results),'missing held-year sources',len(missing),
          'accounts with exceptions',len(problems),flush=True)
    if missing or problems:
        dump(AUDIT/'DEVELOPMENT_STATUS.json',dict(status='pending_company_action_evidence',missing_sources=len(missing),
            accounts_with_exceptions=len(problems),no_validated_results_published=True))
        return
    summary.to_parquet(AUDIT/'development_summary.parquet',index=False)
    summary.to_csv(AUDIT/'development_summary.csv',index=False,encoding='utf-8-sig')
    for key,name in [('daily','daily_nav'),('trades','trades'),('transactions','transactions'),('plans','preopen_plans'),('logs','execution_log')]:
        pd.concat([r[key].assign(account_id=k) for k,r in results.items()],ignore_index=True).to_parquet(AUDIT/f'development_{name}.parquet',index=False)
    dump(AUDIT/'development_terminal_inventory.json',{k:dict(positions=r['terminal_positions'],claims=r['claims']) for k,r in results.items()})
    dump(AUDIT/'DEVELOPMENT_STATUS.json',dict(status='complete',accounts=len(results),all_evidence_covered=True,
        independent_account_and_full_preopen_validation=True,no_posterior_read=True))
    print(summary[['year','start_date','account_return','maximum_drawdown','end_equity','fees']].to_string(index=False),flush=True)

if __name__=='__main__':main()
