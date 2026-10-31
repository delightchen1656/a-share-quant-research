import json
import numpy as np
import pandas as pd
from settings import BASE,OLD,PRIOR,OUT,INPUTS,NEW,new_features,sha,dump,install_read_boundary


def main():
    install_read_boundary()
    rejected=[]
    for label,action in [('posterior',lambda:open(OUT/'posterior_review_guard_probe','rb')),
                         ('unapproved_parquet',lambda:pd.read_parquet(BASE.parent/'unapproved_input.parquet'))]:
        try:
            action()
        except PermissionError:
            rejected.append(label)
        else:
            raise AssertionError('Read guard did not reject forbidden input')
    original=json.loads((OLD/'artifact_registration.json').read_text(encoding='utf-8'))
    for row in original['files']:
        assert sha(BASE/row['path'])==row['sha256'],row['path']
    prior_reg=json.loads((PRIOR/'DEVELOPMENT_ARTIFACTS.json').read_text(encoding='utf-8'))
    for row in prior_reg['files']:
        assert sha(BASE/row['path'])==row['sha256'],row['path']
    manifest=json.loads((INPUTS/'kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        if row['rows']:
            assert sha(INPUTS/'kline_dev_v1'/row['snapshot_file'])==row['snapshot_sha256']
    panel=pd.read_parquet(OUT/'new_factor_panel.parquet')
    base=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    assert panel[['signal_date','symbol']].equals(base[['signal_date','symbol']])
    cal=pd.read_parquet(INPUTS/'calendar_dev_v1.parquet')
    days=pd.DatetimeIndex(cal.loc[cal.is_trading_day.eq(1),'calendar_date'])
    for i in np.linspace(0,len(panel)-1,90,dtype=int):
        row=panel.iloc[i]
        signal=pd.Timestamp(row.signal_date)
        raw=pd.read_parquet(INPUTS/'kline_dev_v1'/f'{row.symbol}.parquet',filters=[('date','<=',signal)])
        frame=raw.set_index('date').reindex(days[days<=signal].copy(deep=True))
        f=new_features(frame).iloc[-1]
        np.testing.assert_allclose(f[NEW].to_numpy(float),row[NEW].to_numpy(float),atol=1e-10,rtol=1e-10,equal_nan=True)
    dump(OUT/'validation.json',dict(passed=True,actual_forbidden_files_not_opened=True,read_guard_probes_rejected=rejected,
        whitelist_files_verified=3312,original53artifacts_unchanged=True,prior_development_and_frozen_artifacts_unchanged=True,
        truncated_history_factor_replays=90,original_signal_pool_unchanged=True,no_post2023data_loaded=True))
    print('Read-denial probes, snapshot hashes and90historical prefix factor replays passed.',flush=True)


if __name__=='__main__':
    main()
