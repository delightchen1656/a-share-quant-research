"""Independent saved-curve audit of the one-way leader-pool posterior results."""
from pathlib import Path
import argparse
import json
import numpy as np
import pandas as pd

from audit_hushen2_leader_pool_post2024 import PRE, VARIANTS, LEADERS, STRATEGY, CASES, sha, load, dump


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output.resolve()
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));assert summary['status']=='verified' and not summary['action_gaps']
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert all(sha(Path(p))==h for p,h in protocol['protected_before'].items())
    pv=json.loads((PRE/'VERIFICATION.json').read_text(encoding='utf-8'))
    assert sha(PRE/'SUMMARY.json')==pv['summary_sha256']
    assert all(sha(PRE/p)==h for p,h in pv['result_hashes'].items())
    assert sha(PRE/'PROTOCOL.json')==protocol['frozen_pre_protocol_sha256']
    panel=json.loads((out/'PANEL_INPUTS.json').read_text(encoding='utf-8'))
    assert sha(PRE/'COMPONENT_PANEL_PRE2025.parquet')==panel['prior_panel_sha256']
    risk=load('posterior_independent_risk',STRATEGY/'backtest/compute_risk_metrics.py')
    codes=set(json.loads(LEADERS.read_text(encoding='utf-8-sig')))
    paths=0;regressionpaths=0;hashes={};maxdelta=0.
    for row in summary['rows']+summary['regression']:
        folder=out/row['tag']/row['variant']
        m=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet')
        for name in ['START_METRICS.parquet','EQUITY_CURVES.parquet','TRADES.parquet']:hashes[str((folder/name).relative_to(out))]=sha(folder/name)
        recomputed=risk.recompute_metrics(c)
        for key in ['cumulative_return','annualized_return','maximum_drawdown','sharpe_zero_rf_252_ddof0']:
            delta=(recomputed[key]-m[key]).abs().max();maxdelta=max(maxdelta,float(delta));assert delta<1e-12
            assert abs(float(m[key].mean())-row[key])<1e-12
        expected={2025:57,2026:56}[row['year']];assert len(m)==expected
        assert m.start_ordinal.is_unique and pd.to_datetime(m.start_date).dt.month.le(3).all()
        assert m.pending_orders.eq(0).all()
        assert (t.entry_date>t.signal_date).all() and (t.entry_date-t.signal_date).dt.days.le(7).all()
        assert (t.exit_date>t.entry_date).all() and t.exit_date.max()<=pd.Timestamp(row['end'])
        if row['variant']!='current':assert t.symbol.str[:6].isin(codes).all()
        for _,g in t.groupby(['start_ordinal','symbol']):
            g=g.sort_values('entry_date')
            if len(g)>1:assert (g.entry_date.iloc[1:].to_numpy()>g.exit_date.iloc[:-1].to_numpy()).all()
        assert abs(len(t)/len(m)+m.terminal_positions.mean()-row['filled'])<1e-12
        for reason,key in [('take','take_count'),('stop','stop_count'),('expiry','expiry_count')]:assert abs(t.reason.eq(reason).sum()/len(m)-row[key])<1e-12
        if row['tag'].startswith('regression'):regressionpaths+=len(m)
        else:paths+=len(m)
    receipts={p.name:sha(p) for p in (out/'actions').glob('*.json')}
    verification=dict(status='passed',account_paths=paths,additional_old_endpoint_regression_paths=regressionpaths,independent_curve_max_metric_delta=maxdelta,action_coverage_gaps=0,new_action_receipts=len(receipts),action_receipt_hashes=receipts,result_hashes=hashes,summary_sha256=sha(out/'SUMMARY.json'),parent_pre2025_results_unchanged=True,parent_pre2025_protocol_unchanged=True,production_hashes_unchanged=True,frozen_models_unchanged=True,no_fitting=True,no_feedback_to_development=True,terminal_positions_preserved=True,endpoint=summary['end'],classification_caution=protocol['caution'])
    dump(out/'VERIFICATION.json',verification)
    print('VERIFIED',paths,'posterior paths +',regressionpaths,'old endpoint regression paths')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
