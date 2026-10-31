import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json
import hashlib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from common import BASE,AUDIT,SPEC,FACTORS,sha,dump


def main():
    assert sha(AUDIT/'spec.json')==json.loads((AUDIT/'registration.json').read_text(encoding='utf-8'))['spec_sha256']
    panel=pd.read_parquet(AUDIT/'weekly_factor_panel.parquet')
    xs=panel.groupby('signal_date')[FACTORS].rank(pct=True,na_option='keep')
    assert xs.index.equals(panel.index)
    outputs=[]
    audits=[]
    model_details=[]
    for year in [2021,2022,2023]:
        cutoff=f'{year}-01-01'
        train_mask=panel.label_maturity_date.lt(cutoff)&panel.ordinary_quote_excess.notna()
        test_mask=panel.year.eq(year)
        train=panel.loc[train_mask]
        test=panel.loc[test_mask].copy()
        assert train.label_maturity_date.max()<cutoff
        assert train.year.max()<year
        trainX=xs.loc[train_mask]
        testX=xs.loc[test_mask]
        medians=trainX.median()
        weights=(1/train.groupby('signal_date').symbol.transform('size')).to_numpy()
        weights/=weights.mean()
        scaler=StandardScaler().fit(trainX.fillna(medians),sample_weight=weights)
        tx=scaler.transform(trainX.fillna(medians))
        vx=scaler.transform(testX.fillna(medians))
        target=train.ordinary_quote_excess.to_numpy()
        models={
            'ridge':Ridge(alpha=10.),
            'hist_gradient_boosting':HistGradientBoostingRegressor(max_iter=100,max_leaf_nodes=15,min_samples_leaf=200,
                     learning_rate=.05,l2_regularization=10,early_stopping=False,random_state=26027)
        }
        predictions={}
        for name,model in models.items():
            model.fit(tx,target,sample_weight=weights)
            predictions[name]=model.predict(vx)
            detail=dict(year=year,method=name,features=FACTORS,medians=medians.to_dict(),scale_mean=scaler.mean_.tolist(),scale=scaler.scale_.tolist())
            if name=='ridge':
                detail['coefficients']=model.coef_.tolist()
                detail['intercept']=float(model.intercept_)
            model_details.append(detail)
        for method in SPEC['methods']:
            name=method['id']
            if name=='random10':
                scores=np.array([int.from_bytes(hashlib.blake2b(f'26027|{r.signal_date}|{r.symbol}'.encode(),digest_size=8).digest(),'big')/2**64 for r in test.itertuples()])
            elif name=='liquidity10':
                scores=test.log_median_amount20.to_numpy()
            elif name=='momentum20':
                scores=test.quote_momentum20.to_numpy()
            elif name=='reversal5':
                scores=test.quote_reversal5.to_numpy()
            elif name=='lowvol20':
                scores=-test.quote_volatility20.to_numpy()
            elif name=='volume_expansion':
                scores=test.volume_ratio5_20.to_numpy()
            elif name=='range_high':
                scores=test.quote_high_position20.to_numpy()
            elif name=='simple_composite':
                scores=(testX.quote_momentum20+(1-testX.quote_volatility20)+testX.log_median_amount20).to_numpy()/3
            else:
                scores=predictions[name]
            ranked=test[['signal_date','entry_day','tuesday','symbol','year']].copy()
            ranked['score']=scores
            ranked['method']=name
            ranked=ranked.sort_values(['signal_date','score','symbol'],ascending=[True,False,True],na_position='last')
            ranked['rank']=ranked.groupby('signal_date').cumcount()+1
            outputs.append(ranked.loc[ranked['rank'].le(30)])
        audits.append(dict(year=year,train_rows=len(train),train_dates=train.signal_date.nunique(),train_symbols=train.symbol.nunique(),
                           last_training_label_date=train.label_maturity_date.max(),validation_rows=len(test),validation_dates=test.signal_date.nunique(),
                           minimum_validation_pool=int(test.groupby('signal_date').size().min()),features_have_no_future_label_flags=True))
        print(f'fixed methods scored validation{year}: {len(train):,}train / {len(test):,}validation rows',flush=True)
    result=pd.concat(outputs,ignore_index=True)
    assert result.groupby(['method','entry_day']).size().eq(30).all()
    assert not result.duplicated(['method','entry_day','symbol']).any()
    result.to_parquet(AUDIT/'selection_scores_top30.parquet',index=False)
    dump(AUDIT/'training_audit.json',dict(folds=audits,model_details=model_details,
         score_file_sha256=sha(AUDIT/'selection_scores_top30.parquet'),spec_sha256=sha(AUDIT/'spec.json'),
         no_seed_or_model_search=True,crosssectional_ranks_use_all_signal_eligible_peers=True))
    print(json.dumps(audits,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
