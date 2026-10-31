"""Predetermined factor diagnostics and purged expanding-year classifiers."""
from pathlib import Path
import os
os.environ.setdefault('OMP_NUM_THREADS','1')
os.environ.setdefault('OPENBLAS_NUM_THREADS','1')
import json
import math
import sys
import warnings
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss
from scipy.stats import spearmanr
from build_dataset import HERE,ROOT,SPEC,FEATURES,sha,dump


def equal_date_weights(frame):
    return (1/frame.groupby('asof').symbol.transform('size')).to_numpy()


def selection(frame,column,direction=1,width_adjusted=False):
    picked=pd.Series(False,index=frame.index)
    for _,group in frame.groupby('asof'):
        if width_adjusted:
            ordered=group.sort_values(['box_width','symbol'])
            bins=np.floor(np.arange(len(ordered))*3/len(ordered)).astype(int)
            subgroups=[ordered.iloc[np.flatnonzero(bins==i)] for i in range(3)]
        else:
            subgroups=[group]
        for part in subgroups:
            if not len(part):
                continue
            ranked=part.sort_values([column,'symbol'],ascending=[direction<0,True],na_position='last')
            picked.loc[ranked.index[:math.ceil(len(part)/3)]]=True
    return picked


def lift_statistics(frame,mask):
    mask=mask.reindex(frame.index).fillna(False)
    per_date=[]
    for date,group in frame.groupby('asof'):
        chosen=group.loc[mask.loc[group.index]]
        if not len(chosen):
            continue
        y=group.y.eq(1)
        sy=chosen.y.eq(1)
        per_date.append(dict(asof=date,pool=len(group),selected=len(chosen),pool_success=int(y.sum()),
                             selected_success=int(sy.sum()),pool_rate=float(y.mean()),hit_rate=float(sy.mean()),
                             lift=float(sy.mean()-y.mean())))
    chosen=frame.loc[mask]
    nknown=int(chosen.y.notna().sum())
    return dict(dates=len(per_date),pool_n=len(frame),selected_n=len(chosen),
                selected_unique_stocks=int(chosen.symbol.nunique()),selected_successes=int(chosen.y.eq(1).sum()),
                selected_unknown=int(chosen.y.isna().sum()),
                selected_known_hit=float(chosen.y.eq(1).sum()/nknown) if nknown else None,
                pool_rate=float(np.mean([r['pool_rate'] for r in per_date])) if per_date else None,
                hit_rate=float(np.mean([r['hit_rate'] for r in per_date])) if per_date else None,
                lift=float(np.mean([r['lift'] for r in per_date])) if per_date else None,
                per_date=per_date)


def bootstrap_lift(frame,mask,draws=1000):
    """Crossed stock trajectory / adjacent-calendar-block multiplicity bootstrap."""
    f=frame.sort_values(['asof','symbol'])
    sids,_=pd.factorize(f.symbol,sort=True)
    tids,_=pd.factorize(f['asof'],sort=True)
    ns,nt=int(sids.max()+1),int(tids.max()+1)
    chosen=mask.reindex(f.index).to_numpy(bool)
    success=f.y.eq(1).to_numpy(float)
    rng=np.random.default_rng(26027)
    effects=[]
    for _ in range(draws):
        stock_count=np.bincount(rng.integers(ns,size=ns),minlength=ns)
        starts=rng.integers(nt,size=math.ceil(nt/2))
        dates=np.column_stack([starts,(starts+1)%nt]).ravel()[:nt]
        date_count=np.bincount(dates,minlength=nt)
        w=stock_count[sids].astype(float)
        total=np.bincount(tids,weights=w,minlength=nt)
        hits=np.bincount(tids,weights=w*success,minlength=nt)
        selected=np.bincount(tids,weights=w*chosen,minlength=nt)
        selected_hits=np.bincount(tids,weights=w*chosen*success,minlength=nt)
        good=(total>0)&(selected>0)&(date_count>0)
        if good.any():
            dif=selected_hits[good]/selected[good]-hits[good]/total[good]
            effects.append(float(np.average(dif,weights=date_count[good])))
    return dict(lower=float(np.quantile(effects,.025)),upper=float(np.quantile(effects,.975)),
                draws=len(effects),calendar_dates=nt,approximate_two_quarter_blocks=nt/2,
                unadjusted_exploratory=True)


class TrainOnlyTransform:
    def fit(self,frame,columns):
        self.columns=[c for c in columns if frame[c].notna().any()]
        self.medians=frame[self.columns].median()
        self.lower=frame[self.columns].quantile(.01)
        self.upper=frame[self.columns].quantile(.99)
        a=frame[self.columns].fillna(self.medians).clip(self.lower,self.upper,axis=1)
        self.scaler=StandardScaler().fit(a)
        return self
    def transform(self,frame):
        a=frame[self.columns].fillna(self.medians).clip(self.lower,self.upper,axis=1)
        return self.scaler.transform(a)
    def record(self):
        return dict(columns=self.columns,medians=self.medians.to_dict(),lower=self.lower.to_dict(),
                    upper=self.upper.to_dict(),means=self.scaler.mean_.tolist(),scale=self.scaler.scale_.tolist())


