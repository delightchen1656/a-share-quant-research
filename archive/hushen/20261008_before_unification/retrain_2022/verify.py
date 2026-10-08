import pipeline as p
import ast,subprocess,sys
import pandas as pd
import numpy as np
import pyarrow.parquet as pq

def main():
    f=p.read('frozen.json');checks={}
    checks['protocol_hash']=p.sha(p.HERE/'protocol.json')==f['protocol_sha256']
    entry=p.HERE/'supermind_mainboard_baseline_1_retrained_2022.py'
    checks['export_hash']=p.sha(entry)==f['export_sha256']
    checks['pipeline_hash']=p.sha(p.HERE/'pipeline.py')==f['pipeline_sha256']
    checks['bounded_manifest_hashes']=all(p.sha(p.HERE/(stage+'_manifest.json'))==f[stage.replace('_snapshot','')+'_manifest_sha256'] for stage in ['training_snapshot','selection_snapshot'])
    for stage,end in [('training_snapshot','2023-01-01'),('selection_snapshot','2024-01-01'),('confirmation_snapshot','2024-11-30')]:
        manifest=p.read(stage+'_manifest.json');ok=True
        for item in manifest['files']:
            path=p.HERE/stage/(item['symbol']+'.parquet')
            assert p.sha(path)==item['sha256']
            dates=pq.read_table(path,columns=['date']).to_pandas().date
            assert dates.max()<pd.Timestamp(end)
        checks[stage+'_physically_bounded']=ok
    train=pd.read_parquet(p.HERE/'training_snapshot_samples.parquet')
    train=train[(train.signal_date>='2019-01-01')&(train.label_end<'2023-01-01')]
    valid=pd.read_parquet(p.HERE/'selection_snapshot_samples.parquet')
    valid=valid[(valid.signal_date>='2023-01-01')&(valid.label_end<'2024-01-01')]
    checks['labels_not_crossing']=train.label_end.lt('2023-01-01').all() and valid.label_end.lt('2024-01-01').all()
    trials=p.read('training_results.json');short=p.read('shortlist.json');sel=p.read('selection_results.json')
    checks['bounded_search']=len(trials)==9 and len(short)==3 and len(sel)==3 and set(t['id'] for t in sel)==set(short)
    checks['shortlist_training_only']=short==[t['id'] for t in trials[:3]]
    for t in trials:assert np.isclose(p.metric(train,t['weights'])['mean_ic'],t['training']['mean_ic'])
    for t in sel:assert np.isclose(p.metric(valid,t['weights'])['mean_ic'],t['selection']['mean_ic'])
    checks['metrics_recomputed']=True
    checks['winner_2023_only']=sel[0]['id']==f['winner']['id'] and sel[0]['selection']['mean_ic']==max(t['selection']['mean_ic'] for t in sel)
    source=p.PARENT/'supermind_mainboard_baseline_1_cutoff_20241130.py'
    def funcs(path):return {n.name:ast.dump(n) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
    a,b=funcs(source),funcs(entry)
    checks['execution_unchanged']=all(a[k]==b[k] for k in ['handle_bar','select_affordable','stock_features','rank_candidates','trade_state','rebalance_due'])
    result=subprocess.run([sys.executable,str(p.HERE/'pipeline.py'),'train'],capture_output=True,text=True)
    checks['frozen_refuses_retrain']=result.returncode!=0 and 'Already frozen' in result.stderr
    if (p.HERE/'evaluation.json').exists():
        ev=p.read('evaluation.json');checks['evaluation_frozen_hash']=ev['frozen_sha256']==p.sha(p.HERE/'frozen.json')
        checks['corporate_actions_resolved']=all(r['unresolved_actions']==0 for r in ev['periods'])
        q=pd.read_parquet(p.HERE/'daily_equity.parquet');checks['cash_no_borrowing']=q.cash.ge(-.01).all()
        checks['independent_cash_accounts']=all(r['initial_cash']==100000 for r in ev['periods'])
        checks['nonempty_execution']=all(r['trades']>0 and r['average_exposure']>0 for r in ev['periods'])
    checks={k:bool(v) for k,v in checks.items()};p.dump('validation.json',checks);assert all(checks.values()),checks
    print('PASS',len(checks),flush=True)
if __name__=='__main__':main()
