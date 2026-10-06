from pathlib import Path
import importlib.util,json,hashlib,sys,re,warnings
import pandas as pd
import numpy as np
warnings.filterwarnings('ignore',category=FutureWarning)
HERE=Path(__file__).resolve().parent;PARENT=HERE.parent;ROOT=PARENT.parents[1]
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'
COLS=['date','open','high','low','close','preclose','volume','amount','turn','tradestatus','isST']
def dump(n,x):(HERE/n).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def read(n):return json.loads((HERE/n).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mod(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def features(stage):
    if stage=='evaluation':
        assert (HERE/'frozen.json').exists() and (HERE/'confirmation.json').exists()
        end=pd.Timestamp('2026-10-01');b=PARENT/'start_date_study/benchmark.parquet';files=sorted((DATA/'raw').glob('*/*.parquet'));hashes=None
    else:
        end=pd.Timestamp({'training':'2023-01-01','selection':'2024-01-01','confirmation':'2024-11-30'}[stage])
        base=PARENT/'retrain_2022';manifest=json.loads((base/(stage+'_snapshot_manifest.json')).read_text(encoding='utf-8'))
        b=base/(stage+'_snapshot')/'benchmark.parquet';assert sha(b)==manifest['benchmark_sha256']
        files=[base/(stage+'_snapshot')/(r['symbol']+'.parquet') for r in manifest['files']];hashes={r['symbol']:r['sha256'] for r in manifest['files']}
    dates=pd.DatetimeIndex(pd.read_parquet(b).date);assert dates.max()<end
    symbols=sorted(f.stem for f in files);matrices={k:pd.DataFrame(np.nan,index=dates,columns=symbols,dtype=np.float32) for k in ('cap','vol','overnight','intraday')}
    eligible=pd.DataFrame(False,index=dates,columns=symbols);prices=pd.DataFrame(np.nan,index=dates,columns=symbols,dtype=float)
    feature=mod(PARENT/'test2_cutoff_20241130/train.py','original_features');feature.CUT=end;inputs=[]
    for i,path in enumerate(files):
        h=sha(path)
        if hashes:assert h==hashes[path.stem]
        x=pd.read_parquet(path);x=x[COLS];x.date=pd.to_datetime(x.date);assert x.date.max()<end
        f,e,c=feature.stock_features(x)
        for k in matrices:matrices[k][path.stem]=f[k].reindex(dates)
        eligible[path.stem]=e.reindex(dates,fill_value=False);prices[path.stem]=c.reindex(dates)
        inputs.append(dict(symbol=path.stem,sha256=h,max_date=str(x.date.max().date())))
        if (i+1)%700==0:print(stage,i+1,flush=True)
    ranks={k:v.where(eligible).rank(axis=1,pct=True).astype(np.float32) for k,v in matrices.items()}
    dump(stage+'_inputs.json',dict(files=inputs,benchmark_sha256=sha(b),max_date=str(dates.max().date())))
    return ranks,eligible,prices,dates
def smooth(ranks,eligible,w):
    a,b,c,d=w
    return (-a*ranks['cap']-b*ranks['vol']+c*ranks['overnight']-d*ranks['intraday']).rolling(5,min_periods=3).mean().astype(np.float32).where(eligible)
def metric(prepared,w,stage):
    ranks,eligible,prices,dates=prepared;score=smooth(ranks,eligible,w)
    start,end={'training':('2019-01-01','2023-01-01'),'selection':('2023-01-01','2024-01-01'),'confirmation':('2024-01-01','2024-11-30')}[stage]
    labels=prices.shift(-20)/prices-1;rows=[]
    for i,d in enumerate(dates):
        if d<pd.Timestamp(start) or i%20!=0 or i+20>=len(dates) or dates[i+20]>=pd.Timestamp(end):continue
        s=score.loc[d].dropna();y=labels.loc[d].reindex(s.index)
        if len(s)<100:continue
        ic=s.rank().corr(y.fillna(-1.).rank());assert np.isfinite(ic)
        rows.append(dict(signal_date=str(d.date()),label_end=str(dates[i+20].date()),n=len(s),missing_terminal=int(y.isna().sum()),ic=float(ic)))
    assert rows
    return dict(mean_ic=float(np.mean([r['ic'] for r in rows])),periods=rows)
def train():
    if (HERE/'frozen.json').exists():raise RuntimeError('Already frozen; retraining refused')
    q=read('protocol.json');train_data=features('training');trials=[]
    for a in q['grid']['cap']:
        for b in q['grid']['vol']:
            w=[a,b,.25,round(1-a-b-.25,10)]
            trials.append(dict(id=len(trials)+1,weights=w,distance=float(np.abs(np.array(w)-[.35,.2,.25,.2]).sum()),training=metric(train_data,w,'training')))
    trials.sort(key=lambda t:(-t['training']['mean_ic'],t['distance'],t['id']));dump('training_results.json',trials);dump('shortlist.json',[t['id'] for t in trials[:3]])
    del train_data
    valid=features('selection');selected=[dict(t,selection=metric(valid,t['weights'],'selection')) for t in trials[:3]]
    selected.sort(key=lambda t:(-t['selection']['mean_ic'],-t['training']['mean_ic'],t['distance'],t['id']));dump('selection_results.json',selected);winner=selected[0]
    source=PARENT/'supermind_test2_D11_fast_cutoff_20241130.py';code=source.read_text(encoding='utf-8');code=code[code.index('from mindgo_api import *'):]
    for name,w in zip(['CAP_WEIGHT','VOL_WEIGHT','OVERNIGHT_WEIGHT','INTRADAY_WEIGHT'],winner['weights']):code=re.sub('^'+name+r' = .*$',name+' = '+repr(w),code,flags=re.M)
    code=code.replace("TRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'","TRAINING_CUTOFF_EXCLUSIVE = '2023-01-01'\nSELECTION_CUTOFF_EXCLUSIVE = '2024-01-01'")
    code=re.sub(r'^VERSION = .*$',"VERSION = '2026-10-05-D11-fast-retrained2022'",code,flags=re.M)
    code='# -*- coding: utf-8 -*-\n# D11独立重训候选：每日频率，10万元。2019—2022拟合，2023选参。\n# 2024确认和2025后仅冻结评价，非真正未见盲测；未在平台服务器验证。\n'+code
    compile(code,'export','exec');target=HERE/'supermind_test2_D11_fast_retrained_2022.py';target.write_text(code,encoding='utf-8')
    dump('frozen.json',dict(winner=winner,protocol_sha256=sha(HERE/'protocol.json'),pipeline_sha256=sha(Path(__file__)),source_sha256=sha(source),export_sha256=sha(target),
        feature_source_sha256=sha(PARENT/'test2_cutoff_20241130/train.py'),training_inputs_sha256=sha(HERE/'training_inputs.json'),selection_inputs_sha256=sha(HERE/'selection_inputs.json'),held_out_read_before_freeze=False))
    print('FROZEN',winner['weights'],winner['training']['mean_ic'],winner['selection']['mean_ic'],flush=True)
def confirm():
    f=read('frozen.json');assert sha(HERE/'protocol.json')==f['protocol_sha256']
    if (HERE/'confirmation.json').exists():raise RuntimeError('Already confirmed')
    x=features('confirmation');result=metric(x,f['winner']['weights'],'confirmation');result['passed']=result['mean_ic']>0;dump('confirmation.json',result);print('CONFIRM',result['mean_ic'],result['passed'],flush=True)
def evaluation_signals():
    f=read('frozen.json');x=features('evaluation');ranks,eligible,prices,dates=x;score=smooth(ranks,eligible,f['winner']['weights']);wanted=set()
    for start,end in [('2023-01-01','2023-12-31'),('2024-01-01','2024-11-29'),('2025-01-01','2026-09-30')]:
        ds=dates[(dates>=start)&(dates<=end)]
        for d in ds:
            i=dates.get_loc(d)
            if d==ds[0] or (i-1)%20==0:wanted.add(dates[i-1])
    result={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist() for d in sorted(wanted)}
    dump('evaluation_rankings.json',result)
if __name__=='__main__':{'train':train,'confirm':confirm,'signals':evaluation_signals}[sys.argv[1]]()
