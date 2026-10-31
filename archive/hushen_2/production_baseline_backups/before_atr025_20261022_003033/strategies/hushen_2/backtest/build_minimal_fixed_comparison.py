"""Compare minimal fixed-quantity IOC accounts against retained original baseline."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import pandas as pd
from run_june2020_starts import BASE
from build_original_start_comparison import inspect_run


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',type=Path,nargs=4);args=parser.parse_args()
    previous=BASE/'results/holdout_restricted/original_execution_all_start_groups/attempt_20261020_034211/FULL_COMPARISON.json'
    baseline=json.loads(previous.read_text(encoding='utf-8'))
    assert baseline['status']=='ok'
    rows=[];deltas=[]
    for directory,old in zip(args.directories,baseline['groups']):
        new=inspect_run(directory,allow_fixed_ioc=True)
        assert new['group']==old['group'] and new['start_count']==old['start_count']
        rows.extend([dict(old,variant='original_baseline'),dict(new,variant='only_fixed_quantity_and_ioc')])
        deltas.append({'group':new['group'],'annualized_return_change_pp':100*(new['annualized_return_mean']-old['annualized_return_mean']),
            'maximum_drawdown_change_pp':100*(new['maximum_drawdown_mean']-old['maximum_drawdown_mean'])})
    out=BASE/'results/holdout_restricted/baseline_fixed_ioc_all_start_groups'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(rows).to_csv(out/'FULL_COMPARISON.csv',index=False,encoding='utf-8-sig')
    report={'status':'ok','end':'2026-10-19','baseline_source':str(previous),'groups':rows,'changes':deltas,
        'scope':'Only fixed pre-submitted buy quantity and IOC; original frozen signals, mixed ATR, budget, prices, costs, timing, and 37-day maturity tail retained',
        'limitation':'Original OHLC, 2% daily buy volume and slippage proxy; no five-level order-book reconstruction',
        'production_strategy_changed':False,'production_account_changed':False}
    (out/'FULL_COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Output',out,flush=True);print(json.dumps(report,ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__':main()
