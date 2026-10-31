"""Verify four new replays and compare with retained pending-slot next-open runs."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from compute_risk_metrics import recompute_metrics

BASE=Path(__file__).resolve().parents[1]
OLD=BASE/'results/holdout_restricted/manual_expiry_open_order_counts/attempt_20261020_044732/ORDER_COUNTS.json'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',nargs=4,type=Path);args=parser.parse_args()
    old_report=json.loads(OLD.read_text(encoding='utf-8'))
    old_by_range={tuple(x['start_range']):x for x in old_report['groups']}
    output=[]
    for directory in args.directories:
        summary=json.loads((directory/'SUMMARY.json').read_text(encoding='utf-8'))
        protocol=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
        assert summary['status']=='complete' and not summary['corporate_action_gaps']
        assert protocol['mode']=='fixed_quantity_ioc_filled_slots_daily_priority'
        assert protocol['execution_policy']['manual_expiry_open'] is True
        key=tuple(summary['start_range']);old_counts=old_by_range[key];old_dir=Path(old_counts['source_directory'])
        previous=json.loads((old_dir/'SUMMARY.json').read_text(encoding='utf-8'))
        assert previous['status']=='complete' and previous['end']==summary['end']
        assert previous['runs']==summary['runs']==old_counts['starts']
        assert digest(directory/'FROZEN_SIGNALS.parquet')==digest(old_dir/'FROZEN_SIGNALS.parquet')
        for filename,expected in old_counts['source_sha256'].items():assert digest(old_dir/filename)==expected
        for path,expected in protocol['source_hashes'].items():assert digest(BASE.parents[1]/path)==expected
        for receipt in protocol['action_sources'].get('fixed_ioc_missing_key_receipts',[]):
            assert digest(BASE.parents[1]/receipt['path'])==receipt['sha256']
        attempts=pd.read_parquet(directory/'FIXED_ORDER_ATTEMPTS.parquet')
        trades=pd.read_parquet(directory/'TRADES.parquet')
        curves=pd.read_parquet(directory/'EQUITY_CURVES.parquet')
        metrics=recompute_metrics(curves);n=summary['runs']
        assert len(metrics)==n
        for saved,column in [('annualized_return_mean','annualized_return'),('cumulative_return_mean','cumulative_return'),
                             ('maximum_drawdown_mean','maximum_drawdown'),('sharpe_mean','sharpe_zero_rf_252_ddof0')]:
            np.testing.assert_allclose(summary[saved],metrics[column].mean(),rtol=0,atol=1e-12)
        assert not summary['terminal_open_positions_max'] and not summary['terminal_pending_orders_max']
        assert len(trades)/n==summary['completed_trades_mean']==summary['filled_orders_mean']
        assert attempts.filled_quantity.gt(0).sum()/n==summary['filled_orders_mean']
        assert attempts.filled_quantity.eq(0).sum()/n==summary['failed_trigger_orders_mean']
        np.testing.assert_allclose(summary['filled_orders_mean']+summary['unfilled_orders_mean'],summary['pending_orders_created_mean'],rtol=0,atol=1e-12)
        for reason in ['take','stop','expiry']:
            assert trades.reason.eq(reason).sum()/n==summary[reason+'_count_mean']
        failed=attempts.loc[attempts.filled_quantity.eq(0)]
        failure_means={str(k):int(v)/n for k,v in failed.status.value_counts().items()}
        assert failure_means.get('no_slot_rejected',0)==summary['no_slot_trigger_orders_mean']
        assert failure_means.get('insufficient_cash_rejected',0)==summary['insufficient_cash_trigger_orders_mean']
        # The source records capture the resource state actually used for each fill.
        filled=attempts.loc[attempts.filled_quantity.gt(0)]
        assert attempts.requested_quantity.mod(100).eq(0).all()
        assert filled.occupied_slots_before.lt(5).all()
        assert (attempts.occupied_slots_before.le(5)).all()
        rows=[]
        for label,s,counts,failures in [('previous_pending_slots',previous,old_counts['means'],old_counts['trigger_failure_status_means']),
            ('new_filled_slots',summary,{k.removesuffix('_mean'):v for k,v in summary.items() if k.endswith('_mean')},failure_means)]:
            row=dict(version=label,start_range=list(key),starts=n,end=s['end'])
            for name in ['cumulative_return_mean','cumulative_return_median','annualized_return_mean','annualized_excess_mean',
                         'beat_sse_fraction','maximum_drawdown_mean','sharpe_mean']:row[name]=s[name]
            row.update({k:counts[k] for k in ['filled_orders','completed_trades','pending_orders_created','expired_entry_orders',
                'failed_trigger_orders','partial_fill_orders','take_count','stop_count','expiry_count','unfilled_orders']})
            row['trigger_failure_status_means']=failures
            rows.append(row)
        output.append(dict(start_range=list(key),previous=rows[0],new=rows[1],
            changes=dict(annualized_return_pp=100*(summary['annualized_return_mean']-previous['annualized_return_mean']),
                maximum_drawdown_pp=100*(summary['maximum_drawdown_mean']-previous['maximum_drawdown_mean']),
                sharpe=summary['sharpe_mean']-previous['sharpe_mean']),
            source_directory=str(directory.resolve()),previous_directory=str(old_dir),
            source_sha256={p.name:digest(p) for p in [directory/'SUMMARY.json',directory/'PROTOCOL.json',
                directory/'FIXED_ORDER_ATTEMPTS.parquet',directory/'TRADES.parquet',directory/'EQUITY_CURVES.parquet']}))
    assert len({tuple(x['start_range']) for x in output})==4
    out=BASE/'results/holdout_restricted/filled_slots_vs_pending_slots'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='verified',units='Equal-weight means across alternative account starts, not pooled account totals',
        limitation='Daily OHLC trigger-priority approximation; 37 calendar-day signal cutoff retained; no new end-tail signals; no production changes',
        previous_count_report=str(OLD),previous_report_sha256=digest(OLD),verification_script_sha256=digest(Path(__file__)),groups=output)
    (out/'COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True)
    for group in output:
        for row in [group['previous'],group['new']]:print(json.dumps(row,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
