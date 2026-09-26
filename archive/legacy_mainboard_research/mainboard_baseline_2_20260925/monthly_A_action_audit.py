"""Diagnose action-book approximation using exports, never feed it into signals."""
import json
import numpy as np
import pandas as pd
from monthly_A_platform_audit import OUT,DATA,save

def main():
    pos=pd.read_json(OUT/'platform_positions.json');pos['date']=pd.to_datetime(pos.date)
    tr=pd.read_json(OUT/'platform_trades.json');tr['date']=pd.to_datetime(tr.date)
    nav=pd.read_json(OUT/'platform_nav.json');nav['date']=pd.to_datetime(nav.date);nav=nav.sort_values('date')
    tr['signed_qty']=tr.quantity*np.where(tr.side=='BUY',1,-1)
    tr['cash_flow']=np.where(tr.side=='BUY',-tr.amount,tr.amount)-tr.commission-tr.stamp_tax
    flow=tr.groupby('date').cash_flow.sum()
    cash=nav.set_index('date').cash
    residual=cash.diff().fillna(cash.iloc[0]-100000)-flow.reindex(cash.index).fillna(0)
    extra=[]
    for symbol,x in pos.groupby('symbol'):
        p=DATA/'raw'/symbol[-2:]/(symbol+'.parquet')
        if not p.exists():continue
        price=pd.read_parquet(p);price['date']=pd.to_datetime(price.date);price=price.set_index('date')
        qty=x.set_index('date').quantity.reindex(cash.index).fillna(0)
        changes=tr[tr.symbol==symbol].groupby('date').signed_qty.sum().reindex(cash.index).fillna(0)
        unexplained=qty.diff().fillna(qty.iloc[0])-changes
        prev=price.close.shift(1);ratio=prev/price.preclose
        for d in cash.index[qty.shift(1).fillna(0)>0]:
            if d not in ratio.index:continue
            value=ratio.loc[d]
            if value>1.000001 or abs(unexplained.loc[d])>.01:
                extra.append(dict(date=str(d.date()),symbol=symbol,prior_qty=float(qty.shift(1).loc[d]),nontrade_qty_change=float(unexplained.loc[d]),price_ratio=float(value),legacy_share_multiplier=round(float(value),1) if value>1.02 else 1.,cash_residual_account=float(residual.loc[d])))
    save('company_action_observations.json',extra)
    bad=[x for x in extra if x['legacy_share_multiplier']>=1.1 and x['nontrade_qty_change']==0]
    save('company_action_audit.json',dict(observed_events=len(extra),false_split_proxy=len(bad),examples=bad[:12],cash_residual_days=int((residual.abs()>.05).sum()),note='Export-derived diagnostic only, not a complete independent corporate-action ledger. Not used to force optimized portfolios to platform holdings.'))
    print('ACTION AUDIT',len(extra),'false split candidates',len(bad));print(json.dumps(bad[:4],indent=2))

if __name__=='__main__':main()
