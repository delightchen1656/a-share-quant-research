"""Phase 1: from-scratch models and predeclared 2023 CAGR selection, fixed 500k."""
from pathlib import Path
import sys, inspect, json, itertools
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'baseline_3_2/retrain_2022'
sys.path.insert(0,str(BASE/'search_1000'))
import search as s
p=s.p; pd=s.pd; np=s.np
OUT=HERE/'results'

def dataset(start,end):
    folder=BASE/'snapshots'/end
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(folder/f)==r['sha256'] for f,r in manifest.items())
    return p.dataset(folder,start,end)

def engine(panels,meta,start,end,actions):
    # Audited previous-close exit; expiry takes precedence over unsellable half.
    # Standard fixed 10% sizing, not the dynamic20 derivative.
    source=inspect.getsource(s.executor).replace('prepared_days=days,print=', 'prepared_days=days,CASH=500000.,print=').replace('/1e6-1','/500000.-1')
    env=dict(s.__dict__);exec(source,env)
    return env['executor'](panels,meta,start,end,actions)

def record(name,result):
    s.save_run(name,result)
    r,c,t,d=result
    assert c.cash.min()>=-.01
    assert np.isclose(c.equity.iloc[-1]/500000-1,r['total_return'])
    fees=float(t.fee.fillna(0).sum()) if 'fee' in t else 0.
    return dict(r,stage=name,fees=fees,reference_price_differences=len(d))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    s.OUT=OUT;p.OUT=OUT;p.HERE=HERE
    p.PLATFORM=HERE/'supermind_rebuild_research_daily.py'
    protocol={'capital':500000,'additional_capital':False,'frequency':'daily',
      'fit':['2020-01-01','2022-12-31'],'select':['2023-01-01','2023-12-31'],
      'confirm':['2024-01-01','2024-12-31'],'historical_test':['2025-01-01','2026-09-30'],
      'model':'HistGradientBoostingClassifier; fresh fit, no pretrained trees',
      'leaves':[7,15,31],'max_iter':180,'learning_rate':.04,'l2':3,'class_weight':'balanced',
      'event_thresholds':[.50,.63,.75],'stop_thresholds':[.35,.50,.65],
      'trial_budget':81,'selection':'2023 net CAGR descending; ties fewer leaves then candidate id',
      'minimum_fills':20,'drawdown_limit':None,'sizing':'fixed 10%, max14, top8',
      'features':'18 fixed technical features; no future feature selection',
      'labels':'20 future bars high>=1.30 close; 22 future opens stop7 before profit24; label end bounded per split',
      'hypotheses':['event scoring improves a simple trend ranking','stop head reduces adverse entries','strong trend extension retains winners'],
      'falsification':'nonpositive development CAGR or failure of component controls prevents automatic promotion',
      'execution':'previous-close signals, next-open fills; audited expiry priority; buy before sell; historical surviving/retired pool',
      'cost_limitations':'0.2% slip each side, commission .0003 min5, stamp .001 throughout, dividend tax20%, no transfer fee; provisional not full historical cost audit',
      'remaining_full_process':['historical fee/FIFO tax rebuild','equal-weight investable comparator','equal-length and start-date robustness','capacity delay cost stresses','order event fault tests','forward simulation'],
      'source_hashes':{str(f):p.sha(f) for f in [BASE/'pipeline.py',BASE/'search_1000/search.py',p.BASE/'start_date_study.py',p.SOURCE]},
      'no_post2023_selection':True,'status':'phase1 research; not production or original 3-1 replica'}
    protocol_path=HERE/'protocol.json'
    if protocol_path.exists():assert json.loads(protocol_path.read_text(encoding='utf-8'))==protocol
    else:p.save(protocol_path,protocol)
    cache={}
    for f in BASE.rglob('corporate_actions.json'):cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    if not (OUT/'frozen.json').exists():
        tr,_,_=dataset('2020-01-01','2022-12-31')
        va,panels,meta=dataset('2023-01-01','2023-12-31')
        models=[[],[]];pred=[[],[]];reports=[]
        for j,target in enumerate(['label','stop_label']):
            fit=p.labeled(tr,target,'2020-01-01','2022-12-31')
            val=p.labeled(va,target,'2023-01-01','2023-12-31')
            for leaves in [7,15,31]:
                model=p.HistGradientBoostingClassifier(max_iter=180,learning_rate=.04,max_leaf_nodes=leaves,l2_regularization=3,class_weight='balanced',early_stopping=False,random_state=42 if j==0 else 73)
                model.fit(fit[p.F],fit[target].astype(int))
                models[j].append(model);pred[j].append(model.predict_proba(va[p.F])[:,1])
                report=p.metrics(val,target,model.predict_proba(val[p.F])[:,1])
                report.update(target=target,leaves=leaves,train_rows=len(fit),max_label_end=str(fit['event_end' if j==0 else 'stop_end'].max()))
                reports.append(report);p.save(OUT/'model_metrics.json',reports)
                p.joblib.dump(model,HERE/f'model_{j}_{leaves}.joblib')
                print('FIT',target,leaves,flush=True)
        possible=va.loc[(np.max(pred[0],axis=0)>=.50)&(np.min(pred[1],axis=0)<=.65),'symbol'].unique()
        actions=s.prepare_actions(panels,set(possible),'2023-01-01','2023-12-31')
        execute=engine(panels,meta,'2023-01-01','2023-12-31',actions)
        rows=[]
        for idx,(a,b,pt,st) in enumerate(itertools.product(range(3),range(3),[.50,.63,.75],[.35,.50,.65]),1):
            scores=va[['date','symbol']].copy();scores['p']=pred[0][a];scores['stop']=pred[1][b];scores['score']=scores.p-.22*scores.stop
            result=execute(s.candidates(scores,pt,st))
            row=record(f'trial_{idx:03}',result)
            row.update(id=idx,event=a,stop=b,p_threshold=pt,s_threshold=st)
            rows.append(row);p.save(OUT/'all_trials_2023.json',rows)
            print('TRIAL',idx,round(row['cagr'],4),flush=True)
        valid=[r for r in rows if r['fills']>=20 and np.isfinite(r['cagr'])]
        if not valid:raise RuntimeError('No eligible development candidate; do not read holdouts')
        best=max(valid,key=lambda r:(r['cagr'],-([7,15,31][r['event']]+[7,15,31][r['stop']]),-r['id']))
        chosen=[models[0][best['event']],models[1][best['stop']]]
        p.export(chosen,best['p_threshold'],best['s_threshold'],va.sample(min(5000,len(va)),random_state=42))
        # Exported platform is a provisional audited daily implementation, not server-tested.
        lock={'selected':best,'development_positive':best['total_return']>0,'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),
              'hashes':{f:p.sha(HERE/f) for f in ['event_model.joblib','stop_model.joblib',p.PLATFORM.name]}}
        p.save(OUT/'frozen.json',lock);print('FROZEN',best['id'],flush=True)
    lock=json.loads((OUT/'frozen.json').read_text(encoding='utf-8'));best=lock['selected']
    chosen=[p.joblib.load(HERE/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    reports=[best]
    for name,start,end in [('fit','2020-01-01','2022-12-31'),('confirmation','2024-01-01','2024-12-31'),('historical_test','2025-01-01','2026-09-30'),('continuous','2020-01-01','2026-09-30')]:
        ds,panels,meta=dataset(start,end)
        scores=p.signals(ds,chosen);cand=s.candidates(scores,best['p_threshold'],best['s_threshold'])
        actions=s.prepare_actions(panels,{x for v in cand.values() for x in v},start,end)
        reports.append(record(name,engine(panels,meta,start,end,actions)(cand)))
        p.save(OUT/'comparison.json',reports)
        assert all(p.sha(HERE/f)==h for f,h in lock['hashes'].items())
        print('STAGE',name,reports[-1]['cagr'],flush=True)
    assert all(p.sha(Path(f))==h for f,h in protocol['source_hashes'].items())
    p.save(OUT/'phase1_complete.json',{'training_selection_evaluation_complete':True,'full_research_complete':False,'no_holdout_refit':True,'original_sources_unchanged':True})
    print('PHASE1 COMPLETE',flush=True)

if __name__=='__main__':main()
