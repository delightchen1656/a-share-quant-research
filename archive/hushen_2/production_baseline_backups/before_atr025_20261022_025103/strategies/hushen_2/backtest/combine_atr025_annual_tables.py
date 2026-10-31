"""Combine separately audited pre/post-2025 groups using one benchmark vintage."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import numpy as np
import pandas as pd
from test_atr_thresholds_pre2025 import BASE,digest


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pre',type=Path,required=True);parser.add_argument('--post',type=Path,required=True);args=parser.parse_args()
    pre=args.pre.resolve();post=args.post.resolve()
    pre_check=json.loads((pre/'INDEPENDENT_VERIFICATION.json').read_text(encoding='utf-8'))
    post_report=json.loads((post/'SUMMARY.json').read_text(encoding='utf-8'))
    post_check=json.loads((post/'INDEPENDENT_VERIFICATION.json').read_text(encoding='utf-8'))
    assert pre_check['status']==post_report['status']==post_check['status']=='verified'
    index=pd.read_parquet(post/'SSE_PRICE_INDEX.parquet').set_index('date').close
    old_index=pd.read_parquet(pre/'SSE_INDEX.parquet').set_index('date').close
    overlap=old_index.to_frame('old').join(index.rename('new'),how='inner')
    assert len(overlap)==len(old_index)
    max_bench_difference=float((overlap.old-overlap.new).abs().max())
    rows=[];sources={};max_pre_benchmark_change=0.
    cases=[(str(y),pre/str(y),False) for y in range(2020,2025)]+[(key,post/key,True) for key in ['2025','2026','2020_to_current','2025_to_current']]
    for name,folder,is_post in cases:
        p=folder/'START_METRICS.parquet';m=pd.read_parquet(p)
        assert m.end_date.nunique()==1
        bench=np.array([(float(index.loc[pd.Timestamp(r.end_date)]/index.loc[pd.Timestamp(r.start_date)]))**(365/(pd.Timestamp(r.end_date)-pd.Timestamp(r.start_date)).days)-1 for r in m.itertuples()])
        if not is_post:max_pre_benchmark_change=max(max_pre_benchmark_change,float(np.abs(m.benchmark_annualized_return.to_numpy()-bench).max()))
        else:assert np.allclose(m.benchmark_annualized,bench,atol=1e-12,rtol=0)
        assert np.allclose(m.filled_orders,m.take_count+m.stop_count+m.expiry_count+m.open_positions_at_end,rtol=0,atol=0)
        assert np.allclose(m.pending_orders_created,m.filled_orders+m.unfilled_orders+m.pending_orders_at_end,rtol=0,atol=0)
        assert m.open_positions_at_end.eq(0).all() and m.pending_orders_at_end.eq(0).all()
        row=dict(group=name,start_count=len(m),end=str(m.end_date.iloc[0]),
            cumulative_return_mean=float(m.cumulative_return.mean()),annualized_return_mean=float(m.annualized_return.mean()),
            benchmark_annualized_return_mean=float(bench.mean()),annualized_excess_mean=float((m.annualized_return.to_numpy()-bench).mean()),
            beat_benchmark_fraction=float((m.annualized_return.to_numpy()>bench).mean()),
            maximum_drawdown_mean=float(m.maximum_drawdown.mean()),sharpe_mean=float(m.sharpe_zero_rf_252_ddof0.mean()),
            **{key+'_mean':float(m[key].mean()) for key in ['filled_orders','unfilled_orders','take_count','stop_count','expiry_count']})
        rows.append(row);sources[str(p)]=digest(p)
    assert len(rows)==9 and sum(r['start_count'] for r in rows)==519
    out=BASE/'results/holdout_restricted/atr025_requested_tables'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S');out.mkdir(parents=True,exist_ok=False)
    report=dict(status='verified',rows=rows,statistics='Equal-start arithmetic means; each path separately computes account CAGR/drawdown/Sharpe. Excess is strategy CAGR minus SSE price-index CAGR, same start/end.',
        benchmark='Single new BaoStock SSE price-index vintage for all nine rows',
        benchmark_audit=dict(old_new_overlap_rows=len(overlap),maximum_close_revision_points=max_bench_difference,
            maximum_pre2025_benchmark_annualized_revision=max_pre_benchmark_change,
            note='Only normalize benchmark/excess/beat fraction in combined presentation; preserve original reports, account curves and trade data.'),
        execution='ATR>=2.5% on original daily top3; no refill; 5slots; 100000 initial; price TR; fixed IOC; 2% capacity; original expiry close; final37 calendar day no-order tail',
        unfilled='Whole orders with zero actual fills, including trigger failure or entry expiry; partial-fill orders count as filled.',
        source_metrics_sha256=sources,verification_files={str(p):digest(p) for p in [pre/'INDEPENDENT_VERIFICATION.json',post/'INDEPENDENT_VERIFICATION.json']},
        benchmark_file=str(post/'SSE_PRICE_INDEX.parquet'),benchmark_sha256=digest(post/'SSE_PRICE_INDEX.parquet'),production_changed=False)
    (out/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('OUTPUT',out);print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
