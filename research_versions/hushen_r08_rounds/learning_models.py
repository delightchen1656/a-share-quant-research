"""Quarterly past-only learning; fixed small model set, no full-period fitting."""
import hashlib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from lightgbm import LGBMRegressor
import research as r

INPUTS=['ret5','ret20','mom','vol60','vol_ratio','turn_ratio','amihud',
        'amount20','turn20','float_cap_proxy','near_high','downside']
MODELS=[(kind,h) for kind in ('ridge','tree') for h in (5,20)]
OUT=r.HERE/'learning_models';PRED=r.HERE/'features_learning_predictions.parquet'

def normalize(f):
    return (f.groupby('signal_date')[INPUTS].rank(pct=True).fillna(.5)-.5).astype('float32')

def training_mask(f,fit,h,calendar):
    end=f['label_end'+str(h)]
    dates=calendar[calendar<fit][-504:]
    sampled=set(dates[::5])
    return (f.execute_date<fit)&(end<fit)&f.signal_date.isin(sampled)&f['target'+str(h)].notna()

def model(kind):
    if kind=='ridge':return Ridge(alpha=100.)
    return LGBMRegressor(n_estimators=80,num_leaves=7,max_depth=3,
        min_child_samples=500,learning_rate=.05,reg_lambda=10.,
        random_state=20260925,n_jobs=2,verbosity=-1,deterministic=True,force_col_wise=True)

def main():
    assert not PRED.exists(),'Do not overwrite completed predictions'
    OUT.mkdir(exist_ok=True)
    r.save(OUT/'protocol.json',dict(models=MODELS,inputs=INPUTS,parameters={k:model(k).get_params() for k in ('ridge','tree')},
        training='Quarterly, preceding504market sessions, every5th cross section, label_end and execution strictly before fit_date',
        target='Within-signal-date forward5/20session return percentile minus0.5; gross training proxy only',
        warning='Repeatedly researched historical sample, not pristine OOS; no model selection using full-period returns',
        code_sha256=hashlib.sha256(__file__.encode()+open(__file__,'rb').read()).hexdigest()))
    f=pd.read_parquet(r.HERE/'learning_labels.parquet').reset_index(drop=True)
    x=normalize(f)
    cal=pd.DatetimeIndex(pd.read_parquet(r.e.DATA/'indices/000905.SH.parquet').date).sort_values()
    pred=f.loc[f.execute_date>=pd.Timestamp('2020-01-01'),['signal_date','execute_date','symbol','downside','float_cap_proxy_group']].copy()
    audits=[]
    for kind,h in MODELS:
        y=f.groupby('signal_date')['target'+str(h)].rank(pct=True)-.5
        name=kind+str(h);pred[name]=np.nan
        for fit in pd.date_range('2020-01-01',r.END,freq='QS'):
            nxt=fit+pd.DateOffset(months=3)
            train=training_mask(f,fit,h,cal)
            test=(f.execute_date>=fit)&(f.execute_date<nxt)
            assert train.sum()>10000 and not (train&test).any()
            assert f.loc[train,'label_end'+str(h)].max()<fit
            m=model(kind);m.fit(x.loc[train],y.loc[train])
            pred.loc[f.index[test],name]=m.predict(x.loc[test])
            audits.append(dict(model=name,fit=str(fit),rows=int(train.sum()),
                max_label_end=str(f.loc[train,'label_end'+str(h)].max()),
                max_execute=str(f.loc[train,'execute_date'].max()),pred_rows=int(test.sum()),
                importance=dict(zip(INPUTS,map(float,m.coef_ if kind=='ridge' else m.feature_importances_)))))
            r.save(OUT/'audit.json',audits)
            print('FIT',name,str(fit.date()),int(train.sum()),flush=True)
    assert pred[[k+str(h) for k,h in MODELS]].notna().all().all()
    pred.to_parquet(PRED,index=False)
    r.save(OUT/'complete.json',dict(rows=len(pred),fits=len(audits),path=str(PRED)))

if __name__=='__main__':main()
