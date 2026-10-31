"""Pair already verified original and ATR025 account summaries; no simulation writes."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from test_atr_thresholds_pre2025 import BASE,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path,required=True);parser.add_argument('--filtered',type=Path,required=True);args=parser.parse_args()
    original=json.loads(args.baseline.read_text(encoding='utf-8'));filtered=json.loads(args.filtered.read_text(encoding='utf-8'))
    assert original['status']==filtered['status']=='verified'
    assert original['benchmark_sha256']==filtered['benchmark_sha256']
    old={r['group']:r for r in original['rows']};new={r['group']:r for r in filtered['rows']};assert old.keys()==new.keys() and len(old)==9
    fields=['annualized_return_mean','annualized_excess_mean','maximum_drawdown_mean','sharpe_mean','filled_orders_mean','unfilled_orders_mean','take_count_mean','stop_count_mean','expiry_count_mean','beat_benchmark_fraction']
    rows=[]
    for group in old:
        a,b=old[group],new[group]
        assert a['start_count']==b['start_count'] and a['end']==b['end']
        assert abs(a['benchmark_annualized_return_mean']-b['benchmark_annualized_return_mean'])<1e-12
        rows.append(dict(group=group,start_count=a['start_count'],end=a['end'],original=a,atr025=b,difference={k:b[k]-a[k] for k in fields}))
    out=BASE/'results/holdout_restricted/atr025_vs_original_annual'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=False)
    report=dict(status='verified',rows=rows,source_files={str(p.resolve()):digest(p) for p in [args.baseline,args.filtered]},
        comparison='Same starts/end/account execution/frozen model/signal source/benchmark; only original top3 ATR>=2.5% filter differs; not independent blind research',production_changed=False)
    (out/'COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OUTPUT',out)
    for r in rows:
        print(r['group'],json.dumps({k:[r['original'][k],r['atr025'][k]] for k in fields},ensure_ascii=False))


if __name__=='__main__':main()
