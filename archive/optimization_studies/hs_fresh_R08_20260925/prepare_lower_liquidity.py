"""Expand only a research universe, retain the old 50m default and original outputs."""
import pandas as pd
import numpy as np
import research as r
from round04 import adjustment_features
from round08_long_momentum import long_features

BASE=r.HERE/'features_historical_5m.parquet'
PATH=r.HERE/'features_liquidity5m_long.parquet'

def main():
    assert not PATH.exists(),'Preserve completed research features'
    r.FEATURES=BASE;r.MIN_AMOUNT20=5e6;r.MIN_SIGNAL_VOL=.001;r.FEATURE_START='2020-01-02'
    f=r.build_features();old=pd.read_parquet(r.HERE/'features_historical_lowvol.parquet')
    subset=f[f.amount20>=50e6]
    assert len(subset)==len(old)
    # Full key/factor digest comparison; group ranks must be recomputed per universe.
    cols=[c for c in old.columns if c!='float_cap_proxy_group']
    a=pd.util.hash_pandas_object(subset[cols].sort_values(['execute_date','symbol']).reset_index(drop=True),index=False)
    b=pd.util.hash_pandas_object(old[cols].sort_values(['execute_date','symbol']).reset_index(drop=True),index=False)
    np.testing.assert_array_equal(a.to_numpy(),b.to_numpy())
    del old,subset,a,b
    market=pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').sort_values('date').set_index('date').close.astype(float)
    parts=[]
    for i,(s,rows) in enumerate(f.groupby('symbol')):
        raw=pd.read_parquet(r.e.raw_path(s),columns=['date','close','preclose']).sort_values('date').set_index('date')
        q=pd.read_parquet(r.e.qfq_path(s),columns=['date','close']).sort_values('date').set_index('date').close.astype(float)
        z=adjustment_features(raw).join(long_features(q,market)).reindex(pd.DatetimeIndex(rows.signal_date));z.index=rows.index;parts.append(z)
        if i%500==0:print('LOWER_LIQUIDITY_SIGNALS',i,flush=True)
    f=f.join(pd.concat(parts));f.to_parquet(PATH,index=False)
    r.save(PATH.with_suffix('.json'),dict(rows=len(f),symbols=f.symbol.nunique(),min_amount20=5e6,
        exact_50m_subset_factor_digest_match=True,warning='Data preparation only;not a successful strategy. Recompute size terciles AFTER each configured liquidity filter. Lower liquidity does not authorize lower costs or higher volume participation. Corporate-action proxy limitations unchanged.'))
    print('PREPARED',len(f),f.symbol.nunique(),flush=True)

if __name__=='__main__':main()
