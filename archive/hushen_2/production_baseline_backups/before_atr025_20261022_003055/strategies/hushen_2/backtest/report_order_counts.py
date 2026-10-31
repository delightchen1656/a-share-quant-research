"""Reconcile order and exit counts from completed manual-expiry-open replays."""
import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
import pandas as pd


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('directories',nargs=4,type=Path)
    args=parser.parse_args()
    groups=[]
    for directory in args.directories:
        summary=json.loads((directory/'SUMMARY.json').read_text(encoding='utf-8'))
        protocol=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
        assert summary['status']=='complete' and not summary['corporate_action_gaps']
        assert protocol['mode']=='fixed_quantity_ioc_manual_next_session_expiry_open'
        with (directory/'START_METRICS.csv').open(encoding='utf-8-sig',newline='') as f:
            rows=list(csv.DictReader(f))
        attempts=pd.read_parquet(directory/'FIXED_ORDER_ATTEMPTS.parquet')
        trades=pd.read_parquet(directory/'TRADES.parquet')
        columns=['pending_orders_created','filled_orders','completed_trades','expired_entry_orders',
                 'failed_trigger_orders','partial_fill_orders','take_count','stop_count','expiry_count']
        totals={k:sum(int(r[k]) for r in rows) for k in columns}
        for row in rows:
            n=int(row['start_ordinal'])
            a=attempts[attempts.start_ordinal.eq(n)]
            t=trades[trades.start_ordinal.eq(n)]
            assert int(a.filled_quantity.gt(0).sum())==int(row['filled_orders'])
            assert int(a.filled_quantity.eq(0).sum())==int(row['failed_trigger_orders'])
            assert len(t)==int(row['completed_trades'])
            for reason in ('take','stop','expiry'):
                assert int(t.reason.eq(reason).sum())==int(row[reason+'_count'])
            assert sum(int(row[k]) for k in ('expired_entry_orders','failed_trigger_orders','filled_orders'))==int(row['pending_orders_created'])
            assert int(row['open_positions_at_end'])==int(row['pending_orders_at_end'])==0
        means={k:v/len(rows) for k,v in totals.items()}
        means['unfilled_orders']=means['expired_entry_orders']+means['failed_trigger_orders']
        totals['unfilled_orders']=totals['expired_entry_orders']+totals['failed_trigger_orders']
        failure_status_means={str(k):int(v)/len(rows) for k,v in attempts.loc[attempts.filled_quantity.eq(0),'status'].value_counts().items()}
        sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                 [directory/'START_METRICS.csv',directory/'FIXED_ORDER_ATTEMPTS.parquet',directory/'TRADES.parquet',directory/'PROTOCOL.json']}
        groups.append(dict(start_range=summary['start_range'],end=summary['end'],starts=len(rows),
            means=means,trigger_failure_status_means=failure_status_means,totals_across_alternative_paths=totals,source_directory=str(directory.resolve()),source_sha256=sources,
            annualized_return_mean=summary['annualized_return_mean']))
    root=Path(__file__).resolve().parents[1]
    out=root/'results/holdout_restricted/manual_expiry_open_order_counts'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    result=dict(status='verified',units='Mean count per alternative account start; not totals of one real account',
        policy='Fixed submitted shares, IOC, original mixed ATR and 2% daily buy capacity; expiry next-session open',groups=groups)
    (out/'ORDER_COUNTS.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True)
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':main()
