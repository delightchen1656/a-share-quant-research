"""Verify and compile comparable fixed-quantity IOC daily-proxy start groups."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import pandas as pd
from run_june2020_starts import BASE, ROOT
from verify_start_replay import main as verify_replay
import sys
sys.path.insert(0,str(BASE/'tracker'))
from market import digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',type=Path,nargs='+');args=parser.parse_args()
    summaries=[];fingerprint=None;sources=[]
    for directory in args.directories:
        verify_replay(directory)
        protocol=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
        assert protocol['execution_mode']=='broker_fixed_quantity_ioc_daily_approximation'
        signature={k:protocol[k] for k in ['strategy','end','initial_cash','slots','last_signal_cutoff_calendar',
            'execution_atr_policy','broker_policy','execution_code_hashes','pipeline_id']}
        if fingerprint is None:fingerprint=signature
        else:assert signature==fingerprint,'Cannot combine different execution policies or input pipelines'
        metrics=pd.read_csv(directory/'START_METRICS.csv')
        first=pd.Timestamp(metrics.start_date.iloc[0])
        group='2020年6月' if first.year==2020 and first.month==6 else f'{first.year}年Q1'
        summaries.append(dict(group=group,start_count=len(metrics),
            cumulative_return_mean=float(metrics.cumulative_return.mean()),cumulative_return_median=float(metrics.cumulative_return.median()),
            annualized_return_mean=float(metrics.annualized_return.mean()),annualized_return_median=float(metrics.annualized_return.median()),
            annualized_excess_mean=float(metrics.annualized_excess.mean()),positive_start_fraction=float(metrics.cumulative_return.gt(0).mean()),
            beat_sse_fraction=float(metrics.beat_sse.mean()),maximum_drawdown_mean=float(metrics.maximum_drawdown.mean()),
            sharpe_mean=float(metrics.sharpe.mean()),take_count_mean=float(metrics.take_count.mean()),stop_count_mean=float(metrics.stop_count.mean()),
            expiry_count_mean=float(metrics.expiry_count.mean()),terminal_open_positions_mean=float(metrics.open_positions.mean()),
            terminal_pending_orders_mean=float(metrics.pending_orders.mean())))
        sources.append({'directory':str(directory),'files':{name:digest(directory/name) for name in ['PROTOCOL.json','SUMMARY.json','START_METRICS.csv','INDEPENDENT_VERIFICATION.json']}})
    out=BASE/'results/holdout_restricted/broker_ioc_all_start_groups'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(summaries).to_csv(out/'FULL_COMPARISON.csv',index=False,encoding='utf-8-sig')
    report={'status':'ok','shared_protocol':fingerprint,'groups':summaries,'sources':sources,
        'exit_count_unit':'Sell execution legs; partial exits counted separately',
        'limitations':'Daily volume 2% and slippage proxy, not historical order-book reconstruction; one-shot conditional parent assumed, broker parent retrigger rule unverified',
        'production_account_changed':False,'production_strategy_changed':False}
    (out/'FULL_COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Output',out,flush=True);print(json.dumps(summaries,ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__':main()
