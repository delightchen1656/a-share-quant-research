"""Independent persisted-curve checks and residual rejection diagnostics."""
from pathlib import Path
import sys,json
import pandas as pd
import numpy as np
from replay_hushen2_local import sha

out=Path(sys.argv[1]);summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));assert summary['status']=='verified'
p=out/'fifth_cash_fit';m=pd.read_parquet(p/'START_METRICS.parquet');c=pd.read_parquet(p/'EQUITY_CURVES.parquet')
t=pd.read_parquet(p/'TRADES.parquet');a=pd.read_parquet(p/'ORDER_ATTEMPTS.parquet');o=pd.read_parquet(p/'PRESET_ORDERS.parquet')
a['signal_date']=pd.to_datetime(a.signal_date);o['signal_date']=pd.to_datetime(o.signal_date)
j=a.merge(o,on=['start_ordinal','signal_date','symbol'],validate='one_to_one');assert j.requested_quantity.eq(j.quantity).all()
failure=j.loc[j.status.eq('insufficient_cash_rejected')].copy()
estimated_cost=failure.quantity*failure.estimated_buy_price+np.maximum(5,failure.quantity*failure.estimated_buy_price*.0003)
assert estimated_cost.le(failure.creation_cash_estimate+1e-8).all()
assert failure.original_quantity.eq(failure.quantity).all()
max_delta=0.
for r in m.itertuples():
    cc=c.loc[c.start_ordinal.eq(r.start_ordinal)].sort_values('date');e=cc.equity.to_numpy();daily=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
    risk=dict(cumulative_return=e[-1]/100000-1,annualized_return=(e[-1]/100000)**(365/(pd.Timestamp(cc.date.iloc[-1])-pd.Timestamp(cc.date.iloc[0])).days)-1,
        maximum_drawdown=(e/np.maximum.accumulate(e)-1).min(),sharpe_zero_rf_252_ddof0=np.sqrt(252)*daily.mean()/daily.std(ddof=0))
    for k,value in risk.items():
        delta=abs(value-getattr(r,k));max_delta=max(max_delta,delta);assert delta<1e-10
    tt=t.loc[t.start_ordinal.eq(r.start_ordinal)];aa=a.loc[a.start_ordinal.eq(r.start_ordinal)]
    assert r.terminal_positions==0 and abs(100000+tt.pnl.sum()-e[-1])<1e-6
    assert len(tt)==r.filled==aa.filled_quantity.gt(0).sum() and r.created==r.filled+r.failed
    assert aa.status.eq('insufficient_cash_rejected').sum()==r.cash_rejected
report=dict(status='passed',paths=len(m),max_metric_delta=max_delta,fixed_submitted_quantity_matches_creation=True,
    residual_cash_rejections=len(failure),all_residual_rejections_affordable_at_creation=True,
    none_of_residual_cash_rejections_required_reduction_at_creation=True,
    residual_cash_rejections_by_creation_slot={str(k):int(v) for k,v in failure.groupby('occupied_slot').size().items()},
    residual_cash_rejections_by_holdings_at_creation={str(k):int(v) for k,v in failure.groupby('holdings_at_creation').size().items()},
    summary_sha256=sha(out/'SUMMARY.json'))
(out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
