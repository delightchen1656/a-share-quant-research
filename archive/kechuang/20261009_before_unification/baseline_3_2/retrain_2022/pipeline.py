"""Frozen chronological retraining. Run once; no holdout-driven reselection."""
import os
os.environ.setdefault('OMP_NUM_THREADS','4')
import ast
import base64
import hashlib
import importlib.util
import inspect
import json
import math
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score, roc_auc_score, brier_score_loss

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=BASE.parents[2]
DATA=ROOT/'evening_accumulation/data'
OUT=HERE/'results'
SOURCE=BASE.parent/'supermind_baseline_3_2_audited_daily.py'
PLATFORM=HERE/'supermind_baseline_3_2_retrained_daily.py'
sys.path.insert(0,str(BASE))
import start_date_study as replay
spec=importlib.util.spec_from_file_location('features_only',BASE.parent/'training_source/src/model.py')
feature=importlib.util.module_from_spec(spec);spec.loader.exec_module(feature)
F=feature.FEATURES
END='2026-09-30'

def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def protocol():
    return {'fit':['2020-01-01','2022-12-31'],'selection':['2023-01-01','2023-12-31'],
        'confirmation':['2024-01-01','2024-12-31'],'historical_test':['2025-01-01',END],
        'model_candidates_leaves':[7,15,31],'iterations':180,'learning_rate':.04,
        'early_stopping':False,'event_thresholds':[.50,.63,.75],'stop_thresholds':[.35,.50,.65],
        'model_selection':'highest 2023 average precision separately for each label; ties prefer fewer leaves',
        'threshold_selection':'highest 2023 net Sharpe, ties net CAGR; require at least 20 fills',
        'fit_after_selection':False,'feature_count':18,'feature_selection':'fixed prior 3-2 features; no search',
        'label_event':'20 complete future bars, high/anchor close >=1.30',
        'label_stop':'22 complete future bars, open/anchor close <=.93 before >=1.24',
        'label_cutoff':'each label_end must be <= its stage end; form before eligibility filtering',
        'initial_cash':1000000,'execution':'inherited local 3-2 audited approximation; prior-day signals at next open',
        'warning':'Previously inspected 2025-2026; isolated historical test, NOT pristine independent OOS',
        'source_sha256':sha(SOURCE),'local_replay_sha256':sha(BASE/'start_date_study.py'),
        'timestamp':pd.Timestamp.now(tz='Asia/Shanghai').isoformat()}

def snapshot(cutoff):
    """Materialize only cutoff rows before any feature/label computation."""
    dest=HERE/'snapshots'/cutoff
    manifest={}
    for kind in ['raw','qfq']:
        (dest/kind).mkdir(parents=True,exist_ok=True)
        for file in sorted((DATA/kind).glob('688*.parquet')):
            p=pd.read_parquet(file,filters=[('date','<=',pd.Timestamp(cutoff))]).sort_values('date')
            if p.empty:continue
            assert p.date.max()<=pd.Timestamp(cutoff)
            target=dest/kind/file.name
            p.to_parquet(target,index=False)
            manifest[kind+'/'+file.name]={'sha256':sha(target),'rows':len(p),'max_date':str(p.date.max().date())}
    save(dest/'manifest.json',manifest)
    print('SNAPSHOT',cutoff,len(manifest),flush=True)
    return dest

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

def labeled(ds,target,start,end):
    label_end='event_end' if target=='label' else 'stop_end'
    x=ds.loc[(ds.date>=start)&(ds.date<=end)&ds[target].notna()&ds[label_end].le(pd.Timestamp(end))].copy()
    assert x[label_end].max()<=pd.Timestamp(end) and x.date.min()>=pd.Timestamp(start)
    return x

def metrics(ds,target,p):
    return {'rows':len(ds),'positive_rate':float(ds[target].mean()),'AP':float(average_precision_score(ds[target],p)),
            'AUC':float(roc_auc_score(ds[target],p)),'brier':float(brier_score_loss(ds[target],p))}

def train(train_ds,val_ds):
    models=[];reports=[]
    for target in ['label','stop_label']:
        tr=labeled(train_ds,target,'2020-01-01','2022-12-31');va=labeled(val_ds,target,'2023-01-01','2023-12-31')
        candidates=[]
        for leaves in [7,15,31]:
            m=HistGradientBoostingClassifier(max_iter=180,learning_rate=.04,max_leaf_nodes=leaves,l2_regularization=3,
                class_weight='balanced',early_stopping=False,random_state=42 if target=='label' else 73)
            m.fit(tr[F],tr[target].astype(int))
            score=metrics(va,target,m.predict_proba(va[F])[:,1])
            score.update(target=target,leaves=leaves,train_rows=len(tr),train_max_anchor=str(tr.date.max().date()),
                train_max_label_end=str(tr['event_end' if target=='label' else 'stop_end'].max().date()))
            reports.append(score);candidates.append((score['AP'],-leaves,m))
            print('FIT',target,leaves,score,flush=True)
        selected=max(candidates,key=lambda x:x[:2]);models.append(selected[2])
    save(OUT/'model_selection_2023.json',reports)
    return models

