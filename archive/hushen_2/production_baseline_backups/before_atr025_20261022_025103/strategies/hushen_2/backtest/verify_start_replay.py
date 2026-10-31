"""Independently recompute return/risk and exit counts from saved replay artifacts."""
import json
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from compute_risk_metrics import recompute_metrics

def main(directory=None):
    directory=Path(directory or sys.argv[1]);base=Path(__file__).resolve().parents[1];root=base.parents[1]
    summary=json.loads((directory/'SUMMARY.json').read_text(encoding='utf-8'))
    assert summary['status']=='complete'
    protocol=json.loads((directory/'PROTOCOL.json').read_text(encoding='utf-8'))
    curves=pd.read_parquet(directory/'EQUITY_CURVES.parquet')
    runs=pd.read_csv(directory/'START_METRICS.csv')
    trades=pd.read_parquet(directory/'TRADES.parquet')
    calculated=recompute_metrics(curves)
    assert len(calculated)==len(runs)==len(protocol['starts'])
    assert runs.start_date.tolist()==protocol['starts']==calculated.start_date.tolist()
    for actual,column in [('cumulative_return','cumulative_return'),('annualized_return','annualized_return'),
                          ('maximum_drawdown','maximum_drawdown'),('sharpe_zero_rf_252_ddof0','sharpe')]:
        np.testing.assert_allclose(calculated[actual],runs[column],rtol=0,atol=1e-12)
    counts=trades.groupby([trades.start_date.dt.strftime('%Y-%m-%d'),'reason']).size()
    for row in runs.itertuples():
        for reason,col in [('take','take_count'),('stop','stop_count'),('expiry','expiry_count')]:
            assert getattr(row,col)==counts.get((row.start_date,reason),0)
        assert row.take_count+row.stop_count+row.expiry_count==row.completed_trades
    index_path=next(p for p in protocol['index_sources'] if 'holdout_index.parquet' in p)
    index=pd.read_parquet(root/index_path);index['date']=pd.to_datetime(index.date)
    close=index.set_index('date').close
    for row in runs.itertuples():
        start=pd.Timestamp(row.start_date);end=pd.Timestamp(row.end_date)
        bench=(float(close.loc[end]/close.loc[start]))**(365/(end-start).days)-1
        assert abs(row.annualized_excess-(row.annualized_return-bench))<1e-12
        assert bool(row.beat_sse)==(row.annualized_excess>0)
    assert not json.loads((directory/'ACTION_GAPS.json').read_text())
    assert not json.loads((directory/'HELD_ACTION_CONFLICTS.json').read_text())
    import hashlib
    mixed_atr_checked=False
    if protocol.get('atr_override_sources'):
        signals=pd.read_parquet(directory/'FROZEN_SIGNALS.parquet')
        for path,expected in protocol['atr_override_sources'].items():
            assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected
            source=pd.read_parquet(root/path,columns=['date','symbol','atr_pct']).rename(columns={'atr_pct':'expected_atr'})
            merged=signals.merge(source,on=['date','symbol'],validate='one_to_one')
            assert len(merged)==len(signals)
            pre=merged.date.lt(pd.Timestamp('2025-01-01'))
            np.testing.assert_array_equal(merged.loc[pre,'atr_pct'],merged.loc[pre,'expected_atr'])
        mixed_atr_checked=True
    software_terminal_checked=False
    if protocol.get('execution_mode') in ('current_tracker_continuous_daily_approximation','broker_fixed_quantity_ioc_daily_approximation'):
        assert protocol['last_signal_cutoff_calendar']==protocol['end']
        terminal=json.loads((directory/'TERMINAL_STATES.json').read_text())
        assert len(terminal)==len(runs)
        for account,row in zip(terminal,runs.itertuples()):
            assert account['start_date']==row.start_date
            assert len(account['positions'])==row.open_positions
            assert len(account['orders'])==row.pending_orders
            assert len(account['positions'])+len(account['orders'])<=5
            for pos in account['positions']:
                assert pos['quantity']>0
                assert pd.Timestamp(pos['deadline'])==pd.Timestamp(pos['entry_date'])+pd.Timedelta(days=30)
            for order in account['orders']:
                assert pd.Timestamp(order['signal_date'])+pd.Timedelta(days=7)>pd.Timestamp(protocol['end'])
        for path,expected in protocol['execution_code_hashes'].items():
            assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,('Execution source changed',path)
        software_terminal_checked=True
    for path,expected in json.loads((directory/'ACTION_SOURCES.json').read_text()).items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest()==expected,('Action source changed',path)
    ioc_checked=False
    if protocol.get('execution_mode')=='broker_fixed_quantity_ioc_daily_approximation':
        attempts=pd.read_parquet(directory/'IOC_ATTEMPTS.parquet')
        assert (attempts.filled_quantity>=0).all()
        assert (attempts.filled_quantity<=attempts.requested_quantity).all()
        buys=attempts[attempts.side.eq('buy')]
        assert not buys.duplicated(['start_date','symbol','signal_date']).any(),'IOC buy silently retried'
        assert buys.requested_quantity.mod(100).eq(0).all()
        sells=attempts[attempts.side.eq('sell') & attempts.filled_quantity.gt(0)].copy()
        assert len(sells)==len(trades),'Sell execution count differs'
        for source,target in [('date','exit_date'),('signal_date','signal_date'),('start_date','start_date')]:
            sells[source]=pd.to_datetime(sells[source])
        verified=sells.merge(trades,on=['symbol','signal_date','start_date'],suffixes=('_attempt','_trade'))
        verified=verified[verified.date.eq(verified.exit_date)]
        assert len(verified)==len(trades)
        np.testing.assert_array_equal(verified.filled_quantity,verified.shares)
        ioc_checked=True
    for key,col,method in [('cumulative_return_mean','cumulative_return','mean'),('cumulative_return_median','cumulative_return','median'),
                          ('annualized_return_mean','annualized_return','mean'),('annualized_excess_mean','annualized_excess','mean'),
                          ('maximum_drawdown_mean','maximum_drawdown','mean'),('sharpe_mean','sharpe','mean'),
                          ('take_count_mean','take_count','mean'),('stop_count_mean','stop_count','mean'),('expiry_count_mean','expiry_count','mean')]:
        assert abs(summary[key]-getattr(runs[col],method)())<1e-12
    report={'status':'ok','runs':len(runs),'independent_risk_recompute':True,'exit_count_recompute':True,'same_interval_sse_comparison':True,
            'actual_held_company_actions_complete':True,'action_source_files_unchanged':True,'summary_recompute':True,
            'software_terminal_and_execution_sources_checked':software_terminal_checked,
            'mixed_atr_override_source_checked':mixed_atr_checked,'fixed_quantity_ioc_attempts_checked':ioc_checked}
    (directory/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
