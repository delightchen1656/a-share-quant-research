"""Independent equity, benchmark, trades, order-count and protected-file checks."""
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from test_atr_thresholds_pre2025 import digest,BASE,ROOT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args();out=args.output
    report=json.loads((out/'COMPARISON.json').read_text(encoding='utf-8'))
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    assert report['status']=='complete'
    signals=pd.read_parquet(out/'INPUT_SIGNALS.parquet');index=pd.read_parquet(out/'SSE_INDEX.parquet').set_index('date').close
    checks=[];total=0
    for summary in report['summaries']:
        folder=out/summary['group'];m=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet')
        t=pd.read_parquet(folder/'TRADES.parquet');a=pd.read_parquet(folder/'ORDER_ATTEMPTS.parquet')
        assert len(m)==summary['start_count']
        assert len(t)==len(t.merge(signals[['date','symbol']],left_on=['signal_date','symbol'],right_on=['date','symbol'],validate='many_to_one'))
        assert t.signal_date.max()<=pd.Timestamp(summary['last_signal_cutoff'])
        assert t.exit_date.max()<=pd.Timestamp(summary['end'])
        for ordinal,g in c.groupby('start_ordinal'):
            g=g.sort_values('date');e=g.equity.to_numpy();r=np.r_[e[0]/100000-1,e[1:]/e[:-1]-1]
            row=m.loc[m.start_ordinal.eq(ordinal)].iloc[0]
            start,end=g.date.iloc[0],g.date.iloc[-1];days=(end-start).days
            expected=[e[-1]/100000-1,(e[-1]/100000)**(365/days)-1,np.min(e/np.maximum.accumulate(e)-1),np.sqrt(252)*r.mean()/r.std(ddof=0)]
            actual=[row.cumulative_return,row.annualized_return,row.maximum_drawdown,row.sharpe_zero_rf_252_ddof0]
            assert np.allclose(expected,actual,rtol=0,atol=1e-12)
            bench=(index.loc[end]/index.loc[start])**(365/days)-1
            assert abs(bench-row.benchmark_annualized_return)<1e-12
            assert abs(row.annualized_excess-(row.annualized_return-bench))<1e-12
            tt=t.loc[t.start_ordinal.eq(ordinal)];aa=a.loc[a.start_ordinal.eq(ordinal)]
            assert row.filled_orders==len(tt)==aa.filled_quantity.gt(0).sum()
            assert row.triggered_zero_fill_orders==aa.filled_quantity.eq(0).sum()
            assert row.unfilled_orders==row.expired_untriggered_orders+row.triggered_zero_fill_orders
            assert row.pending_orders_created==row.filled_orders+row.unfilled_orders+row.pending_orders_at_end
            assert row.filled_orders==row.take_count+row.stop_count+row.expiry_count+row.open_positions_at_end
            assert row.open_positions_at_end==row.pending_orders_at_end==0
            assert abs(e[-1]-(100000+tt.pnl.sum()))<1e-6
        for key in ['annualized_return','benchmark_annualized_return','annualized_excess','maximum_drawdown','sharpe_zero_rf_252_ddof0','filled_orders','unfilled_orders','take_count','stop_count','expiry_count']:
            assert abs(summary[key+'_mean']-m[key].mean())<1e-12
        checks.append(dict(group=summary['group'],runs=len(m),metrics=True,benchmark=True,order_counts=True,net_pnl=True));total+=len(m)
    # The 2020 annual replay must match prior continuous replay up to its new signal cutoff.
    old=pd.read_parquet(BASE/'results/holdout_restricted/atr_thresholds_pre2025/attempt_20261021_202130/atr_ge_025/EQUITY_CURVES.parquet',filters=[('date','<=',pd.Timestamp('2020-11-24'))])
    new=pd.read_parquet(out/'2020/EQUITY_CURVES.parquet',filters=[('date','<=',pd.Timestamp('2020-11-24'))])
    paired=new.merge(old,on=['date','start_ordinal'],validate='one_to_one',suffixes=('_new','_old'))
    assert len(paired)==len(new)==len(old)
    delta=float((paired.equity_new-paired.equity_old).abs().max());assert delta<1e-8
    protected={p:digest(Path(p))==h for p,h in protocol['protected_before'].items()};assert all(protected.values())
    source_hashes={p:digest(ROOT/p)==h for p,h in protocol['sources'].items()};assert all(source_hashes.values())
    verified=dict(status='verified',runs=total,checks=checks,baseline_2020_prefix_max_difference=delta,protected_files_unchanged=protected,sources_unchanged=source_hashes)
    (out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(verified,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(verified,ensure_ascii=False))


if __name__=='__main__':main()
