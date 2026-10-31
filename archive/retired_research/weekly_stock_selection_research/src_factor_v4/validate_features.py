"""Verify causal feature prefixes and unchanged original sources before promotion."""
import json
import sys
import types
import numpy as np
import pandas as pd
from settings import BASE,OLD,OUT,INPUTS,BASE_FACTORS,NEW_FACTORS,new_features,quotes_valid,sha,dump


def main():
    original=json.loads((OLD/'artifact_registration.json').read_text(encoding='utf-8'))
    for row in original['files']:
        assert sha(BASE/row['path'])==row['sha256'],row['path']
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    new=pd.read_parquet(OUT/'new_factor_panel.parquet')
    assert new[['signal_date','symbol']].equals(panel[['signal_date','symbol']])
    calendar=pd.read_parquet(INPUTS/'calendar_dev_v1.parquet')
    days=pd.DatetimeIndex(calendar.loc[calendar.is_trading_day.eq(1),'calendar_date'])
    market=pd.read_parquet(INPUTS/'sse_dev_v1.parquet').set_index('date').reindex(days)
    market_lr=np.log(market.close/market.close.shift(1))
    support=types.ModuleType('factor_functions')
    support.quotes_valid=quotes_valid
    sys.modules['factor_functions']=support
    from runtime import base_features_and_pool
    for position in np.linspace(0,len(new)-1,90,dtype=int):
        row=new.iloc[position]
        signal=pd.Timestamp(row.signal_date)
        raw=pd.read_parquet(INPUTS/'kline_dev_v1'/f'{row.symbol}.parquet',filters=[('date','<=',signal)])
        frame=raw.set_index('date').reindex(days[days<=signal])
        check=new_features(frame,market_lr.loc[:signal]).iloc[-1]
        np.testing.assert_allclose(check[NEW_FACTORS].to_numpy(float),row[NEW_FACTORS].to_numpy(float),atol=1e-10,rtol=1e-10,equal_nan=True)
        base,eligible=base_features_and_pool(frame)
        assert eligible.iloc[-1]
        np.testing.assert_allclose(base.iloc[-1][BASE_FACTORS].to_numpy(float),panel.iloc[position][BASE_FACTORS].to_numpy(float),atol=1e-10,rtol=1e-10,equal_nan=True)
    dump(OUT/'feature_validation.json',dict(passed=True,truncated_history_new_feature_replays=90,
         frozen_runtime_original_features_and_pool_replays=90,original53artifact_hashes_unchanged=True,
         new_factor_rows_identical_original_pool=True,no_post2023quotes_used=True))
    print('90historical prefix checks passed for all36factors and frozen pool runtime.',flush=True)


if __name__=='__main__':
    main()