def probability_metrics(frame,column):
    known=frame.loc[frame.y.notna()]
    w=equal_date_weights(known)
    y=known.y.to_numpy()
    p=known[column].to_numpy()
    return dict(known_n=len(known),positive=int(y.sum()),
                auc=float(roc_auc_score(y,p,sample_weight=w)) if len(np.unique(y))==2 else None,
                average_precision=float(average_precision_score(y,p,sample_weight=w)) if y.sum() else None,
                brier=float(brier_score_loss(y,p,sample_weight=w)))


def main():
    data=pd.read_parquet(HERE/'results/factor_dataset.parquet')
    data['label_end']=pd.to_datetime(data.label_end)
    mature=data.loc[data.label_end.notna()].copy()
    discovery=mature.loc[mature.label_end.lt('2022-01-01')]
    validation=mature.loc[mature.year.isin([2022,2023])].copy()
    assert set(validation.year)=={2022,2023}
    assert validation.label_end.le('2023-12-31').all()
    factor_rows=[]
    selected_records=[]
    for feature in SPEC['features_order']:
        name,direction=feature['name'],feature['direction']
        raw=selection(validation,name,direction)
        adjusted=selection(validation,name,direction,True) if name!='box_width' else None
        disc_mask=selection(discovery,name,direction,name!='box_width')
        disc=lift_statistics(discovery,disc_mask)
        raw_stats=lift_statistics(validation,raw)
        primary=lift_statistics(validation,adjusted) if adjusted is not None else raw_stats
        annual={}
        for year,group in validation.groupby('year'):
            annual[str(year)]=lift_statistics(group,adjusted if adjusted is not None else raw)
        ci=bootstrap_lift(validation,adjusted if adjusted is not None else raw)
        lead=bool(name!='box_width' and disc['lift']>0 and all(annual[str(y)]['lift']>0 for y in [2022,2023])
                  and primary['selected_n']>=30 and primary['selected_unique_stocks']>=20 and primary['selected_successes']>=5)
        row=dict(feature=name,meaning=feature['meaning'],direction=direction,discovery_lift=disc['lift'],
                 raw_lift=raw_stats['lift'],adjusted_lift=primary['lift'] if adjusted is not None else None,
                 primary_hit_rate=primary['hit_rate'],pool_rate=primary['pool_rate'],
                 lift2022=annual['2022']['lift'],lift2023=annual['2023']['lift'],
                 selected_n=primary['selected_n'],selected_unique_stocks=primary['selected_unique_stocks'],
                 selected_successes=primary['selected_successes'],selected_unknown=primary['selected_unknown'],
                 ci_lower=ci['lower'],ci_upper=ci['upper'],directional_lead=lead)
        factor_rows.append(row)
        selected_records.append(dict(feature=name,discovery=disc,raw=raw_stats,width_adjusted=primary if adjusted is not None else None,
                                     annual=annual,bootstrap=ci))
    factors=pd.DataFrame(factor_rows).sort_values(['directional_lead','adjusted_lift','feature'],ascending=[False,False,True])
    factors.to_parquet(HERE/'results/factor_results.parquet',index=False)
    dump(HERE/'results/factor_details.json',selected_records)
    strict_factor_rows=[]
    strict_validation=validation.loc[validation.strict_v1]
    for feature in SPEC['features_order']:
        name,direction=feature['name'],feature['direction']
        mask=selection(strict_validation,name,direction,name!='box_width')
        stats=lift_statistics(strict_validation,mask)
        strict_factor_rows.append(dict(feature=name,**stats))
    dump(HERE/'results/strict_factor_diagnostics.json',strict_factor_rows)
    # Discovery-only feature correlation report, not an extra feature search.
    discovery[FEATURES].corr(method='spearman').to_parquet(HERE/'results/discovery_spearman.parquet')

    models=[]
    splits=[]
    predictions=[]
    train_details=[]
    for year in [2022,2023]:
        boundary=pd.Timestamp(f'{year}-01-01')
        train=mature.loc[mature.label_end.lt(boundary)&mature.y.notna()].copy()
        test=validation.loc[validation.year.eq(year)].copy()
        assert pd.to_datetime(train['asof']).max()<boundary and train.label_end.max()<boundary
        assert set(train.index).isdisjoint(test.index)
        positives=int(train.y.sum())
        split=dict(year=year,train_rows=len(train),train_unique=train.symbol.nunique(),train_positive=positives,
                   train_last_signal=str(max(train['asof'])),train_max_label_end=str(train.label_end.max().date()),
                   validation_dates=sorted(test['asof'].unique().tolist()),validation_rows=len(test),
                   validation_known=int(test.y.notna().sum()),validation_positive=int(test.y.sum()),
                   validation_unknown=int(test.y.isna().sum()),
                   repeated_train_validation_stocks=len(set(train.symbol)&set(test.symbol)))
        splits.append(split)
        minimum=SPEC['models']['training_minimum']
        enough=(len(train)>=minimum['known_rows'] and train.symbol.nunique()>=minimum['unique_stocks']
                and positives>=minimum['positive'] and len(train)-positives>=minimum['negative'])
        split['model_training_sufficient']=bool(enough)
        if not enough:
            continue
        weights=equal_date_weights(train)
        weights=weights/weights.mean()
        prior=float(np.average(train.y,weights=weights))
        test['prior']=prior
        for model_name in ['width_only','logistic','random_forest']:
            columns=['box_width'] if model_name=='width_only' else FEATURES
            prep=TrainOnlyTransform().fit(train,columns)
            x=prep.transform(train)
            tx=prep.transform(test)
            if model_name=='random_forest':
                estimator=RandomForestClassifier(**SPEC['models']['random_forest'])
            else:
                estimator=LogisticRegression(**SPEC['models']['logistic'])
            estimator.fit(x,train.y.astype(int),sample_weight=weights)
            test[model_name]=estimator.predict_proba(tx)[:,list(estimator.classes_).index(1)]
            detail=dict(year=year,model=model_name,preprocessing=prep.record())
            if hasattr(estimator,'coef_'):
                detail['coefficients']=dict(zip(prep.columns,estimator.coef_[0].tolist()))
                detail['intercept']=float(estimator.intercept_[0])
            else:
                detail['training_impurity_importance_only']=dict(zip(prep.columns,estimator.feature_importances_.tolist()))
            train_details.append(detail)
        for name in ['prior','width_only','logistic','random_forest','score']:
            if name=='prior':
                # A constant probability cannot select stocks; never report the
                # accidental symbol-order tie-break as a classifier's uplift.
                stats=dict(pool_rate=float(np.mean([g.y.eq(1).mean() for _,g in test.groupby('asof')])),
                           hit_rate=None,lift=None,selected_n=None,selected_successes=None)
            else:
                picked=selection(test,name,1)
                stats=lift_statistics(test,picked)
            if name!='score':
                metric=probability_metrics(test,name)
            else:
                known=test.loc[test.y.notna()]
                w=equal_date_weights(known)
                metric=dict(brier=None,auc=float(roc_auc_score(known.y,known[name],sample_weight=w)),
                            average_precision=float(average_precision_score(known.y,known[name],sample_weight=w)))
            models.append(dict(year=year,model=name,**metric,**{k:v for k,v in stats.items() if k!='per_date'}))
        # The prior has no meaningful stock ranking: its top-third is a deterministic
        # symbol tie-break, explicitly excluded from screening comparisons.
        keep=['symbol','asof','year','label_end','label_status','strict_v1','y','y_persistence','box_width','score','prior','width_only','logistic','random_forest']
        predictions.append(test[keep])
    model_frame=pd.DataFrame(models)
    model_frame.to_parquet(HERE/'results/model_results.parquet',index=False)
    prediction=pd.concat(predictions).sort_values(['asof','symbol']) if predictions else pd.DataFrame()
    prediction.to_parquet(HERE/'results/validation_predictions.parquet',index=False)
    dump(HERE/'results/time_splits.json',splits)
    dump(HERE/'results/model_training_details.json',train_details)
    model_gates={}
    for name in ['logistic','random_forest']:
        checks=[]
        for year in [2022,2023]:
            g=model_frame.loc[model_frame.year.eq(year)].set_index('model')
            checks.append(bool(name in g.index and g.loc[name,'lift']>0 and g.loc[name,'brier']<g.loc['prior','brier'] and g.loc[name,'brier']<g.loc['width_only','brier']))
        model_gates[name]=all(checks)
    strict_stats=[]
    if len(prediction):
        for year,g in prediction.loc[prediction.strict_v1].groupby('year'):
            for name in ['width_only','logistic','random_forest','score']:
                strict_stats.append(dict(year=int(year),model=name,**lift_statistics(g,selection(g,name))))
    dump(HERE/'results/strict_subset_diagnostics.json',strict_stats)
    audit=dict(spec_sha256=sha(HERE/'spec.json'),code_sha256=sha(__file__),features=FEATURES,
               discovery_rows=len(discovery),discovery_unique=discovery.symbol.nunique(),
               validation_rows=len(validation),validation_unique=validation.symbol.nunique(),
               validation_known=int(validation.y.notna().sum()),validation_positive=int(validation.y.sum()),
               validation_dates=sorted(validation['asof'].unique().tolist()),
               factor_directional_leads=factors.loc[factors.directional_lead,'feature'].tolist(),
               confirmed_factors=[],model_gates=model_gates,old20_reordered=False,
               note='Calendar condition in frozen spec overrides illustrative expected quarter count: 2023Q2 126-day label is immature, not evaluated. Adjacent labels overlap; development-only observations and unadjusted exploratory intervals.')
    dump(HERE/'results/analysis_audit.json',audit)
    print(factors[['feature','discovery_lift','raw_lift','adjusted_lift','lift2022','lift2023','selected_successes','ci_lower','ci_upper','directional_lead']].to_string(index=False),flush=True)
    print(model_frame[['year','model','brier','auc','average_precision','hit_rate','pool_rate','lift']].to_string(index=False),flush=True)
    print(json.dumps(audit,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    main()
