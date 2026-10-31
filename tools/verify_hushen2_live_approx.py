"""Independent accounting/statistical checks and benchmark/annual presentation."""
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd
from replay_hushen2_live_approx import dump,sha

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);a=ap.parse_args();out=Path(a.out)
    protocol=json.loads((out/'PROTOCOL.json').read_text(encoding='utf-8'))
    m=pd.read_parquet(out/'START_METRICS.parquet');curves=pd.read_parquet(out/'EQUITY_CURVES.parquet')
    bench=pd.read_parquet(out/'BENCHMARKS.parquet');bench.date=pd.to_datetime(bench.date)
    indices={k:g.set_index('date').close for k,g in bench.groupby('benchmark')}
    assert len(m)==58 and not json.loads((out/'ACTION_GAPS.json').read_text(encoding='utf-8'))
    maximum_error=0.;year_rows=[]
    for i,row in m.iterrows():
        start=pd.Timestamp(row.start_date);end=pd.Timestamp(row.end_date)
        c=curves.loc[curves.start_ordinal.eq(row.start_ordinal)].sort_values('date');c.date=pd.to_datetime(c.date)
        equity=c.equity.to_numpy();ret=np.r_[equity[0]/100000-1,np.diff(equity)/equity[:-1]]
        values={'cumulative_return':equity[-1]/100000-1,'annualized_return':(equity[-1]/100000)**(365/(end-start).days)-1,
                'maximum_drawdown':(equity/np.maximum.accumulate(equity)-1).min(),
                'sharpe_zero_rf_252_ddof0':np.sqrt(252)*ret.mean()/ret.std(ddof=0)}
        maximum_error=max(maximum_error,max(abs(values[k]-float(row[k])) for k in values))
        folder=out/'paths'/f'{int(row.start_ordinal):02d}_{row.start_date}'
        trades=pd.read_parquet(folder/'TRADES.parquet');attempts=pd.read_parquet(folder/'ATTEMPTS.parquet')
        assert pd.to_datetime(trades.exit_date).gt(pd.to_datetime(trades.entry_date)).all()
        assert pd.to_datetime(trades.entry_date).gt(pd.to_datetime(trades.signal_date)).all()
        assert pd.to_datetime(trades.entry_date).le(pd.to_datetime(trades.signal_date)+pd.Timedelta(days=7)).all()
        assert attempts.filled_quantity.le(attempts.requested_quantity).all()
        assert (attempts.requested_quantity%100).eq(0).all()
        for k,index in indices.items():
            annual=(index.loc[end]/index.loc[start])**(365/(end-start).days)-1
            m.loc[i,'benchmark_annualized_'+k]=annual
            m.loc[i,'annualized_excess_'+k]=row.annualized_return-annual
        prior=100000.
        for year,g in c.groupby(c.date.dt.year):
            e=np.r_[prior,g.equity.to_numpy()];daily=e[1:]/e[:-1]-1
            exits=trades.loc[pd.to_datetime(trades.exit_date).dt.year.eq(year)]
            fills=attempts.loc[pd.to_datetime(attempts.date).dt.year.eq(year)&attempts.filled_quantity.gt(0)]
            year_rows.append(dict(start_ordinal=row.start_ordinal,year=int(year),year_return=e[-1]/prior-1,
                maximum_drawdown=float((e/np.maximum.accumulate(e)-1).min()),
                sharpe=float(np.sqrt(252)*daily.mean()/daily.std(ddof=0)),filled=len(fills),
                takes=int(exits.reason.eq('take').sum()),stops=int(exits.reason.eq('stop').sum()),expiries=int(exits.reason.eq('expiry').sum())))
            prior=e[-1]
    assert maximum_error<1e-10
    m.to_parquet(out/'START_METRICS.parquet',index=False)
    years=pd.DataFrame(year_rows).groupby('year').mean(numeric_only=True).drop(columns='start_ordinal').reset_index()
    years.to_parquet(out/'ANNUAL_CONTINUOUS_PATHS.parquet',index=False)
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
    for kind,func in [('mean','mean'),('median','median')]:
        for k in indices:summary[kind]['annualized_excess_'+k]=float(getattr(m['annualized_excess_'+k],func)())
    summary.update(annual_continuous_paths=years.to_dict('records'),worst_path_drawdown=float(m.maximum_drawdown.min()),
        benchmarks='SSE and CSI300 price index; mean of per-path account CAGR minus benchmark CAGR, same endpoints',
        live_ledger_modified=False,model_retrained=False,verification_max_metric_error=maximum_error)
    dump(out/'SUMMARY.json',summary)
    dump(out/'VERIFICATION.json',dict(status='ok',paths=58,metric_error=maximum_error,action_coverage_gaps=0,
         trade_window_and_T1='passed',fixed_quantities='passed',terminal_accounting='verified in all workers',
         source_hashes={str(p.name):sha(p) for p in (out/'PROTOCOL.json',out/'SOURCE_AUDIT.json',out/'SIGNALS.parquet',out/'START_METRICS.parquet',out/'BENCHMARKS.parquet')}))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('best','worst','earliest')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
