"""Pre2024-only refinement. Posterior directories are explicitly denied."""
from pathlib import Path
import sys
import json
import hashlib
import itertools
import importlib.util
import numpy as np
import pandas as pd

BASE=Path(__file__).resolve().parent.parent
OLD=BASE/'audits/holdout_restricted/research_v1'
PRIOR=BASE/'audits/holdout_restricted/monday_factor_v4'
OUT=BASE/'audits/holdout_restricted/monday_factor_v5'
INPUTS=BASE/'inputs_pre2025'
module_spec=importlib.util.spec_from_file_location('pre2024_factor_functions',BASE/'src_factor_v4/settings.py')
previous=importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(previous)
BASE_FACTORS=previous.BASE_FACTORS
PRIOR_NEW=previous.NEW_FACTORS
CORE=[f for f in BASE_FACTORS if f!='quote_momentum20']
NEW=['up_day_fraction60','positive_run20','return_autocorr20','jump_share20','close_to_vwap1','range_compression5_20']
ALL_FACTORS=BASE_FACTORS+PRIOR_NEW+NEW
BLOCKS={'long_momentum':['momentum120'],'acceleration':['acceleration5_20'],
        'amount':['amount_surprise1_20'],'tail':previous.GROUPS['tail']}


def variants():
    result={'original12':list(BASE_FACTORS),'anchor11':list(CORE)}
    for n in range(1,5):
        for subset in itertools.combinations(BLOCKS,n):
            result['combine__'+'__'.join(subset)]=CORE+[f for block in subset for f in BLOCKS[block]]
    result.update({'prune__'+f:[c for c in CORE if c!=f] for f in CORE})
    result.update({'new__'+f:CORE+[f] for f in NEW})
    result['new_group6']=CORE+NEW
    result['long_plus_new6']=CORE+['momentum120']+NEW
    assert len(result)==36
    assert all(len(columns)==len(set(columns)) for columns in result.values())
    return result


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path,data):
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def install_read_boundary():
    def audit(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,Path)):
            text=str(args[0]).replace('\\','/').lower()
            if 'restricted_audit_2025_2026' in text or 'posterior_review' in text:
                raise PermissionError('Optimizer must never open posterior audit artifacts')
    sys.addaudithook(audit)
    original=pd.read_parquet
    exact={OLD/'weekly_factor_panel.parquet',OLD/'selection_scores_top30.parquet',PRIOR/'new_factor_panel.parquet'}
    exact.update(PRIOR/f'fold_scores_{y}.parquet' for y in range(2019,2024))
    exact={p.resolve() for p in exact}
    def guarded(path,*args,**kwargs):
        p=Path(path).resolve()
        allowed=p.is_relative_to((INPUTS/'kline_dev_v1').resolve()) or p in {
            (INPUTS/'calendar_dev_v1.parquet').resolve(),(INPUTS/'sse_dev_v1.parquet').resolve()}
        allowed=allowed or p in exact or p.is_relative_to(OUT.resolve())
        if not allowed:
            raise PermissionError('Parquet outside registered development whitelist')
        return original(path,*args,**kwargs)
    pd.read_parquet=guarded


def new_features(frame):
    valid,num=previous.quotes_valid(frame)
    lr=np.log1p(num.pctChg/100).where(valid)
    f=pd.DataFrame(index=frame.index)
    f['up_day_fraction60']=lr.gt(0).astype(float).where(valid).rolling(60,min_periods=54).mean()
    up=(lr.gt(0)&valid).astype(int)
    f['positive_run20']=up.groupby(up.eq(0).cumsum()).cumsum().clip(upper=20).where(valid)
    f['return_autocorr20']=lr.rolling(20,min_periods=18).corr(lr.shift(1))
    denominator=lr.abs().rolling(20,min_periods=18).sum()
    f['jump_share20']=(lr.abs().rolling(20,min_periods=18).max()/denominator).where(denominator.gt(0),0.)
    vwap=(num.amount/num.volume).where(valid)
    f['close_to_vwap1']=(num.close/vwap-1).where(valid)
    range1=((num.high-num.low)/num.preclose).where(valid)
    f['range_compression5_20']=range1.rolling(5,min_periods=5).mean()/range1.rolling(20,min_periods=18).mean()
    assert list(f)==NEW
    return f.replace([np.inf,-np.inf],np.nan)
