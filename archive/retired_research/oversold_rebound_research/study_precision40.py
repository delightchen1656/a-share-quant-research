"""Precision-first screening of basic signals. Nested annual time splits, pre2025.

Positive: first eligible (T+1) +3% touch within B1..B40. No downstream
outcome, quote from B1 onward, stock identity, or buy-day gap enters X.
Outer scores are reporting only: thresholds/methods chosen on prior year.
"""
import json
import hashlib
import math
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier,RandomForestClassifier
from sklearn.cluster import KMeans
from threadpoolctl import threadpool_limits
from study import ROOT,SOURCE,digest

OUT=ROOT/'results_v8_precision40'
CORE=['ret20','ret5','below_ma20','below_ma60','low_recent','rebound_from_low',
      'body','upper','lower','volume_ratio','last3_volume_ratio','close_over_prev_high',
      'ma20_slope5','ma60_slope10','pre_return60','pre_return120','ma20_ma60_gap',
      'down_volume_share20','up_volume_ratio20','new_lows10','signal_return',
      'signal_recovery','signal_close_rank','volatility20','raw_signal_close',
      'down_count21','one_price_count21']
LONG=['position1y','drawdown1y','recent_peak_to_high1y','position2y','drawdown2y',
      'recent_peak_to_high2y','position3y','drawdown3y','recent_peak_to_high3y']
FEATURES=CORE+LONG
TARGETS=[.92,.95,.97,.99]
CONFIGS=['rule_deep','rule_lowprice','rule_deep_lowprice','rule_low_position1',
         'lr_core_c01','lr_long_c01','hgb_core','hgb_long','rf_long','cluster4','cluster8']


def lower_bound(hits,n):
    if not n:return 0.
    z=1.96;p=hits/n
    return (p+z*z/(2*n)-z*math.sqrt(p*(1-p)/n+z*z/(4*n*n)))/(1+z*z/n)


def make_model(config):
    if config.startswith('lr'):
        return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
             StandardScaler(),LogisticRegression(C=.1,max_iter=2000,random_state=718))
    if config.startswith('hgb'):
        return HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=7,min_samples_leaf=30,
            l2_regularization=10,learning_rate=.05,early_stopping=False,random_state=718)
    if config.startswith('rf'):
        return make_pipeline(SimpleImputer(strategy='median',add_indicator=True,keep_empty_features=True),
            RandomForestClassifier(n_estimators=160,min_samples_leaf=20,max_features=.7,n_jobs=2,random_state=718))
    if config.startswith('cluster'):
        return make_pipeline(SimpleImputer(strategy='median',keep_empty_features=True),StandardScaler(),
            KMeans(n_clusters=int(config[-1]),n_init=10,random_state=718))
    return None


def matrix(d,features):
    assert set(features)<=set(FEATURES)
    return d[features].replace([np.inf,-np.inf],np.nan)


def fit(config,d):
    fs=CORE if '_core' in config else FEATURES
    model=make_model(config)
    if model is None:return dict(config=config,features=[])
    x=matrix(d,fs);y=d.target.to_numpy(dtype=int)
    if config.startswith('cluster'):
        model.fit(x);clusters=model.predict(x)
        # Empirical-Bayes shrinkage prevents tiny pure clusters getting score=1.
        base=y.mean();prob={}
        for k in np.unique(clusters):
            a=y[clusters==k];prob[int(k)]=float((a.sum()+20*base)/(len(a)+20))
        return dict(config=config,features=fs,model=model,cluster_prob=prob)
    model.fit(x,y)
    return dict(config=config,features=fs,model=model)


def score(pack,d):
    config=pack['config']
    if config=='rule_deep':return np.where(d.below_ma20<=-.10,1.,0.)
    if config=='rule_lowprice':return np.where(d.raw_signal_close<20,1.,0.)
    if config=='rule_deep_lowprice':return np.where((d.below_ma20<=-.10)&(d.raw_signal_close<20),1.,0.)
    if config=='rule_low_position1':return np.where(d.position1y<=.2,1.,0.)
    x=matrix(d,pack['features'])
    if config.startswith('cluster'):
        return np.array([pack['cluster_prob'][int(k)] for k in pack['model'].predict(x)])
    return pack['model'].predict_proba(x)[:,1]


