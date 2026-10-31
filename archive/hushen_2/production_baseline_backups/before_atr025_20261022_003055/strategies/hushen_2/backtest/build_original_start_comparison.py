"""Independently verify saved original-execution replays and compile all start groups."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import numpy as np
import pandas as pd
from run_june2020_starts import ROOT, BASE, ARCHIVE
import sys
sys.path.insert(0,str(BASE/'tracker'))
from market import digest


def inspect_run(directory,allow_fixed_ioc=False):
    protocol=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
    minimal=protocol['mode']=='baseline_only_fixed_quantity_ioc'
    assert protocol['mode']=='original_frozen_inputs_and_original_execution_not_tracker' or (allow_fixed_ioc and minimal)
    m=pd.read_csv(directory/'START_METRICS.csv')
    c=pd.read_parquet(directory/'EQUITY_CURVES.parquet')
    t=pd.read_parquet(directory/'TRADES.parquet')
    index=pd.read_parquet(ARCHIVE/'results/holdout_restricted/batch_006_defense_post2024_audit/sh000001_holdout_index.parquet')
    index['date']=pd.to_datetime(index.date);close=index.set_index('date').close
    assert m.start_date.tolist()==protocol['starts']
    rows=[]
    for r in m.itertuples():
        g=c[c.start_ordinal.eq(r.start_ordinal)].sort_values('date');e=g.equity
        start=pd.Timestamp(r.start_date);end=pd.Timestamp(r.end_date)
        assert g.date.iloc[0]==start and g.date.iloc[-1]==end and not g.date.duplicated().any()
        daily=e.pct_change().fillna(e.iloc[0]/100000-1)
        cum=e.iloc[-1]/100000-1;annual=(1+cum)**(365/(end-start).days)-1
        drawdown=(e/e.cummax()-1).min();sharpe=np.sqrt(252)*daily.mean()/daily.std(ddof=0)
        np.testing.assert_allclose([cum,annual,drawdown,sharpe],[r.cumulative_return,r.annualized_return,r.maximum_drawdown,r.sharpe_zero_rf_252_ddof0],rtol=0,atol=1e-12)
        counts=t[t.start_ordinal.eq(r.start_ordinal)].reason.value_counts()
        assert set(counts.index)<={'take','stop','expiry'} and counts.sum()==r.completed_trades
        assert r.action_gap_count==0 and r.open_positions_at_end==0 and r.pending_orders_at_end==0
        bench=(float(close.loc[end]/close.loc[start]))**(365/(end-start).days)-1
        rows.append(dict(cumulative_return=float(cum),annualized_return=float(annual),annualized_excess=float(annual-bench),
            maximum_drawdown=float(drawdown),sharpe=float(sharpe),
            **{k+'_count':int(counts.get(k,0)) for k in ['take','stop','expiry']}))
    for path,expected in protocol['source_hashes'].items():assert digest(ROOT/path)==expected
    for source in protocol['action_sources'].get('sources',[]):assert digest(source['path'])==source['sha256']
    for source in [protocol['action_sources'].get('june_missing_key_receipt')]:
        if source:assert digest(ROOT/source['path'])==source['sha256']
    for source in protocol['action_sources'].get('fixed_ioc_missing_key_receipts',[]):
        assert digest(ROOT/source['path'])==source['sha256']
    if minimal:
        from baseline_fixed_ioc import fixed_ioc_engine
        from run_june2020_starts import module
        core=module('minimal_comparison_core',ARCHIVE/'research/run_batch.py')
        engine=fixed_ioc_engine(core)
        assert engine.adapted_source==(directory/'SIMULATE_SOURCE.txt').read_text(encoding='utf-8')
        assert engine.policy==protocol['execution_policy']
        attempts=pd.read_parquet(directory/'FIXED_ORDER_ATTEMPTS.parquet')
        assert not attempts.duplicated(['start_ordinal','symbol','signal_date']).any()
        assert attempts.requested_quantity.mod(100).eq(0).all()
        assert (attempts.filled_quantity>=0).all() and (attempts.filled_quantity<=attempts.requested_quantity).all()
        fills=attempts[attempts.filled_quantity.gt(0)].copy()
        fills['signal_date']=pd.to_datetime(fills.signal_date);fills['entry_date']=pd.to_datetime(fills.date)
        linked=fills.merge(t,on=['start_ordinal','symbol','signal_date','entry_date'],validate='one_to_one')
        assert len(linked)==len(fills)==len(t)
        np.testing.assert_allclose(linked.filled_quantity,linked.entry_notional/linked.entry_price,rtol=0,atol=1e-9)
        old_signals=pd.read_parquet(BASE/'results/holdout_restricted/original_q1_replay/attempt_20261020_033310/FROZEN_SIGNALS.parquet')
        pd.testing.assert_frame_equal(pd.read_parquet(directory/'FROZEN_SIGNALS.parquet'),old_signals)
    d=pd.DataFrame(rows)
    group=('2020年6月' if pd.Timestamp(m.start_date.iloc[0]).month==6 else f'{pd.Timestamp(m.start_date.iloc[0]).year}年Q1')+'起点至2026-10-19'
    summary=dict(group=group,start_count=len(m),cumulative_return_mean=float(d.cumulative_return.mean()),
        cumulative_return_median=float(d.cumulative_return.median()),annualized_return_mean=float(d.annualized_return.mean()),
        annualized_return_median=float(d.annualized_return.median()),annualized_excess_mean=float(d.annualized_excess.mean()),
        positive_start_fraction=float(d.cumulative_return.gt(0).mean()),beat_sse_fraction=float(d.annualized_excess.gt(0).mean()),
        maximum_drawdown_mean=float(d.maximum_drawdown.mean()),sharpe_mean=float(d.sharpe.mean()),
        **{k+'_count_mean':float(d[k+'_count'].mean()) for k in ['take','stop','expiry']})
    if (directory/'SUMMARY.json').exists():
        stored=json.loads((directory/'SUMMARY.json').read_text(encoding='utf-8'));assert stored['status']=='complete'
        for k in set(stored)&set(summary):
            if isinstance(summary[k],(int,float)):assert abs(summary[k]-stored[k])<1e-12,(k,summary[k],stored[k])
    report={'status':'ok','runs':len(m),'daily_risk_metrics_recomputed':True,'exit_counts_recomputed':True,
        'minimal_patch_and_fixed_ioc_verified':minimal,
        'same_interval_benchmark_recomputed':True,'terminal_empty':True,'coverage_gaps':0,'recorded_source_hashes_unchanged':True,
        'summary':summary,'inputs':{p.name:digest(p) for p in [directory/'PROTOCOL.json',directory/'START_METRICS.csv',directory/'EQUITY_CURVES.parquet',directory/'TRADES.parquet']}}
    (directory/'REPLAY_INDEPENDENT_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return summary


def main():
    parser=argparse.ArgumentParser();parser.add_argument('directories',nargs='+',type=Path);args=parser.parse_args()
    summaries=[inspect_run(p) for p in args.directories]
    out=BASE/'results/holdout_restricted/original_execution_all_start_groups'/datetime.now().strftime('attempt_%Y%m%d_%H%M%S')
    out.mkdir(parents=True,exist_ok=False)
    pd.DataFrame(summaries).to_csv(out/'FULL_COMPARISON.csv',index=False,encoding='utf-8-sig')
    report={'status':'ok','strategy':'C04_NEW','slots':5,'initial_cash':100000,'end':'2026-10-19',
        'execution':'Original frozen mixed ATR, frozen stitched signals and original execution including 37-day maturity tail',
        'groups':summaries,'sources':[str(p.relative_to(ROOT)) if p.is_absolute() else str(p) for p in args.directories],
        'production_account_changed':False,'production_strategy_changed':False}
    (out/'FULL_COMPARISON.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Output',out,flush=True);print(json.dumps(summaries,ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__':main()
