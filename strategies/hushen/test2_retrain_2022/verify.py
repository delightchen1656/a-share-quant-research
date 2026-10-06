import pipeline as p
import ast,subprocess,sys
import pandas as pd
import numpy as np
import pyarrow.parquet as pq

def main():
    f=p.read('frozen.json');checks={}
    entry=p.HERE/'supermind_test2_D11_fast_retrained_2022.py'
    checks['frozen_hashes']=all(p.sha(p.HERE/name)==f[key] for name,key in [('protocol.json','protocol_sha256'),('pipeline.py','pipeline_sha256'),(entry.name,'export_sha256'),('training_inputs.json','training_inputs_sha256'),('selection_inputs.json','selection_inputs_sha256')])
    checks['feature_source_hash']=p.sha(p.PARENT/'test2_cutoff_20241130/train.py')==f['feature_source_sha256']
    for stage,end in [('training','2023-01-01'),('selection','2024-01-01'),('confirmation','2024-11-30')]:
        record=p.read(stage+'_inputs.json');base=p.PARENT/'retrain_2022'/(stage+'_snapshot')
        for item in record['files']:
            path=base/(item['symbol']+'.parquet');assert p.sha(path)==item['sha256']
            dates=pq.read_table(path,columns=['date']).to_pandas().date;assert dates.max()<pd.Timestamp(end)
        checks[stage+'_physical_cutoff']=True
    trials=p.read('training_results.json');selected=p.read('selection_results.json');short=p.read('shortlist.json')
    checks['nine_candidates_three_finalists']=len(trials)==9 and len(selected)==3 and short==[t['id'] for t in trials[:3]] and set(short)==set(t['id'] for t in selected)
    checks['training_sort']=trials==sorted(trials,key=lambda t:(-t['training']['mean_ic'],t['distance'],t['id']))
    checks['selection_sort']=selected==sorted(selected,key=lambda t:(-t['selection']['mean_ic'],-t['training']['mean_ic'],t['distance'],t['id'])) and selected[0]==f['winner']
    for stage,records,start,end in [('training',[t['training'] for t in trials],'2019-01-01','2023-01-01'),('selection',[t['selection'] for t in selected],'2023-01-01','2024-01-01'),('confirmation',[p.read('confirmation.json')],'2024-01-01','2024-11-30')]:
        for r in records:
            assert np.isclose(r['mean_ic'],np.mean([row['ic'] for row in r['periods']]))
            for row in r['periods']:assert start<=row['signal_date']<row['label_end']<end
        checks[stage+'_labels_and_aggregation']=True
    def funcs(path):return {n.name:ast.dump(n) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
    checks['all_platform_functions_unchanged']=funcs(entry)==funcs(p.PARENT/'supermind_test2_D11_fast_cutoff_20241130.py')
    r=subprocess.run([sys.executable,str(p.HERE/'pipeline.py'),'train'],capture_output=True,text=True)
    checks['frozen_refuses_retrain']=r.returncode!=0 and 'Already frozen' in r.stderr
    # Full-universe first evaluation date, exported original function vs vectorized rankings.
    engine=p.mod(p.PARENT/'start_date_study/study.py','mock');model=engine.module(entry,'export_check')
    raw={};base=p.PARENT/'retrain_2022/training_snapshot';dates=pd.DatetimeIndex(pd.read_parquet(base/'benchmark.parquet').date)[-5:]
    for path in sorted(base.glob('*.parquet')):
        if path.stem=='benchmark':continue
        x=pd.read_parquet(path).set_index('date').tail(320).rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
        x['is_paused']=1-pd.to_numeric(x.tradestatus);raw[path.stem]=x
    ranks,_=model.compute_signals(raw,{str(d.date()):set(raw) for d in dates},dates)
    checks['full_universe_export_parity']=ranks==p.read('evaluation_rankings.json')[str(dates[-1].date())]
    checks['exported_weights']=list(f['winner']['weights'])==[model.CAP_WEIGHT,model.VOL_WEIGHT,model.OVERNIGHT_WEIGHT,model.INTRADAY_WEIGHT]
    e=p.read('evaluation.json');q=pd.read_parquet(p.HERE/'daily_equity.parquet')
    checks['evaluation_after_freeze']=e['frozen_sha256']==p.sha(p.HERE/'frozen.json')
    checks['cash_and_fills']=q.cash.ge(-.01).all() and all(r['trades']>0 and r['initial_cash']==100000 for r in e['periods'])
    checks['held_corporate_actions_resolved']=all(r['unresolved_actions']==0 for r in e['periods'])
    checks={k:bool(v) for k,v in checks.items()};p.dump('validation.json',checks);assert all(checks.values()),checks
    print('PASS',len(checks),flush=True)
if __name__=='__main__':main()
