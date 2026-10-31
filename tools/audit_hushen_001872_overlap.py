"""Read-only provider/local overlap audit, preserving both independent responses."""
from pathlib import Path
from datetime import datetime
import json
import pandas as pd
import numpy as np
import daily_market_update as api
from backfill_hushen_2015 import DATA,BASE,sha,save


def main():
    out=BASE/'results/holdout_restricted/history_2015_extension/attempt_20261022_2119/overlap_audit_001872'
    out.mkdir(exist_ok=True)
    symbol='001872.SZ';oldpath=DATA/'raw/SZ/001872.SZ.parquet'
    old=pd.read_parquet(oldpath);old.date=pd.to_datetime(old.date)
    end=str((old.date.min()+pd.Timedelta(days=45)).date())
    api.safe_login()
    try:
        fresh=api.normalize_history(api.query_history('sz.001872','2013-01-01',end,'3'),symbol,'main')
        fresh.to_parquet(out/'PROVIDER_RAW_RESPONSE.parquet',index=False)
        overlap=old.merge(fresh,on='date',suffixes=('_old','_fresh'))
        records=[]
        for col in ['open','high','low','close','preclose','volume','amount','turn','pctChg']:
            a=pd.to_numeric(overlap[col+'_old'],errors='coerce');b=pd.to_numeric(overlap[col+'_fresh'],errors='coerce')
            mismatch=~np.isclose(a,b,rtol=0,atol=1e-8,equal_nan=True)
            for _,r in overlap.loc[mismatch].iterrows():
                records.append(dict(date=str(r.date.date()),column=col,old=r[col+'_old'],fresh=r[col+'_fresh']))
        membership=[]
        parent=out.parent
        for path in sorted((parent/'membership').glob('*.parquet')):
            f=pd.read_parquet(path);v=f.loc[f.code.isin(['sz.001872','sz.000022'])].to_dict('records')
            if v:membership.append(dict(date=path.stem,rows=v))
        save(out/'AUDIT.json',dict(symbol=symbol,original_path=str(oldpath),original_sha256=sha(oldpath),
            provider_response_sha256=sha(out/'PROVIDER_RAW_RESPONSE.parquet'),fetched_at=datetime.now().isoformat(),
            overlap_rows=len(overlap),fresh_first=fresh.date.min(),fresh_last=fresh.date.max(),differences=records,
            historical_code_membership=membership,original_untouched=True))
        # Explicit user-authorized resolution: ONLY provider-normalization of
        # missing volume to zero on these verified non-trading rows. No price,
        # amount, tradestatus, active-day volume or original stored row changes.
        changed=overlap.loc[~np.isclose(pd.to_numeric(overlap.volume_old),pd.to_numeric(overlap.volume_fresh),rtol=0,atol=0,equal_nan=True)]
        assert len(changed)==32 and all(r['column']=='volume' for r in records)
        assert changed.volume_old.isna().all() and changed.volume_fresh.eq(0).all()
        assert changed.tradestatus_old.astype(str).eq('0').all() and changed.tradestatus_fresh.astype(str).eq('0').all()
        assert changed.amount_old.isna().all() and changed.amount_fresh.isna().all()
        folder=out.parent/'overlap_resolutions';folder.mkdir(exist_ok=True)
        save(folder/(symbol+'.json'),dict(status='approved_specific_nontrading_null_zero_equivalence',
            symbol=symbol,original_sha256=sha(oldpath),audit_path=str(out/'AUDIT.json'),
            audit_sha256=sha(out/'AUDIT.json'),provider_response_path=str(out/'PROVIDER_RAW_RESPONSE.parquet'),
            provider_response_sha256=sha(out/'PROVIDER_RAW_RESPONSE.parquet'),
            dates=[str(d.date()) for d in changed.date],columns=['volume'],
            preserve_original_overlap=True,active_volume_changes_allowed=False,
            scope='User authorized investigation and resolution; verified suspended rows only; never a generic bypass'))
        print(json.dumps(dict(overlap_rows=len(overlap),fresh_rows=len(fresh),differences=records),ensure_ascii=True,indent=2))
    finally:
        api.bs.logout()


if __name__=='__main__':main()
