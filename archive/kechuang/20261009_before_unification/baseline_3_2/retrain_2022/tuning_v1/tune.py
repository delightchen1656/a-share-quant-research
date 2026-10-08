"""Bounded regularization search. No future-period feedback or repeat selection."""
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import pipeline as p
import contextlib
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier

OLD=HERE.parent
OUT=HERE/'results'
CONFIGS=[
    {'name':'shallow','leaves':5,'min_leaf':100,'l2':10,'iterations':120},
    {'name':'shallow_smooth','leaves':5,'min_leaf':250,'l2':20,'iterations':180},
    {'name':'medium','leaves':7,'min_leaf':100,'l2':10,'iterations':120},
    {'name':'medium_smooth','leaves':7,'min_leaf':250,'l2':20,'iterations':180},
    {'name':'wide','leaves':15,'min_leaf':100,'l2':10,'iterations':120},
    {'name':'wide_smooth','leaves':15,'min_leaf':250,'l2':20,'iterations':180},
]

def evaluate(scores,panels,meta,start,end,pt,st,name):
    with (OUT/'execution.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        r=p.replay_stage(scores,panels,meta,start,end,pt,st,name)
    curve=pd.read_parquet(OUT/name/'daily_equity.parquet')
    rets=curve.set_index('date').equity.pct_change();rets.iloc[0]=curve.equity.iloc[0]/1e6-1
    quarters=(1+rets).groupby(rets.index.to_period('Q')).prod()-1
    r.update(worst_quarter=float(quarters.min()),positive_quarters=int((quarters>0).sum()),
        objective=float(r['cagr']-.5*abs(r['max_drawdown'])+.25*quarters.min()))
    return r

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'frozen.json').exists():raise RuntimeError('Already frozen; no re-selection allowed.')
    protocol={'fit':'2020-2022, complete labels only','selection':'2023 only','confirmation':'2024, read after freeze',
        'historical_test':'2025-2026-09-30, read after freeze','configs':CONFIGS,'thresholds':[.55,.65,.75],
        'stop_model':'previous fixed 2020-2022 fitted model; threshold .35 unchanged',
        'score':'2023 CAGR - 0.5*abs(maxDD) + 0.25*worst quarterly return',
        'eligibility':'at least 40 fills, average exposure >=15%',
        'promotion_gate':'positive 2023 total return, >=2 positive quarters and objective > control',
        'budget':'18 new configurations plus unchanged control; no expansion after viewing results',
        'warning':'All later periods previously inspected. Not pristine independent OOS.',
        'old_platform_sha256':p.sha(OLD/'supermind_baseline_3_2_retrained_daily.py')}
    p.save(HERE/'protocol.json',protocol)
    # Reuse immutable physical snapshots; never reconstruct from full future panel.
    tr,_,_=p.dataset(OLD/'snapshots/2022-12-31','2020-01-01','2022-12-31')
    va,panels,meta=p.dataset(OLD/'snapshots/2023-12-31','2023-01-01','2023-12-31')
    tr=p.labeled(tr,'label','2020-01-01','2022-12-31')
    assert tr.event_end.max()<=pd.Timestamp('2022-12-31')
    old_models=[joblib.load(OLD/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    stop=old_models[1]
    p.OUT=OUT;p.HERE=HERE;p.PLATFORM=HERE/'supermind_baseline_3_2_tuned_daily.py'
    p.save(OUT/'corporate_actions.json',p.json.loads((OLD/'results/corporate_actions.json').read_text(encoding='utf-8')))
    models={'control':old_models[0]};results=[]
    r=evaluate(p.signals(va,old_models),panels,meta,'2023-01-01','2023-12-31',.63,.35,'control_2023')
    r.update(candidate='control',threshold=.63);results.append(r)
    for cfg in CONFIGS:
        m=HistGradientBoostingClassifier(max_iter=cfg['iterations'],learning_rate=.04,max_leaf_nodes=cfg['leaves'],
            min_samples_leaf=cfg['min_leaf'],l2_regularization=cfg['l2'],class_weight='balanced',early_stopping=False,random_state=42)
        m.fit(tr[p.F],tr.label.astype(int));models[cfg['name']]=m
        sc=p.signals(va,[m,stop])
        for pt in [.55,.65,.75]:
            name=cfg['name']+'_'+str(pt)
            r=evaluate(sc,panels,meta,'2023-01-01','2023-12-31',pt,.35,name)
            r.update(candidate=cfg['name'],threshold=pt);results.append(r)
            print('CANDIDATE',name,'return',round(r['total_return'],4),'score',round(r['objective'],4),flush=True)
    pd.DataFrame(results).to_csv(OUT/'selection_2023.csv',index=False,encoding='utf-8-sig')
    eligible=[r for r in results if r['fills']>=40 and r['avg_exposure']>=.15]
    best=max(eligible,key=lambda r:(r['objective'],r['sharpe_rf0']))
    promoted=best['candidate']!='control' and best['total_return']>0 and best['positive_quarters']>=2 and best['objective']>results[0]['objective']
    selected=[models[best['candidate']],stop]
    p.export(selected,best['threshold'],.35,va.sample(min(5000,len(va)),random_state=42))
    lock={'best':best,'development_gate_passed':promoted,'platform_sha256':p.sha(p.PLATFORM),
        'event_sha256':p.sha(HERE/'event_model.joblib'),'stop_sha256':p.sha(HERE/'stop_model.joblib'),
        'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'future_used_for_selection':False}
    p.save(OUT/'frozen.json',lock);print('FROZEN',lock,flush=True)
    comparisons=[]
    for stage,start,end in [('2020_2022','2020-01-01','2022-12-31'),('2024','2024-01-01','2024-12-31'),('2025_2026','2025-01-01',p.END)]:
        ds,panels,meta=p.dataset(OLD/'snapshots'/end,start,end)
        for kind,ms,pt in [('control',old_models,.63),('candidate',selected,best['threshold'])]:
            scores=p.signals(ds,ms)
            r=evaluate(scores,panels,meta,start,end,pt,.35,stage+'_'+kind)
            r.update(stage=stage,version=kind);comparisons.append(r)
            print('EVALUATION',stage,kind,'CAGR',round(r['cagr'],4),'DD',round(r['max_drawdown'],4),flush=True)
        assert p.sha(p.PLATFORM)==lock['platform_sha256'] and p.sha(HERE/'event_model.joblib')==lock['event_sha256']
    for kind,r in [('control',results[0]),('candidate',best)]:comparisons.append(dict(r,stage='2023',version=kind))
    pd.DataFrame(comparisons).to_csv(OUT/'comparison.csv',index=False,encoding='utf-8-sig')
    assert p.sha(OLD/'supermind_baseline_3_2_retrained_daily.py')==protocol['old_platform_sha256']
    p.save(OUT/'completion.json',{'completed':True,'gate_passed':promoted,'selection_count':len(results),'old_version_unchanged':True})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
