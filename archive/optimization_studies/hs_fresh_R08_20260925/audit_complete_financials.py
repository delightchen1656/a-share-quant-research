"""Verify the supplement preserves existing data and adds retired histories."""
import hashlib,json
import pandas as pd
import numpy as np
import research as r
from prepare_complete_financials import FEATURES

if __name__=='__main__':
    u=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    retired=set(u.loc[u.outDate.notna(),'symbol'])
    cols=['execute_date','signal_date','symbol','fin_available','fin_report','fin_roe','fin_margin','fin_cash','fin_growth']
    old=pd.read_parquet(r.HERE/'features_broad_financials.parquet',columns=cols)
    new=pd.read_parquet(FEATURES,columns=cols)
    assert len(old)==len(new)
    keys=['execute_date','symbol']
    assert not new.duplicated(keys).any()
    pd.testing.assert_frame_equal(old[keys].reset_index(drop=True),new[keys].reset_index(drop=True))
    a=old.loc[~old.symbol.isin(retired)].reset_index(drop=True)
    b=new.loc[~new.symbol.isin(retired)].reset_index(drop=True)
    np.testing.assert_array_equal(pd.util.hash_pandas_object(a,index=False).to_numpy(),pd.util.hash_pandas_object(b,index=False).to_numpy())
    known=new.fin_available.notna()
    assert (new.loc[known,'fin_available']<new.loc[known,'signal_date']).all()
    rd=new[new.symbol.isin(retired)]
    assert rd.fin_available.notna().any()
    report=dict(rows=len(new),unchanged_current_symbol_rows=len(a),current_symbols_exact_digest_match=True,
        retired_eligible_symbols=rd.symbol.nunique(),retired_known_symbols=rd.loc[rd.fin_available.notna(),'symbol'].nunique(),
        retired_known_fraction=float(rd.fin_available.notna().mean()),
        availability_strictly_before_signal=True,feature_sha256=hashlib.sha256(FEATURES.read_bytes()).hexdigest(),
        original_vintage_certified=False)
    r.save(r.HERE/'financial_supplement_validation.json',report);print(json.dumps(report),flush=True)
