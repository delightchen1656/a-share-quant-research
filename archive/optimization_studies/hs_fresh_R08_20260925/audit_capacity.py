"""Read-only comparison of saved executions with same-day raw trading capacity."""
import sys,json
import numpy as np
import pandas as pd
import research as r

def main(folder):
    out=r.HERE/folder;s=json.loads((out/'summary.json').read_text(encoding='utf-8'))
    results={}
    for cid in s['full']:
        trades=pd.read_json(out/(cid+'_trades.json'));trades.date=pd.to_datetime(trades.date)
        rows=[]
        for symbol,t in trades.groupby('symbol'):
            raw=pd.read_parquet(r.e.raw_path(symbol),columns=['date','amount','volume'])
            raw=raw.rename(columns={'amount':'market_amount','volume':'market_volume'})
            merged=t.merge(raw,on='date',how='left',validate='many_to_one');rows.append(merged)
        t=pd.concat(rows,ignore_index=True)
        assert t.market_volume.notna().all() and (t.market_volume>0).all()
        assert t.market_amount.notna().all() and (t.market_amount>0).all()
        volume=t.quantity/t.market_volume;amount=t.amount/t.market_amount
        assert (volume<=.05+1e-10).all()
        results[cid]=dict(orders=len(t),max_volume_fraction=float(volume.max()),p99_volume_fraction=float(volume.quantile(.99)),
            max_amount_fraction=float(amount.max()),p99_amount_fraction=float(amount.quantile(.99)),
            min_market_amount=float(t.market_amount.min()),
            warning='Daily capacity proxy only; day totals become known after open, so this does not prove09:31minute fill feasibility. No current-day volume is used in stock-selection signals.')
    r.save(out/'capacity_audit.json',results)
    print(json.dumps(results,ensure_ascii=False))

if __name__=='__main__':main(sys.argv[1])
