"""Read frozen models; evaluate only, never fit or reselect parameters."""
from pathlib import Path
import sys, json, hashlib, inspect, os
os.environ.setdefault('OMP_NUM_THREADS','4')
HERE=Path(__file__).resolve().parent
BASE=HERE.parent
sys.path.insert(0,str(BASE/'exit_search_v1'))
import run as exits
s=exits.s
p=s.p
pd=s.pd
np=s.np
OUT=HERE/'results'
OUT.mkdir(exist_ok=True)
s.OUT=OUT
p.OUT=OUT
END='2026-09-30'
VERSIONS=[('tuning_v1',.65,.35,'candidate'),('tuning_v2',.65,.45,'v2'),
          ('search_1000',.60,.40,'winner'),('exit_search_v1',.60,.40,'exit_v1')]

def main():
    sources=[BASE/name/f for name,_,_,_ in VERSIONS for f in ['event_model.joblib','stop_model.joblib','results/frozen.json']]
    sources += [p.SOURCE,p.BASE/'start_date_study.py',BASE/'pipeline.py',BASE/'search_1000/search.py',BASE/'exit_search_v1/run.py']
    before={str(f):p.sha(f) for f in sources}
    snapshot=BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    for rel,details in manifest.items():
        assert p.sha(snapshot/rel)==details['sha256'],rel
    print('SNAPSHOT VERIFIED',len(manifest),flush=True)
    p.save(HERE/'protocol.json',{'capital':1000000,'end':END,'starts':['2020-01-01','2025-01-01'],
        'models_fitted':False,'parameters_reselected':False,'full_period_includes_training':True,
        'source_hashes':before,'snapshot_manifest_sha256':p.sha(snapshot/'manifest.json'),
        'annualization':'(final/initial)**(365.25/calendar_days)-1',
        'execution':'unchanged inherited 3-2 daily local replay'})
    cache={}
    for folder in [BASE/'results']+[BASE/name/'results' for name,_,_,_ in VERSIONS]:
        f=folder/'corporate_actions.json'
        if f.exists():cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    print('DATA READY',len(ds),flush=True)
    candidates={}
    for name,pt,st,_ in VERSIONS:
        models=[p.joblib.load(BASE/name/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
        scores=p.signals(ds,models)
        candidates[name]=s.candidates(scores,pt,st)
        print('PREDICTIONS',name,len(candidates[name]),flush=True)
    symbols={x for cand in candidates.values() for vals in cand.values() for x in vals}
    # Fetch only missing corporate-action records if the frozen cache is incomplete.
    actions=s.prepare_actions(panels,symbols,'2020-01-01',END)
    rows=[]
    rule=json.loads((BASE/'exit_search_v1/results/frozen.json').read_text())['rule']
    for start in ['2020-01-01','2025-01-01']:
        engine,state=exits.make_engine(panels,meta,start,END,actions)
        for name,_,_,old_version in VERSIONS:
            state['exit']=exits.exit_function(rule if name=='exit_search_v1' else exits.CONTROL)
            result=engine(candidates[name])
            s.save_run(name+'_'+start[:4],result)
            row=dict(result[0],version=name,period=start[:4]+'_to_latest')
            if start=='2025-01-01':
                old=pd.read_csv(BASE/name/'results/comparison.csv')
                ref=old[(old.stage=='2025_2026')&(old.version==old_version)].iloc[0]
                for field in ['final_asset','cagr','max_drawdown','sharpe_rf0','fills']:
                    assert np.isclose(row[field],ref[field],rtol=1e-10,atol=1e-7),(name,field,row[field],ref[field])
                row['existing_result_parity']=True
            rows.append(row)
            p.save(OUT/'comparison.json',rows)
            print('RESULT',name,start,round(row['cagr']*100,4),round(row['max_drawdown']*100,4),flush=True)
    assert all(p.sha(Path(f))==v for f,v in before.items())
    p.save(OUT/'verification.json',{'passed':True,'snapshot_files_verified':len(manifest),
        'all_four_2025_results_match_existing':True,'models_and_sources_unchanged':True,'runs':len(rows)})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
