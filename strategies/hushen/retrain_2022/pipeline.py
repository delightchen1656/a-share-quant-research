from pathlib import Path
import importlib.util,json,hashlib,sys,re,warnings
import pandas as pd
import numpy as np
import pyarrow.parquet as pq
warnings.filterwarnings('ignore',category=FutureWarning)
HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
ROOT=PARENT.parents[1]
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'
COLS=['date','open','high','low','close','preclose','volume','amount','turn','tradestatus','isST']
def dump(name,x): (HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def read(name):return json.loads((HERE/name).read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def mod(p,name):
    spec=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def features(end,name):
    """A physically bounded stage snapshot; no observations after end returned."""
    out=HERE/name;out.mkdir(exist_ok=True)
    limit=pd.Timestamp(end)+pd.Timedelta(days=1)
    b=pq.read_table(PARENT/'start_date_study/benchmark.parquet',filters=[('date','<',limit.to_pydatetime())]).to_pandas()
    assert pd.to_datetime(b.date).max()<limit
    b.to_parquet(out/'benchmark.parquet',index=False);market=b.set_index('date').close
    engine=mod(PARENT/'cutoff_20241130/train.py','feature_engine');engine.CUT=limit
    dates=[];last=None
    for i,d in enumerate(market.index):
        if d<pd.Timestamp('2019-01-01'):continue
        due=last is None or (last!=(d.year,d.month) and d.month%2==1)
        last=(d.year,d.month)
        if due and i>=273:dates.append(market.index[i-1])
    sd=pd.DatetimeIndex(dates);chunks=[];files=[]
    for i,p in enumerate(sorted((DATA/'raw').glob('*/*.parquet'))):
        x=pq.read_table(p,columns=COLS,filters=[('date','<',limit.to_pydatetime())]).to_pandas()
        if x.empty:continue
        x.date=pd.to_datetime(x.date);x=x.sort_values('date');assert x.date.max()<limit
        dest=out/p.name;x.to_parquet(dest,index=False);files.append(dict(symbol=p.stem,sha256=sha(dest),max_date=str(x.date.max().date())))
        f,_,_=engine.features(x,market);f=f.reindex(sd);f=f[f.eligible & f.label_end.notna() & (f.label_end<limit)].copy()
        f['symbol']=p.stem;f.index.name='signal_date';chunks.append(f.reset_index())
        if (i+1)%700==0:print(name,i+1,flush=True)
    data=pd.concat(chunks,ignore_index=True);frames=[]
    for d,x in data.groupby('signal_date'):
        x=x.sort_values('symbol').replace([np.inf,-np.inf],np.nan)
        group=np.minimum(np.floor(x.float_cap_proxy.rank(pct=True)*3),2)
        x=x[group==1].dropna(subset=['long_risk','market_adjusted','distribution_proxy','vol60','ret5','turn20']).copy()
        x['d']=x.distribution_proxy.rank(pct=True);x['m']=x.long_risk.rank(pct=True);x['v']=1-x.vol60.rank(pct=True)
        frames.append(x)
    result=pd.concat(frames,ignore_index=True);result.to_parquet(HERE/(name+'_samples.parquet'),index=False)
    dump(name+'_manifest.json',dict(max_observation=max(v['max_date'] for v in files),files=files,benchmark_sha256=sha(out/'benchmark.parquet'),samples_sha256=sha(HERE/(name+'_samples.parquet'))))
    return result
def metric(data,weights):
    rows=[]
    for d,x in data.groupby('signal_date'):
        score=weights[0]*x.d+weights[1]*x.m+weights[2]*x.v
        ic=score.rank().corr(x.label.rank());assert np.isfinite(ic)
        rows.append(dict(signal_date=str(d.date()),label_end=str(x.label_end.iloc[0].date()),n=len(x),ic=ic,missing_terminal=int(x.missing_terminal.sum())))
    assert rows
    return dict(mean_ic=float(np.mean([r['ic'] for r in rows])),positive_fraction=float(np.mean([r['ic']>0 for r in rows])),periods=rows)
def train():
    if (HERE/'frozen.json').exists():raise RuntimeError('Already frozen: retraining/feedback search refused')
    protocol=read('protocol.json');ph=sha(HERE/'protocol.json')
    tr=features('2022-12-31','training_snapshot');tr=tr[(tr.signal_date>='2019-01-01')&(tr.label_end<'2023-01-01')]
    trials=[]
    for d in protocol['grid']['distribution']:
        for m in protocol['grid']['momentum']:
            w=[d,m,round(1-d-m,8)];result=metric(tr,w)
            trials.append(dict(id=len(trials)+1,weights=w,distance=float(np.abs(np.array(w)-[.4,.3,.3]).sum()),training=result))
    trials.sort(key=lambda t:(-t['training']['mean_ic'],t['distance'],t['id']))
    shortlist=trials[:3];dump('training_results.json',trials);dump('shortlist.json',[t['id'] for t in shortlist])
    va=features('2023-12-31','selection_snapshot');va=va[(va.signal_date>='2023-01-01')&(va.label_end<'2024-01-01')]
    selected=[]
    for trial in shortlist:selected.append(dict(trial,selection=metric(va,trial['weights'])))
    selected.sort(key=lambda t:(-t['selection']['mean_ic'],-t['training']['mean_ic'],t['distance'],t['id']))
    dump('selection_results.json',selected);winner=selected[0]
    source=PARENT/'supermind_mainboard_baseline_1_cutoff_20241130.py'
    code=source.read_text(encoding='utf-8');code=code[code.index('from mindgo_api import *'):]
    for key,value in zip(['DISTRIBUTION_WEIGHT','MOMENTUM_WEIGHT','LOW_VOL_WEIGHT'],winner['weights']):code=re.sub(r'^'+key+r' = .*$',key+' = '+repr(value),code,flags=re.M)
    code=code.replace("TRAINING_CUTOFF_EXCLUSIVE = '2024-11-30'","TRAINING_CUTOFF_EXCLUSIVE = '2023-01-01'\nSELECTION_CUTOFF_EXCLUSIVE = '2024-01-01'")
    code=re.sub(r'R08 signal=', 'R08 retrain2022 signal=',code)
    code=code.replace('沪深1 cutoff20241130 weights=0.3/0.2/0.5','沪深1 retrain2022 weights='+str(winner['weights']))
    code='# 沪深基准1独立时序重训候选；10万元；分钟频率09:31。\n# 2019—2022拟合，2023选参；2024确认及2025后不反馈优化。\n# 既有框架和后段历史已暴露，不是真正未见盲测；尚无平台服务器验证。\n'+code
    compile(code,'export','exec');entry=HERE/'supermind_mainboard_baseline_1_retrained_2022.py';entry.write_text(code,encoding='utf-8')
    dump('frozen.json',dict(winner=winner,protocol_sha256=ph,source_sha256=sha(source),export_sha256=sha(entry),pipeline_sha256=sha(Path(__file__)),
        training_manifest_sha256=sha(HERE/'training_snapshot_manifest.json'),selection_manifest_sha256=sha(HERE/'selection_snapshot_manifest.json'),
        max_fit_label=str(tr.label_end.max().date()),max_selection_label=str(va.label_end.max().date()),held_out_read_before_freeze=False))
    print('FROZEN',winner['weights'],winner['training']['mean_ic'],winner['selection']['mean_ic'],flush=True)
def confirm():
    frozen=read('frozen.json');assert sha(HERE/'protocol.json')==frozen['protocol_sha256']
    if (HERE/'confirmation.json').exists():raise RuntimeError('Confirmation already recorded')
    data=features('2024-11-29','confirmation_snapshot');data=data[(data.signal_date>='2024-01-01')&(data.label_end<'2024-11-30')]
    result=metric(data,frozen['winner']['weights']);result['passed']=result['mean_ic']>0
    dump('confirmation.json',result);print('CONFIRM',result['mean_ic'],result['passed'],flush=True)
if __name__=='__main__':
    {'train':train,'confirm':confirm}[sys.argv[1]]()
