from concurrent.futures import ThreadPoolExecutor
import json
import numpy as np
import pandas as pd
from settings import BASE,OLD,OUT,INPUTS,NEW_FACTORS,sha,dump,new_features


def main():
    assert not (OUT/'new_factor_panel.parquet').exists()
    manifest=json.loads((INPUTS/'kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    old=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    groups={s:g[['signal_date']].copy() for s,g in old.groupby('symbol')}
    calendar=pd.read_parquet(INPUTS/'calendar_dev_v1.parquet')
    days=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
    index=pd.read_parquet(INPUTS/'sse_dev_v1.parquet').set_index('date').reindex(days)
    market_lr=np.log(index.close/index.close.shift(1))
    records={r['symbol']:r for r in manifest['files'] if r['rows']}
    def worker(symbol):
        item=records[symbol]
        path=INPUTS/'kline_dev_v1'/item['snapshot_file']
        assert sha(path)==item['snapshot_sha256']
        raw=pd.read_parquet(path)
        assert raw.date.le('2023-12-31').all()
        frame=raw.set_index('date').reindex(days)
        f=new_features(frame,market_lr)
        result=groups[symbol].copy()
        dates=pd.to_datetime(result.signal_date)
        result[NEW_FACTORS]=f.reindex(dates).to_numpy()
        result['symbol']=symbol
        return result
    parts=[]
    with ThreadPoolExecutor(max_workers=8) as pool:
        for i,result in enumerate(pool.map(worker,sorted(groups)),1):
            parts.append(result)
            if i%500==0:
                print('trailing new-factor construction',i,'/',len(groups),flush=True)
    result=pd.concat(parts,ignore_index=True).sort_values(['signal_date','symbol']).reset_index(drop=True)
    assert result[['signal_date','symbol']].equals(old[['signal_date','symbol']])
    result.to_parquet(OUT/'new_factor_panel.parquet',index=False)
    dump(OUT/'new_factor_audit.json',dict(rows=len(result),new_factors=NEW_FACTORS,
         missing_fraction={c:float(result[c].isna().mean()) for c in NEW_FACTORS},
         original_pool_and_labels_unchanged=True,only_pre2024_quotes=True,panel_sha256=sha(OUT/'new_factor_panel.parquet')))
    print('New factors built',len(result),'rows',len(NEW_FACTORS),'features',flush=True)


if __name__=='__main__':
    main()
