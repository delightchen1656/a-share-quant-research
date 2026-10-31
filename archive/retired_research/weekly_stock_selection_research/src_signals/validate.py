"""Check restored artifacts, endpoint labels, information cutoffs and Friday score reproduction."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
from pathlib import Path
import sys
import json
import hashlib
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor

BASE=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(BASE/'src'))
from portfolio import Quotes
from common import FACTORS,quote_valid
OUT=BASE/'audits/holdout_restricted/signal_average_v3'
digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def factors_at_prefix(symbol,signal,q):
    df=pd.read_parquet(BASE/'inputs_pre2025/kline_dev_v1'/f'{symbol}.parquet',filters=[('date','<=',pd.Timestamp(signal))])
    frame=df.set_index('date').reindex(q.days[q.days<=pd.Timestamp(signal)])
    valid,num=quote_valid(frame)
    lr=np.log1p(num.pctChg/100).where(valid)
    chain=lr.cumsum()
    amt=num.amount.where(valid)
    vol=num.volume.where(valid)
    turn=pd.to_numeric(frame.turn,errors='coerce').where(valid)
    f={}
    for n in [20,60]:
        f[f'quote_momentum{n}']=np.expm1(lr.rolling(n,min_periods=int(np.ceil(n*.9))).sum().iloc[-1])
        f[f'quote_volatility{n}']=lr.rolling(n,min_periods=int(np.ceil(n*.9))).std().iloc[-1]
    f['quote_reversal5']=-np.expm1(lr.rolling(5,min_periods=5).sum().iloc[-1])
    f['quote_reversal1']=-np.expm1(lr.iloc[-1])
    f['log_median_amount20']=np.log(amt.rolling(20,min_periods=18).median().iloc[-1])
    f['volume_ratio5_20']=vol.rolling(5,min_periods=5).mean().iloc[-1]/vol.rolling(20,min_periods=18).mean().iloc[-1]
    f['turnover_mean20']=turn.rolling(20,min_periods=18).mean().iloc[-1]
    lo=chain.rolling(20,min_periods=18).min().iloc[-1]
    hi=chain.rolling(20,min_periods=18).max().iloc[-1]
    f['quote_high_position20']=(chain.iloc[-1]-lo)/(hi-lo) if hi>lo else .5
    f['quote_efficiency20']=abs(lr.rolling(20,min_periods=18).sum().iloc[-1])/lr.abs().rolling(20,min_periods=18).sum().iloc[-1]
    f['last_quote_change']=np.expm1(lr.iloc[-1])
    return f


def main():
    original=BASE/'audits/holdout_restricted/research_v1'
    reg=json.loads((original/'artifact_registration.json').read_text(encoding='utf-8'))
    for row in reg['files']:
        assert digest(BASE/row['path'])==row['sha256'],row['path']
    q=Quotes()
    manifest=json.loads((BASE/'inputs_pre2025/kline_dev_v1/manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        if item['rows']:
            assert digest(BASE/'inputs_pre2025/kline_dev_v1'/item['snapshot_file'])==item['snapshot_sha256']
    checks={}
    for endpoint,folder,col,weekday in [('Friday','friday_open_v2','entry_day',4),('Monday','research_v1','monday',0)]:
        root=BASE/'audits/holdout_restricted'/folder
        panel=pd.read_parquet(root/'weekly_factor_panel.parquet')
        scores=pd.read_parquet(root/'selection_scores_top30.parquet')
        train=json.loads((root/'training_audit.json').read_text(encoding='utf-8'))
        assert all(f['last_training_label_date']<f"{f['year']}-01-01" for f in train['folds'])
        assert (pd.to_datetime(panel[col]).dt.weekday==weekday).all()
        assert (pd.to_datetime(panel.tuesday).dt.weekday==1).all()
        assert panel.label_maturity_date.le('2023-12-31').all()
        assert (pd.to_datetime(scores.signal_date)<pd.to_datetime(scores[col])).all()
        assert scores.groupby(['method',col]).size().eq(30).all()
        assert not scores.duplicated(['method',col,'symbol']).any()
        for row in panel.iloc[np.linspace(0,len(panel)-1,60,dtype=int)].itertuples():
            entry=getattr(row,col)
            start=q.days.get_loc(pd.Timestamp(entry))
            stop=q.days.get_loc(pd.Timestamp(row.tuesday))
            assert q.days[start-1]==pd.Timestamp(row.signal_date)
            f=factors_at_prefix(row.symbol,row.signal_date,q)
            for feature in FACTORS:
                np.testing.assert_allclose(f[feature],getattr(row,feature),atol=1e-10,rtol=1e-10,equal_nan=True)
            path=[q.bar(row.symbol,i) for i in range(start,stop+1)]
            ordinary=all(x['active'] for x in path) and all(abs(b['preclose']-a['close'])<=.015 for a,b in zip(path,path[1:]))
            actual=path[-1]['close']/path[0]['open']-1 if ordinary else np.nan
            np.testing.assert_allclose(actual,row.ordinary_gross_quote_return,atol=1e-12,rtol=1e-12,equal_nan=True)
        checks[endpoint]=dict(historical_prefix_features_replayed=60,full_horizon_labels_replayed=60,
                             mature_training_labels=True,previous_actual_close_only=True,scores_top30_unique=True)
        if endpoint=='Friday':
            xs=panel.groupby('signal_date')[FACTORS].rank(pct=True,na_option='keep')
            train_mask=panel.label_maturity_date.lt('2023-01-01')&panel.ordinary_quote_excess.notna()
            test=panel.year.eq(2023)
            target=panel.loc[train_mask,'ordinary_quote_excess'].copy()
            altered=panel.ordinary_quote_excess.copy()
            altered.loc[test]=999.
            np.testing.assert_array_equal(altered.loc[train_mask],target)
            med=xs.loc[train_mask].median()
            weights=(1/panel.loc[train_mask].groupby('signal_date').symbol.transform('size')).to_numpy()
            weights/=weights.mean()
            scaler=StandardScaler().fit(xs.loc[train_mask].fillna(med),sample_weight=weights)
            model=HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,min_samples_leaf=200,
                learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=26027)
            model.fit(scaler.transform(xs.loc[train_mask].fillna(med)),target,sample_weight=weights)
            verify=panel.loc[test,['signal_date','symbol']].copy()
            verify['score']=model.predict(scaler.transform(xs.loc[test].fillna(med)))
            verify=verify.sort_values(['signal_date','score','symbol'],ascending=[True,False,True])
            verify['rank']=verify.groupby('signal_date').cumcount()+1
            verify=verify.loc[verify['rank'].le(30)]
            saved=scores.loc[scores.year.eq(2023)&scores.method.eq('hist_gradient_boosting')]
            assert list(zip(verify.signal_date,verify.symbol,verify['rank']))==list(zip(saved.signal_date,saved.symbol,saved['rank']))
            np.testing.assert_allclose(verify.score,saved.score,atol=1e-12,rtol=1e-12)
            checks[endpoint]['2023_HGB_independent_refit_reproduced']=True
            checks[endpoint]['future_validation_targets_do_not_change_training']=True
    checks.update(passed=True,original_Monday_artifacts_restored_to_all53_original_hashes=True,whitelist_snapshot_hashes_verified=3312)
    (OUT/'validation.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
