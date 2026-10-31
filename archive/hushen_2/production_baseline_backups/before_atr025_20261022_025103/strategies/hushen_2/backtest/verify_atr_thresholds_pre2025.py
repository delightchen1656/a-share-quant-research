"""Independently verify the four-threshold comparison without changing source results."""
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output
    report=json.loads((out/'COMPARISON.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert report['status']=='complete'
    signals=pd.read_parquet(out/'INPUT_SIGNALS_PRE2025.parquet')
    assert signals.date.max()<=pd.Timestamp('2024-11-24')
    checks={}
    for summary in report['summaries']:
        folder=out/summary['variant']
        c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet');m=pd.read_parquet(folder/'START_METRICS.parquet')
        assert len(m)==58 and c.date.max()==pd.Timestamp('2024-12-31')
        assert t.exit_date.max()<=pd.Timestamp('2024-12-31')
        selected=signals.loc[signals.atr_pct.ge(summary['threshold'])]
        matched=t.merge(selected[['date','symbol']],left_on=['signal_date','symbol'],right_on=['date','symbol'],validate='many_to_one')
        assert len(matched)==len(t)
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy();r=np.r_[e[0]/100000-1,e[1:]/e[:-1]-1]
            a=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            expected=[e[-1]/100000-1,(e[-1]/100000)**(365/(g.date.iloc[-1]-g.date.iloc[0]).days)-1,
                np.min(e/np.maximum.accumulate(e)-1),np.sqrt(252)*r.mean()/r.std(ddof=0)]
            actual=[a.cumulative_return,a.annualized_return,a.maximum_drawdown,a.sharpe_zero_rf_252_ddof0]
            assert np.allclose(expected,actual,rtol=0,atol=1e-12),(ordinal,expected,actual)
            assert a.completed_trades==t.start_ordinal.eq(ordinal).sum()
        assert summary['terminal_open_positions_max']==0 and summary['terminal_pending_orders_max']==0
        checks[summary['variant']]=dict(runs=58,metrics_recomputed=True,trades_match_filter=True,
            signals_by_year={str(y):int(selected.date.dt.year.eq(y).sum()) for y in range(2020,2025)})
    # Unfiltered replay must reproduce retained selected account curves until the new maturity cutoff.
    base=out.parents[3]
    source=base/'results/holdout_restricted/fixed_ioc_atr_price_q1_2020/attempt_20261020_051613/EQUITY_CURVES.parquet'
    old=pd.read_parquet(source,filters=[('date','<=',pd.Timestamp('2024-11-24'))])
    new=pd.read_parquet(out/'original/EQUITY_CURVES.parquet');new=new.loc[new.date.le(pd.Timestamp('2024-11-24'))]
    pair=new.merge(old,on=['start_ordinal','date'],suffixes=('_new','_old'),validate='one_to_one')
    assert len(pair)==len(old)==len(new)
    delta=float((pair.equity_new-pair.equity_old).abs().max())
    assert delta<=1e-8,delta
    protected={p:hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in protocol['protected_before'].items()}
    assert all(protected.values())
    root=Path(__file__).resolve().parents[3]
    sources_unchanged={p:hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in protocol['source_hashes'].items()}
    assert all(sources_unchanged.values())
    verification=dict(status='verified',variant_checks=checks,baseline_prefix_rows=len(pair),baseline_prefix_max_abs_equity_difference=delta,
        protected_unchanged=protected,sources_unchanged=sources_unchanged,all_232_paths_verified=True)
    (out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(verification,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(verification,ensure_ascii=False))


if __name__=='__main__':main()
