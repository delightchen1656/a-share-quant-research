"""Independent checks on persisted fifth-slot trial outputs."""
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
from replay_hushen2_local import sha

out=Path(sys.argv[1]);summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));assert summary['status']=='verified'
paths=0;max_delta=0.
for variant in ['current','fifth_minus100']:
    folder=out/variant;m=pd.read_parquet(folder/'START_METRICS.parquet');c=pd.read_parquet(folder/'EQUITY_CURVES.parquet')
    t=pd.read_parquet(folder/'TRADES.parquet');a=pd.read_parquet(folder/'ORDER_ATTEMPTS.parquet');o=pd.read_parquet(folder/'PRESET_ORDERS.parquet')
    a['signal_date']=pd.to_datetime(a.signal_date);o['signal_date']=pd.to_datetime(o.signal_date)
    join=a.merge(o[['start_ordinal','signal_date','symbol','quantity','occupied_slot','original_quantity']],on=['start_ordinal','signal_date','symbol'],validate='one_to_one')
    assert join.requested_quantity.eq(join.quantity).all()
    assert (o.original_quantity-o.quantity).eq(np.where(o.occupied_slot.eq(5)&(variant=='fifth_minus100'),100,0)).all()
    for r in m.itertuples():
        frame=c.loc[c.start_ordinal.eq(r.start_ordinal)].sort_values('date');e=frame.equity.to_numpy();daily=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
        values=dict(cumulative_return=e[-1]/100000-1,annualized_return=(e[-1]/100000)**(365/(pd.Timestamp(frame.date.iloc[-1])-pd.Timestamp(frame.date.iloc[0])).days)-1,
            maximum_drawdown=(e/np.maximum.accumulate(e)-1).min(),sharpe_zero_rf_252_ddof0=np.sqrt(252)*daily.mean()/daily.std(ddof=0))
        for k,v in values.items():
            delta=abs(v-getattr(r,k));max_delta=max(max_delta,delta);assert delta<1e-10
        trades=t.loc[t.start_ordinal.eq(r.start_ordinal)];attempts=a.loc[a.start_ordinal.eq(r.start_ordinal)]
        assert r.terminal_positions==0 and abs(100000+trades.pnl.sum()-e[-1])<1e-6
        assert len(trades)==r.filled==int(attempts.filled_quantity.gt(0).sum())
        assert r.created==r.filled+r.failed
        assert r.cash_rejected==attempts.status.eq('insufficient_cash_rejected').sum()
    paths+=len(m)
report=dict(status='passed',paths=paths,max_metric_delta=max_delta,preset_fifth_reduction_exact=True,fixed_submitted_quantities_verified=True,
    closed_trade_PnL_and_order_counts_reconciled=True,summary_sha256=sha(out/'SUMMARY.json'))
(out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