def portable(m,event,threshold):
    trees=[]
    for iteration in m._predictors:
        assert len(iteration)==1
        nodes=iteration[0].nodes
        assert not nodes['is_categorical'].any()
        trees.append([{'f':int(n['feature_idx']),'t':float(n['num_threshold']),'m':bool(n['missing_go_to_left']),
            'l':int(n['left']),'r':int(n['right']),'leaf':bool(n['is_leaf']),'v':float(n['value'])} for n in nodes])
    result={'format':'portable_hist_gradient_boosting_v1','features':F,'baseline':float(m._baseline_prediction[0,0]),
            'trees':trees,'threshold':threshold,'training_end':'2022-12-31','training_start':'2020-01-01'}
    if event:result.update(top_per_day=8,max_positions=14,universe=[])
    else:result.update(rank_penalty=.22,label='next_22_complete_bars_stop7_before_profit24')
    return result

def namespace(source):
    tree=ast.parse(source)
    ns={'np':np,'pd':pd,'math':math,'base64':base64,'zlib':zlib,'json':json,'g':SimpleNamespace()}
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.Assign))],type_ignores=[]),'<export>','exec'),ns)
    return ns

def fast(m):
    m=dict(m)
    m['fast_trees']=[tuple(np.array([n[k] for n in t],dtype=d) for k,d in [('f',int),('t',float),('m',bool),('l',int),('r',int),('leaf',bool),('v',float)]) for t in m['trees']]
    return m

def signals(ds,models):
    x=ds.copy()
    x['p']=models[0].predict_proba(x[F])[:,1];x['stop']=models[1].predict_proba(x[F])[:,1]
    x['score']=x.p-.22*x.stop
    return x

def replay_stage(scores,panels,meta,start,end,p_threshold,s_threshold,name):
    dest=OUT/name;dest.mkdir(parents=True,exist_ok=True)
    x=scores[(scores.p>=p_threshold)&(scores.stop<=s_threshold)].sort_values(['date','score','symbol'],ascending=[True,False,True])
    candidates={d:list(g.head(8).symbol) for d,g in x.groupby('date')}
    cal=pd.read_csv(DATA/'metadata/trade_calendar_20261004.csv')
    dates=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>=pd.Timestamp(start)-pd.Timedelta(days=12))&(dates<=end)]
    symbols=set(s for values in candidates.values() for s in values);requests=set()
    for s in symbols:
        rows=panels[s]
        ev=rows[(abs(rows.adjust_ratio-1)>1e-5)&(rows.index>=start)&(rows.index<=end)]
        requests.update((s,int(d.year)) for d in ev.index)
    cache_path=OUT/'corporate_actions.json'
    if not cache_path.exists():
        old=BASE/'start_dates_2021q1_to_20260930/corporate_actions.json'
        save(cache_path,json.loads(old.read_text(encoding='utf-8')) if old.exists() else {})
    actions_ns=dict(replay.__dict__);actions_ns['OUT']=OUT
    exec(inspect.getsource(replay.actions),actions_ns)
    actions=actions_ns['actions'](requests)
    # Original audited simulator is reused, not the old training simulator.
    ns=namespace(SOURCE.read_text(encoding='utf-8'));ns['g'].model={'max_positions':14,'top_per_day':8}
    env=dict(replay.__dict__);env.update(OUT=dest,END=pd.Timestamp(end),plot=lambda _:None)
    src=inspect.getsource(replay.run_starts)
    old="starts=dates[(dates>='2021-01-01')&(dates<='2021-03-31')]"
    assert old in src
    src=src.replace(old,"starts=dates[dates>=pd.Timestamp('"+start+"')][:1]")
    exec(src,env)
    env['run_starts']((ns,[{'max_positions':14,'top_per_day':8}],dates,panels,candidates,meta,requests),actions)
    return pd.read_csv(dest/'start_date_results.csv').iloc[0].to_dict()