def select_options(config,s,y,min_n):
    rows=[]
    # Fixed grid, plus discrete rule/cluster scores. No outer predictions involved.
    thresholds=[.5] if config.startswith('rule') else sorted(set(np.r_[np.arange(.50,.996,.01),np.quantile(s,[.5,.6,.7,.8,.9])]))
    for threshold in thresholds:
        mask=s>=threshold;n=int(mask.sum());hits=int(y[mask].sum())
        if n>=min_n:
            rows.append(dict(config=config,threshold=float(threshold),n=n,hits=hits,
                precision=hits/n,lower=lower_bound(hits,n)))
    return rows


def choose(rows,target):
    valid=[x for x in rows if x['precision']>=target]
    # Precision-first target constraint; then favor confidence over a tiny perfect subset.
    return max(valid,key=lambda x:(x['lower'],x['precision'],x['n'])) if valid else None


def stats(g):
    selected=g.loc[g.selected];n=len(g);k=len(selected);pos=int(g.target.sum());hit=int(selected.target.sum())
    bad=n-pos;badkept=k-hit
    return dict(total=n,baseline_precision=pos/n if n else None,selected=k,retention=k/n if n else None,
        hits=hit,precision=hit/k if k else None,bad_kept=badkept,bad_removed=bad-badkept,
        bad_removal_rate=(bad-badkept)/bad if bad else None,
        good_removed=pos-hit,good_removal_rate=(pos-hit)/pos if pos else None,
        selected_late=int((selected.first_t1_touch_day>40).sum()),selected_nohit=int(selected.first_t1_touch_day.isna().sum()))


