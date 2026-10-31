from pathlib import Path
from types import SimpleNamespace
import ast, base64, hashlib, json, zlib, importlib.util, math
import numpy as np
import pandas as pd
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'quant_env').is_dir() and (p/'AGENTS.md').is_file())
DATA=ROOT/'K线数据/科创'
spec=importlib.util.spec_from_file_location('star_features',Path(__file__).resolve().parents[1]/'research/training_source/src/model.py')
feature=importlib.util.module_from_spec(spec);spec.loader.exec_module(feature)
F=feature.FEATURES
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def dataset(dest,start,end):
    chunks=[];panels={};metadata=pd.read_csv(DATA/'metadata/universe.csv').set_index('symbol')
    for file in sorted((dest/'qfq').glob('*.parquet')):
        q=pd.read_parquet(file).sort_values('date').reset_index(drop=True)
        raw=pd.read_parquet(dest/'raw'/file.name).sort_values('date').set_index('date')
        assert pd.DatetimeIndex(q.date).equals(raw.index)
        g=feature._one(q,20,.30);g['symbol']=file.stem
        g['event_end']=g.date.shift(-20);g['stop_end']=g.date.shift(-22)
        # Vectorize on full symbol history, NEVER on filtered eligible dates.
        stop=np.full(len(g),10000);profit=stop.copy()
        for k in range(1,23):
            ret=g.open.shift(-k)/g.close-1
            stop=np.where((ret<=-.07)&(stop==10000),k,stop)
            profit=np.where((ret>=.24)&(profit==10000),k,profit)
        g['stop_label']=(stop<profit).astype(float)
        g.loc[g.stop_end.isna(),'stop_label']=np.nan
        valid=(np.arange(len(g))+1>=120)&(g.ret5<=.12)&(g.ret20<=.20)&(g.rise_from_low60<=.30)&(g.volume_spike<=5)&(g.high!=g.low)&(g.pctChg<19.5)&(np.expm1(g.amount20)>=50e6)&(g.isST.astype(str)!='1')
        out=pd.to_datetime(metadata.loc[file.stem,'outDate'],errors='coerce')
        if pd.notna(out):valid &= g.date<out
        g=g.loc[valid].replace([np.inf,-np.inf],np.nan).dropna(subset=F)
        # Include last previous-year signal for next-day replay, but never fitting.
        chunks.append(g.loc[(g.date>=pd.Timestamp(start)-pd.Timedelta(days=10))&(g.date<=end),['date','symbol']+F+['label','stop_label','event_end','stop_end']])
        raw['prev_actual']=raw.close.shift();raw['adjust_ratio']=raw.preclose/raw.prev_actual
        panels[file.stem]=raw
    ds=pd.concat(chunks,ignore_index=True).sort_values(['date','symbol']).reset_index(drop=True)
    return ds,panels,metadata

def namespace(source):
    tree=ast.parse(source)
    ns={'np':np,'pd':pd,'math':math,'base64':base64,'zlib':zlib,'json':json,'g':SimpleNamespace()}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Assign))],type_ignores=[]),'<export>','exec'),ns)
    return ns

def fast(m):
    m=dict(m)
    m['fast_trees']=[tuple(np.array([n[k] for n in t],dtype=d) for k,d in [('f',int),('t',float),('m',bool),('l',int),('r',int),('leaf',bool),('v',float)]) for t in m['trees']]
    return m