def export(models,pt,st,check_rows):
    blobs=[portable(m,i==0,pt if i==0 else st) for i,m in enumerate(models)]
    text=SOURCE.read_text(encoding='utf-8');tree=ast.parse(text)
    replacements={'_EMBEDDED_MODEL_B64':base64.b64encode(zlib.compress(json.dumps(blobs[0]).encode())).decode(),
        '_EMBEDDED_STOP_MODEL_B64':base64.b64encode(zlib.compress(json.dumps(blobs[1]).encode())).decode(),
        'SIGNAL_THRESHOLD':pt,'STRATEGY_VERSION':'科创3-2：2022截止重训测试版'}
    for node in tree.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in replacements:
            node.value=ast.Constant(value=replacements[node.targets[0].id])
    tree.body[0].value=ast.Constant(value='Chronological 3-2 retrain: fit 2020-2022, select 2023, confirm 2024; isolated historical test 2025+. Not pristine OOS.')
    text=ast.unparse(ast.fix_missing_locations(tree))
    assert 'stop[i] <= 0.5' in text
    text=text.replace('stop[i] <= 0.5','stop[i] <= '+repr(st))
    # 000688 has insufficient early history; use a long-lived index only as calendar.
    text=text.replace("benchmark = history(['000688.SH']","benchmark = history(['000001.SH']")
    text=text.replace("_past(benchmark.get('000688.SH'), today)","_past(benchmark.get('000001.SH'), today)")
    compile(text,str(PLATFORM),'exec');PLATFORM.write_text(text+'\n',encoding='utf-8')
    ns=namespace(text);errors=[]
    for i,key in enumerate(['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']):
        model=json.loads(zlib.decompress(base64.b64decode(ns[key])))
        error=float(np.max(abs(models[i].predict_proba(check_rows[F])[:,1]-ns['_batch_probabilities'](fast(model),check_rows[F].to_numpy()))))
        assert error<1e-10;errors.append(error)
        joblib.dump({'model':models[i],'features':F,'training_end':'2022-12-31'},HERE/('event_model.joblib' if i==0 else 'stop_model.joblib'))
    save(OUT/'export_validation.json',{'maximum_probability_errors':errors,'rows':len(check_rows),'compile':'passed','platform_runtime':'not executed on SuperMind'})

def main():
    OUT.mkdir(exist_ok=True)
    if (OUT/'frozen.json').exists():raise RuntimeError('Already frozen. Do not rerun selection after holdout inspection.')
    pr=protocol();save(HERE/'protocol.json',pr)
    tr,_,_=dataset(snapshot('2022-12-31'),'2020-01-01','2022-12-31')
    va,panels,meta=dataset(snapshot('2023-12-31'),'2023-01-01','2023-12-31')
    models=train(tr,va);scored=signals(va,models)
    results=[]
    for pt in pr['event_thresholds']:
        for st in pr['stop_thresholds']:
            r=replay_stage(scored,panels,meta,'2023-01-01','2023-12-31',pt,st,f'selection_p{pt}_s{st}')
            r.update(p_threshold=pt,s_threshold=st);results.append(r)
    pd.DataFrame(results).to_csv(OUT/'threshold_selection_2023.csv',index=False,encoding='utf-8-sig')
    valid=[r for r in results if r['fills']>=20 and np.isfinite(r['sharpe_rf0'])]
    if not valid:raise RuntimeError('No 2023 candidate meets minimum fills; no holdout opened.')
    best=max(valid,key=lambda r:(r['sharpe_rf0'],r['cagr']));pt=best['p_threshold'];st=best['s_threshold']
    export(models,pt,st,va.sample(min(5000,len(va)),random_state=42))
    lock={'selected':best,'event_model_sha256':sha(HERE/'event_model.joblib'),'stop_model_sha256':sha(HERE/'stop_model.joblib'),
          'platform_sha256':sha(PLATFORM),'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
          'fit_cutoff':'2022-12-31','selection_end':'2023-12-31','never_refit_on_validation':True}
    save(OUT/'frozen.json',lock);print('FROZEN',lock,flush=True)
    stages=[dict(best,stage='2023_selection')]
    # Training replay is descriptive, does not affect selection.
    for name,start,end in [('2020_2022_fit','2020-01-01','2022-12-31'),('2024_confirmation','2024-01-01','2024-12-31'),('2025_2026_test','2025-01-01',END)]:
        dest=HERE/'snapshots'/end
        if not dest.exists():dest=snapshot(end)
        ds,panels,meta=dataset(dest,start,end);scored=signals(ds,models)
        scored[['date','symbol','p','stop','score']].to_parquet(OUT/(name+'_scores.parquet'),index=False)
        report={}
        for target,i in [('label',0),('stop_label',1)]:
            x=labeled(ds,target,start,end)
            report[target]=metrics(x,target,models[i].predict_proba(x[F])[:,1])
        save(OUT/(name+'_classification.json'),report)
        r=replay_stage(scored,panels,meta,start,end,pt,st,name);r['stage']=name;stages.append(r)
        assert sha(PLATFORM)==lock['platform_sha256'] and sha(HERE/'event_model.joblib')==lock['event_model_sha256'] and sha(HERE/'stop_model.joblib')==lock['stop_model_sha256']
    pd.DataFrame(stages).to_csv(OUT/'stage_comparison.csv',index=False,encoding='utf-8-sig')
    assert sha(SOURCE)==pr['source_sha256'] and sha(BASE/'start_date_study.py')==pr['local_replay_sha256']
    save(OUT/'completion.json',{'completed':True,'stages':stages,'original_source_unchanged':True,'holdout_reselection':False})
    print('COMPLETE',json.dumps(stages,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
