"""Fit only the45registered feature variants; fixed models, chronological folds."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import datetime
import json
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from settings import BASE,OLD,OUT,BASE_FACTORS,NEW_FACTORS,sha,dump,variants


def main():
    spec=json.loads((OUT/'spec.json').read_text(encoding='utf-8'))
    registration=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    assert sha(OUT/'spec.json')==registration['spec_sha256']
    for record in registration['files']:
        assert sha(BASE/record['path'])==record['sha256'],record['path']
    assert not list(OUT.glob('fold_scores_*.parquet')),'Preserve previous scores, no hidden repeated fits'
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    new=pd.read_parquet(OUT/'new_factor_panel.parquet')
    assert new[['signal_date','symbol']].equals(panel[['signal_date','symbol']])
    panel[NEW_FACTORS]=new[NEW_FACTORS]
    features=BASE_FACTORS+NEW_FACTORS
    ranks=panel.groupby('signal_date')[features].rank(pct=True,na_option='keep')
    saved=pd.read_parquet(OLD/'selection_scores_top30.parquet')
    model_variants=variants()
    assert model_variants==spec['models']
    code=list((BASE/'src_factor_v4').glob('*.py'))
    dump(OUT/'fit_registration.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         before_new_variant_scores=True,new_panel_sha256=sha(OUT/'new_factor_panel.parquet'),
         code=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in code]))
    folds=[]
    for year in spec['folds']:
        train=panel.label_maturity_date.lt(f'{year}-01-01')&panel.ordinary_quote_excess.notna()
        test=panel.year.eq(year)
        assert panel.loc[train,'label_maturity_date'].max()<f'{year}-01-01'
        medians=ranks.loc[train].median()
        assert medians.notna().all()
        weights=(1/panel.loc[train].groupby('signal_date').symbol.transform('size')).to_numpy()
        weights/=weights.mean()
        scaler=StandardScaler().fit(ranks.loc[train].fillna(medians),sample_weight=weights)
        tx=scaler.transform(ranks.loc[train].fillna(medians))
        vx=scaler.transform(ranks.loc[test].fillna(medians))
        target=panel.loc[train,'ordinary_quote_excess'].to_numpy()
        date_keys=panel.loc[test,['signal_date','monday','tuesday','symbol','year']].copy()
        result=[]
        for number,(name,columns) in enumerate(model_variants.items(),1):
            ix=[features.index(c) for c in columns]
            model=HistGradientBoostingRegressor(**spec['fixed_HGB'])
            model.fit(tx[:,ix],target,sample_weight=weights)
            ranked=date_keys.copy()
            ranked['score']=model.predict(vx[:,ix])
            ranked['variant']=name
            ranked=ranked.sort_values(['signal_date','score','symbol'],ascending=[True,False,True])
            ranked['rank']=ranked.groupby('signal_date').cumcount()+1
            ranked=ranked.loc[ranked['rank'].le(30)]
            if name=='baseline12' and year>=2021:
                reference=saved.loc[saved.year.eq(year)&saved.method.eq('hist_gradient_boosting')]
                assert list(zip(ranked.signal_date,ranked.symbol,ranked['rank']))==list(zip(reference.signal_date,reference.symbol,reference['rank'])),'Baseline ranks changed'
                np.testing.assert_allclose(ranked.score,reference.score,atol=1e-12,rtol=1e-12)
            result.append(ranked)
            if number%5==0:
                print(f'fold{year}: {number}/45 fixed factor variants fitted',flush=True)
        scores=pd.concat(result,ignore_index=True)
        assert scores.groupby(['variant','monday']).size().eq(30).all()
        scores.to_parquet(OUT/f'fold_scores_{year}.parquet',index=False)
        details=dict(year=year,training_rows=int(train.sum()),training_dates=int(panel.loc[train,'signal_date'].nunique()),
             last_training_label=panel.loc[train,'label_maturity_date'].max(),validation_rows=int(test.sum()),
             variants_fitted=len(model_variants),train_medians=medians.to_dict(),
             scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist(),
             baseline_original_top30_reproduced=bool(year>=2021),scores_sha256=sha(OUT/f'fold_scores_{year}.parquet'))
        folds.append(details)
        dump(OUT/'fold_training_audit.json',dict(folds=folds,all_outcomes_used_only_after_labels_mature=True))
        print(f'fold{year}complete: {train.sum():,}train rows / {test.sum():,}score rows',flush=True)
    dump(OUT/'fit_complete.json',dict(folds=len(folds),variants=45,model_fits=225,all_original_baseline_scores_reproduced=True,
         no_extra_variants_or_hyperparameter_search=True,original_pool_and_labels_unchanged=True))


if __name__=='__main__':
    main()
