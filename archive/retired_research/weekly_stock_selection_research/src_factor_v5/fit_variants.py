"""Registered36factor trials; frozen HGB controls; pre2024data only."""
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json
import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import HistGradientBoostingRegressor
from settings import BASE,OLD,PRIOR,OUT,NEW,PRIOR_NEW,ALL_FACTORS,variants,sha,dump,install_read_boundary


def main():
    install_read_boundary()
    spec=json.loads((OUT/'spec.json').read_text(encoding='utf-8'))
    reg=json.loads((OUT/'registration.json').read_text(encoding='utf-8'))
    amendment=json.loads((OUT/'engineering_amendment.json').read_text(encoding='utf-8'))
    assert sha(OUT/'spec.json')==reg['spec_sha256']
    for row in reg['files']:
        expected=amendment['amended_builder_sha256'] if row['path'].endswith('build_features.py') else row['sha256']
        assert sha(BASE/row['path'])==expected,row['path']
    assert json.loads((OUT/'validation.json').read_text(encoding='utf-8'))['passed']
    assert not list(OUT.glob('fold_scores_*.parquet')),'No overwriting scored trials'
    panel=pd.read_parquet(OLD/'weekly_factor_panel.parquet')
    prior=pd.read_parquet(PRIOR/'new_factor_panel.parquet')
    new=pd.read_parquet(OUT/'new_factor_panel.parquet')
    keys=panel[['signal_date','symbol']]
    assert keys.equals(prior[['signal_date','symbol']]) and keys.equals(new[['signal_date','symbol']])
    panel[PRIOR_NEW]=prior[PRIOR_NEW]
    panel[NEW]=new[NEW]
    xs=panel.groupby('signal_date')[ALL_FACTORS].rank(pct=True,na_option='keep')
    model_variants=variants()
    assert spec['variants']==model_variants
    dump(OUT/'fit_registration.json',dict(utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
         code=[dict(path=str(p.relative_to(BASE)),sha256=sha(p)) for p in sorted((BASE/'src_factor_v5').glob('*.py'))],
         before_new_model_outcomes=True,posterior_read_denial_enabled=True))
    folds=[]
    for year in spec['folds']:
        train=panel.label_maturity_date.lt(f'{year}-01-01')&panel.ordinary_quote_excess.notna()
        test=panel.year.eq(year)
        assert panel.loc[train,'label_maturity_date'].max()<f'{year}-01-01'
        med=xs.loc[train].median()
        assert med.notna().all()
        weights=(1/panel.loc[train].groupby('signal_date').symbol.transform('size')).to_numpy()
        weights/=weights.mean()
        scaler=StandardScaler().fit(xs.loc[train].fillna(med),sample_weight=weights)
        tx=scaler.transform(xs.loc[train].fillna(med))
        vx=scaler.transform(xs.loc[test].fillna(med))
        target=panel.loc[train,'ordinary_quote_excess'].to_numpy()
        past_scores=pd.read_parquet(PRIOR/f'fold_scores_{year}.parquet')
        outputs=[]
        for number,(name,columns) in enumerate(model_variants.items(),1):
            ix=[ALL_FACTORS.index(c) for c in columns]
            model=HistGradientBoostingRegressor(**spec['fixed_HGB'])
            model.fit(tx[:,ix],target,sample_weight=weights)
            ranked=panel.loc[test,['signal_date','monday','tuesday','year','symbol']].copy()
            ranked['score']=model.predict(vx[:,ix])
            ranked['variant']=name
            ranked=ranked.sort_values(['signal_date','score','symbol'],ascending=[True,False,True])
            ranked['rank']=ranked.groupby('signal_date').cumcount()+1
            ranked=ranked.loc[ranked['rank'].le(30)]
            if name in ['original12','anchor11']:
                oldname='baseline12' if name=='original12' else 'drop__quote_momentum20'
                reference=past_scores.loc[past_scores.variant.eq(oldname)]
                assert list(zip(ranked.signal_date,ranked.symbol,ranked['rank']))==list(zip(reference.signal_date,reference.symbol,reference['rank']))
                np.testing.assert_allclose(ranked.score,reference.score,atol=1e-12,rtol=1e-12)
            outputs.append(ranked)
            if number%6==0:
                print(f'fold{year}: {number}/36fixed variants fitted',flush=True)
        result=pd.concat(outputs,ignore_index=True)
        assert result.groupby(['variant','monday']).size().eq(30).all()
        result.to_parquet(OUT/f'fold_scores_{year}.parquet',index=False)
        folds.append(dict(year=year,training_rows=int(train.sum()),training_dates=int(panel.loc[train,'signal_date'].nunique()),
             last_training_label=panel.loc[train,'label_maturity_date'].max(),test_rows=int(test.sum()),
             both_anchors_reproduced=True,score_sha256=sha(OUT/f'fold_scores_{year}.parquet'),
             medians=med.to_dict(),scaler_mean=scaler.mean_.tolist(),scaler_scale=scaler.scale_.tolist()))
        dump(OUT/'fold_training_audit.json',dict(folds=folds,all_training_labels_mature_before_test=True))
        print('fold',year,'complete',flush=True)
    dump(OUT/'fit_complete.json',dict(model_fits=180,variants=36,folds=5,both_anchors_reproduced_all_folds=True,
         posterior_results_not_read=True,no_extra_trials=True))


if __name__=='__main__':
    main()