def main():
    OUT.mkdir(exist_ok=True)
    cfg=dict(features=FEATURES,configs=CONFIGS,targets=TARGETS,outer_years=[2021,2022,2023,2024],
       selection='Validation precision >= requested target, n>=20 leaders/n>=50 sample; maximize Wilson lower bound then precision/count; else abstain. No outer-driven revision.',
       min_validation={'leaders':20,'sample':50},boundary='2024-12-31')
    (OUT/'PROTOCOL.json').write_text(json.dumps(cfg,indent=2),encoding='utf8')
    features_path=ROOT/'results_v5_long_position/events.parquet';labels_path=ROOT/'results_v7_takeprofit3/signals.parquet'
    features=pd.read_parquet(features_path);labels=pd.read_parquet(labels_path)
    d=features.merge(labels[['code','signal_date','first_t1_touch_day','buy_date']],left_on=['code','date'],right_on=['code','signal_date'],validate='one_to_one')
    calendar=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist();positions={x:i for i,x in enumerate(calendar)}
    d['label_end']=[calendar[positions[x]+40] for x in d.buy_date]
    d['target']=d.first_t1_touch_day.between(1,40).fillna(False).astype(int)
    assert len(d)==4641 and int(d.is_leader.sum())==881
    # Feature safety: forbidden outcome mutation leaves the exact matrix unchanged.
    corrupted=d.copy()
    for col in ['first_t1_touch_day','max_up60','max_down60','close20','close60','continued','entry_gap','path_slope','below_entry_share']:
        corrupted[col]=-99999
    pd.testing.assert_frame_equal(matrix(d,FEATURES),matrix(corrupted,FEATURES))
    predictions=[];choices=[];validation=[];comparison=[]
    for pool,pm in [('sample',pd.Series(True,index=d.index)),('leaders',d.is_leader)]:
        cohort=d.loc[pm].copy().reset_index(drop=True);min_n=cfg['min_validation'][pool]
        for year in cfg['outer_years']:
            outer_start=f'{year}-01-01';inner_start=f'{year-1}-01-01'
            train=cohort.loc[cohort.label_end<inner_start]
            valid=cohort.loc[(cohort.date>=inner_start)&(cohort.date<outer_start)&(cohort.label_end<outer_start)]
            test=cohort.loc[cohort.year==year]
            full_train=cohort.loc[cohort.label_end<outer_start]
            assert train.label_end.max()<inner_start and full_train.label_end.max()<outer_start
            assert test.date.min()>=outer_start
            options=[];packs={}
            for config in CONFIGS:
                pack=fit(config,train);s=score(pack,valid)
                options.extend(select_options(config,s,valid.target.to_numpy(),min_n))
                # Each family is also evaluated by the SAME prior-year selection procedure.
                packs[config]=fit(config,full_train)
            validation.extend([dict(pool=pool,outer_year=year,**x) for x in options])
            for target in TARGETS:
                chosen=choose(options,target);choices.append(dict(pool=pool,outer_year=year,target=target,chosen=chosen,train_n=len(full_train),validation_n=len(valid),test_n=len(test)))
                selected=np.zeros(len(test),dtype=bool) if chosen is None else score(packs[chosen['config']],test)>=chosen['threshold']
                pred=test[['code','date','year','target','first_t1_touch_day','label_end']].copy()
                pred['pool']=pool;pred['requested_precision']=target;pred['selected']=selected
                pred['method']=chosen['config'] if chosen else 'abstain'
                predictions.append(pred)
                for family,configs in [('rules',[x for x in CONFIGS if x.startswith('rule')]),
                      ('classification',[x for x in CONFIGS if x.startswith(('lr','hgb','rf'))]),
                      ('clustering',[x for x in CONFIGS if x.startswith('cluster')])]:
                    c=choose([x for x in options if x['config'] in configs],target)
                    temp=pred.copy();temp['selected']=False if c is None else score(packs[c['config']],test)>=c['threshold']
                    comparison.append(dict(pool=pool,year=year,target=target,family=family,method=c['config'] if c else 'abstain',**stats(temp)))
            print(pool,year,'done',flush=True)
    p=pd.concat(predictions,ignore_index=True);p.to_parquet(OUT/'outer_predictions.parquet',index=False)
    aggregates=[];annual=[]
    for (pool,t),g in p.groupby(['pool','requested_precision']):
        aggregates.append(dict(pool=pool,target=float(t),**stats(g)))
        for year,h in g.groupby('year'):annual.append(dict(pool=pool,target=float(t),year=int(year),**stats(h)))
    families=[]
    # Pool family statistics are sums of year-wise confusion counts, never mean of precisions.
    for pool in ['sample','leaders']:
        for t in TARGETS:
            for family in ['rules','classification','clustering']:
                a=[x for x in comparison if x['pool']==pool and x['target']==t and x['family']==family]
                kept=sum(x['selected'] for x in a);hit=sum(x['hits'] for x in a)
                families.append(dict(pool=pool,target=t,family=family,selected=kept,hits=hit,precision=hit/kept if kept else None))
    result=dict(aggregates=aggregates,annual=annual,families=families,choices=choices,
        source_hashes={str(features_path.relative_to(ROOT)):digest(features_path),str(labels_path.relative_to(ROOT)):digest(labels_path)},
        protocol_sha256=digest(OUT/'PROTOCOL.json'),code_sha256=digest(Path(__file__)),
        caveats=['Nested time evaluation inside previously explored pre2025 data, not untouched blind testing.',
                 'Fixed prior box-selected cohort, retrospective leader membership, overlapping stock/market episodes.',
                 'Label is price touch not economic/account profit or fill; no future-label leakage into features.',
                 'No 2025+ quotes/labels read, no current viewer or production model modified.'])
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'validation_options.json').write_text(json.dumps(validation,indent=2),encoding='utf8')
    print(json.dumps(aggregates,ensure_ascii=False,indent=2));print('annual97',json.dumps([x for x in annual if x['target']==.97],ensure_ascii=False))


if __name__=='__main__':
    with threadpool_limits(limits=2):main()
