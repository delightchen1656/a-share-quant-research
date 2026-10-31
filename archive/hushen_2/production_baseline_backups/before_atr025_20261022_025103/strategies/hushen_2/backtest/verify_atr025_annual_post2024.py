"""Independent saved-curve and order-ledger checks; no account simulation."""
import argparse,json,hashlib
from pathlib import Path
import numpy as np
import pandas as pd

def main():
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);out=p.parse_args().output
    summary=json.loads((out/'SUMMARY.json').read_text(encoding='utf-8'))
    index=pd.read_parquet(out/'SSE_PRICE_INDEX.parquet').set_index('date').close
    groups=[]
    for s in summary['summaries']:
        folder=out/s['group'];m=pd.read_parquet(folder/'START_METRICS.parquet')
        c=pd.read_parquet(folder/'EQUITY_CURVES.parquet');t=pd.read_parquet(folder/'TRADES.parquet');a=pd.read_parquet(folder/'FIXED_ORDER_ATTEMPTS.parquet')
        assert len(m)==s['runs']
        for r in m.itertuples():
            cc=c.loc[c.start_ordinal.eq(r.start_ordinal)].sort_values('date');tt=t.loc[t.start_ordinal.eq(r.start_ordinal)];aa=a.loc[a.start_ordinal.eq(r.start_ordinal)]
            e=cc.equity.to_numpy();ret=np.r_[e[0]/100000-1,e[1:]/e[:-1]-1]
            days=(cc.date.iloc[-1]-cc.date.iloc[0]).days
            annual=(e[-1]/100000)**(365/days)-1
            benchmark=(index.loc[cc.date.iloc[-1]]/index.loc[cc.date.iloc[0]])**(365/days)-1
            expected=[e[-1]/100000-1,annual,benchmark,annual-benchmark,np.min(e/np.maximum.accumulate(e)-1),np.sqrt(252)*ret.mean()/ret.std(ddof=0)]
            actual=[r.cumulative_return,r.annualized_return,r.benchmark_annualized,r.annualized_excess,r.maximum_drawdown,r.sharpe_zero_rf_252_ddof0]
            assert np.allclose(expected,actual,atol=1e-12,rtol=0)
            assert not aa.duplicated(['symbol','signal_date']).any()
            assert aa.filled_quantity.gt(0).sum()==len(tt)==r.filled_orders
            assert aa.filled_quantity.eq(0).sum()==r.failed_trigger_orders
            assert r.pending_orders_created==r.filled_orders+r.unfilled_orders+r.pending_orders_at_end
            assert r.unfilled_orders==r.failed_trigger_orders+r.expired_entry_orders
            assert len(tt)==r.take_count+r.stop_count+r.expiry_count
            assert not r.open_positions_at_end and not r.pending_orders_at_end and len(r.raw_action_gaps)==0
            for reason in ['take','stop','expiry']:assert tt.reason.eq(reason).sum()==getattr(r,reason+'_count')
            filled=aa.loc[aa.filled_quantity.gt(0)]
            merge=tt.assign(signal_date=tt.signal_date.astype(str)).merge(filled[['symbol','signal_date','date']],on=['symbol','signal_date'],validate='one_to_one')
            assert len(merge)==len(tt)
            assert pd.to_datetime(merge.date).eq(merge.entry_date).all()
        for k,v in s['means'].items():assert abs(float(m[k].mean())-v)<1e-12
        groups.append(dict(group=s['group'],runs=len(m),metrics_recomputed=True,order_identities=True,buy_orders_match_trades=True,action_gaps=0,terminal_empty=True))
    result=dict(status='verified',groups=groups,total_paths=sum(x['runs'] for x in groups),inputs={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.parquet')})
    (out/'INDEPENDENT_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
