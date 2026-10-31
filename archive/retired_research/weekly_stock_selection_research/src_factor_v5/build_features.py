from concurrent.futures import ThreadPoolExecutor
import json
import numpy as np
import pandas as pd
from settings import OLD,OUT,INPUTS,NEW,sha,dump,new_features,install_read_boundary


def main():
    install_read_boundary()
    assert not (OUT/'new_factor_panel.parquet').exists()
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    groups={s:g[['signal_date']].copy() for s,g in panel.groupby('symbol')}
    manifest=json.loads((INPUTS/'kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    records={r['symbol']:r for r in manifest['files'] if r['rows']}
    cal=pd.read_parquet(INPUTS/'calendar_dev_v1.parquet')
    days=pd.DatetimeIndex(cal.loc[cal.is_trading_day.eq(1),'calendar_date'])
    def worker(symbol):
        record=records[symbol]
        path=INPUTS/'kline_dev_v1'/record['snapshot_file']
        assert sha(path)==record['snapshot_sha256']
        frame=pd.read_parquet(path)
        assert frame.date.le('2023-12-31').all()
        frame=frame.set_index('date').reindex(days.copy(deep=True))
        f=new_features(frame)
        assert frame.index.is_unique and f.index.is_unique,symbol
        result=groups[symbol].copy()
        result[NEW]=f.reindex(pd.to_datetime(result.signal_date)).to_numpy()
        result['symbol']=symbol
        return result
    parts=[]
    with ThreadPoolExecutor(max_workers=1) as pool:
        for i,p in enumerate(pool.map(worker,sorted(groups)),1):
            parts.append(p)
            if i%500==0:
                print('new6factor construction',i,'/',len(groups),flush=True)
    result=pd.concat(parts,ignore_index=True).sort_values(['signal_date','symbol']).reset_index(drop=True)
    assert result[['signal_date','symbol']].equals(panel[['signal_date','symbol']])
    result.to_parquet(OUT/'new_factor_panel.parquet',index=False)
    dump(OUT/'new_factor_audit.json',dict(rows=len(result),new_features=NEW,unchanged_original_signal_pool=True,
         unknown_future_labels_not_used_for_pool=True,missing_fraction={c:float(result[c].isna().mean()) for c in NEW},
         sha256=sha(OUT/'new_factor_panel.parquet'),posterior_read_hook_enabled=True))
    print('New6factor panel retained:',len(result),'rows',flush=True)


if __name__=='__main__':
    main()
