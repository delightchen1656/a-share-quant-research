"""Second bounded round: fixed event classifier, stop-model regularization."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
PREVIOUS=ROOT/'tuning_v1'
sys.path.insert(0,str(PREVIOUS))
import tune as common
p=common.p
pd=common.pd
joblib=common.joblib
HGB=common.HistGradientBoostingClassifier
OUT=HERE/'results'
CONFIGS=[{'name':f'{weight or "unweighted"}_leaf{leaves}','weight':weight,'leaves':leaves,
          'min_leaf':250 if leaves==3 else 100,'l2':20 if leaves==3 else 10,'iterations':120}
         for weight in ['balanced',None] for leaves in [3,7,15]]

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'frozen.json').exists():raise RuntimeError('Frozen round; selection cannot be rerun.')
    preserved={str(f):p.sha(f) for f in [PREVIOUS/'event_model.joblib',PREVIOUS/'stop_model.joblib',PREVIOUS/'supermind_baseline_3_2_tuned_daily.py',ROOT/'supermind_baseline_3_2_retrained_daily.py',p.SOURCE]}
    protocol={'fit':['2020-01-01','2022-12-31'],'selection':['2023-01-01','2023-12-31'],
        'configs':CONFIGS,'stop_thresholds':[.25,.35,.45],'event_model':'frozen tuning_v1; threshold .65',
        'objective':'2023 CAGR - .5*abs(maxDD) + .25*worst quarterly return',
        'eligibility':'at least 40 fills and average exposure >=15%',
        'gate':'2023 positive return, >=2 positive quarters, objective above control',
        'budget':18,'reselect_after_confirmation':False,'preserved':preserved}
    p.save(HERE/'protocol.json',protocol)
    tr,_,_=p.dataset(ROOT/'snapshots/2022-12-31','2020-01-01','2022-12-31')
    va,panels,meta=p.dataset(ROOT/'snapshots/2023-12-31','2023-01-01','2023-12-31')
    tr=p.labeled(tr,'stop_label','2020-01-01','2022-12-31')
    assert tr.stop_end.max()<=pd.Timestamp('2022-12-31')
    p.save(OUT/'training_boundary.json',{'rows':len(tr),'max_anchor':str(tr.date.max()),'max_label_end':str(tr.stop_end.max())})
    original=[joblib.load(PREVIOUS/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    event=original[0]
    p.OUT=OUT;p.HERE=HERE;p.PLATFORM=HERE/'supermind_baseline_3_2_tuning_v2_daily.py';common.OUT=OUT
    p.save(OUT/'corporate_actions.json',p.json.loads((PREVIOUS/'results/corporate_actions.json').read_text(encoding='utf-8')))
    models={'control':original[1]};results=[]
    r=common.evaluate(p.signals(va,original),panels,meta,'2023-01-01','2023-12-31',.65,.35,'control_2023')
    r.update(candidate='control',stop_threshold=.35);results.append(r)
    for cfg in CONFIGS:
        m=HGB(max_iter=120,learning_rate=.04,max_leaf_nodes=cfg['leaves'],min_samples_leaf=cfg['min_leaf'],
            l2_regularization=cfg['l2'],class_weight=cfg['weight'],early_stopping=False,random_state=73)
        m.fit(tr[p.F],tr.stop_label.astype(int));models[cfg['name']]=m
        scored=p.signals(va,[event,m])
        for threshold in [.25,.35,.45]:
            r=common.evaluate(scored,panels,meta,'2023-01-01','2023-12-31',.65,threshold,cfg['name']+'_'+str(threshold))
            r.update(candidate=cfg['name'],stop_threshold=threshold);results.append(r)
            print('CANDIDATE',cfg['name'],threshold,'return',round(r['total_return'],4),'score',round(r['objective'],4),flush=True)
    pd.DataFrame(results).to_csv(OUT/'selection_2023.csv',index=False,encoding='utf-8-sig')
    eligible=[r for r in results if r['fills']>=40 and r['avg_exposure']>=.15]
    best=max(eligible,key=lambda r:(r['objective'],r['sharpe_rf0']))
    gate=best['total_return']>0 and best['positive_quarters']>=2 and best['objective']>results[0]['objective']
    selected=[event,models[best['candidate']]]
    p.export(selected,.65,best['stop_threshold'],va.sample(min(5000,len(va)),random_state=42))
    # Cosmetic version identity is fixed before any later-period evaluation.
    text=p.PLATFORM.read_text(encoding='utf-8').replace('科创3-2：2022截止重训测试版','科创3-2：规范调参V2（研究）')
    p.PLATFORM.write_text(text,encoding='utf-8')
    lock={'best':best,'development_gate_passed':bool(gate),'platform_sha256':p.sha(p.PLATFORM),
          'event_sha256':p.sha(HERE/'event_model.joblib'),'stop_sha256':p.sha(HERE/'stop_model.joblib'),
          'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'future_used_for_selection':False}
    p.save(OUT/'frozen.json',lock);print('FROZEN',lock,flush=True)
    rows=[dict(results[0],stage='2023',version='v1'),dict(best,stage='2023',version='v2')]
    for stage,start,end in [('2020_2022','2020-01-01','2022-12-31'),('2024','2024-01-01','2024-12-31'),('2025_2026','2025-01-01',p.END)]:
        ds,panels,meta=p.dataset(ROOT/'snapshots'/end,start,end)
        for kind,ms,st in [('v1',original,.35),('v2',selected,best['stop_threshold'])]:
            r=common.evaluate(p.signals(ds,ms),panels,meta,start,end,.65,st,stage+'_'+kind)
            r.update(stage=stage,version=kind);rows.append(r)
            print('EVALUATION',stage,kind,'CAGR',round(r['cagr'],4),'DD',round(r['max_drawdown'],4),flush=True)
        assert p.sha(p.PLATFORM)==lock['platform_sha256'] and p.sha(HERE/'stop_model.joblib')==lock['stop_sha256']
    pd.DataFrame(rows).to_csv(OUT/'comparison.csv',index=False,encoding='utf-8-sig')
    assert all(p.sha(Path(file))==digest for file,digest in preserved.items())
    p.save(OUT/'completion.json',{'completed':True,'gate_passed':bool(gate),'selection_count':len(results),'preserved_sources':True})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
