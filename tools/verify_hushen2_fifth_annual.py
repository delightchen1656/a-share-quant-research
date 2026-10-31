"""Independent persisted-output audit for annual fifth-slot trial."""
from pathlib import Path
import json,sys
import numpy as np
import pandas as pd
from replay_hushen2_local import sha

out=Path(sys.argv[1]);s=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'));assert s['status']=='verified'
paths=0;max_delta=0.
for row in s['rows']:
    p=out/row['group']/row['variant'];m=pd.read_parquet(p/'START_METRICS.parquet');c=pd.read_parquet(p/'EQUITY_CURVES.parquet')
    t=pd.read_parquet(p/'TRADES.parquet');a=pd.read_parquet(p/'ORDER_ATTEMPTS.parquet');o=pd.read_parquet(p/'PRESET_ORDERS.parquet')
    a['signal_date']=pd.to_datetime(a.signal_date);o['signal_date']=pd.to_datetime(o.signal_date)
    j=a.merge(o[['start_ordinal','signal_date','symbol','quantity']],on=['start_ordinal','signal_date','symbol'],validate='one_to_one')
    assert len(j)==len(a) and j.requested_quantity.eq(j.quantity).all()
    expected=np.where(o.occupied_slot.eq(5)&(row['variant']=='fifth_minus100'),100,0)
    assert (o.original_quantity-o.quantity).eq(expected).all()
    assert m.terminal_positions.eq(0).all() and len(m)==row['starts']
    for r in m.itertuples():
        cc=c.loc[c.start_ordinal.eq(r.start_ordinal)].sort_values('date');e=cc.equity.to_numpy();daily=np.r_[e[0]/100000-1,np.diff(e)/e[:-1]]
        calc=dict(cumulative_return=e[-1]/100000-1,annualized_return=(e[-1]/100000)**(365/(pd.Timestamp(cc.date.iloc[-1])-pd.Timestamp(cc.date.iloc[0])).days)-1,
            maximum_drawdown=(e/np.maximum.accumulate(e)-1).min(),sharpe_zero_rf_252_ddof0=np.sqrt(252)*daily.mean()/daily.std(ddof=0))
        for k,value in calc.items():
            delta=abs(getattr(r,k)-value);max_delta=max(max_delta,delta);assert delta<1e-10
        tr=t.loc[t.start_ordinal.eq(r.start_ordinal)];at=a.loc[a.start_ordinal.eq(r.start_ordinal)]
        assert abs(100000+tr.pnl.sum()-e[-1])<1e-6 and len(tr)==r.filled==at.filled_quantity.gt(0).sum()
        assert r.created==r.filled+r.failed and r.cash_rejected==at.status.eq('insufficient_cash_rejected').sum()
    for k,v in row['means'].items():assert abs(m[k].mean()-v)<1e-8
    paths+=len(m)
assert paths==s['paths']==922
result=dict(status='passed',paths=paths,groups=len(s['rows']),max_metric_delta=max_delta,preset_quantity_exact=True,
    fixed_submitted_quantity_verified=True,all_daily_risks_and_PnL_reconciled=True,trade_cash_rejection_counts_reconciled=True,summary_sha256=sha(out/'SUMMARY.json'))
(out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
