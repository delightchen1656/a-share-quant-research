"""Independent checks of frozen experiment boundaries and reported ledgers."""
import pipeline as p
from pathlib import Path
import json, sys, ast
import pandas as pd
import numpy as np

def feature_parity():
    folder=p.BASE/'retrain_2022/training_snapshot'
    dates=pd.DatetimeIndex(pd.read_parquet(folder/'benchmark.parquet').date)
    signal=dates[dates.get_loc(dates[dates>='2019-01-01'][0])-1]
    raw={}
    for path in sorted(folder.glob('*.parquet')):
        if path.stem=='benchmark':continue
        x=pd.read_parquet(path);x.date=pd.to_datetime(x.date);x=x[x.date<=signal].set_index('date').tail(320)
        if x.empty:continue
        x=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
        x['is_paused']=1-pd.to_numeric(x.tradestatus)
        raw[path.stem]=x
    trials=[dict(id='baseline',config=p.Q['base'])]
    for tid in ['smooth_20','weights_20','windows_20','filters_20']:
        trials += [t for t in p.Q['trials'] if t['id']==tid]
    engine=p.engine_module();checks={}
    for t in trials:
        c=t['config'];m=engine.module(p.ENTRY,'parity_export')
        code=p.ENTRY.read_text(encoding='utf-8')
        code=code.replace('vol = r.rolling(60).std()',f"vol = r.rolling({c['vol_window']}).std()")
        code=code.replace('.fillna(0).rolling(20).sum()',f".fillna(0).rolling({c['return_window']}).sum()")
        code=code.replace('(amount >= 1e7)',f"(amount >= {c['amount_min']})").replace('(vol < .09)',f"(vol < {c['vol_max']})")
        a,b,o,i=c['weights']
        code=code.replace("-.35 * ranked['cap'] - .20 * ranked['vol'] +\n             .25 * ranked['overnight'] - .20 * ranked['intraday']",f"-{a} * ranked['cap'] - {b} * ranked['vol'] +\n             {o} * ranked['overnight'] - {i} * ranked['intraday']")
        exec(compile(code,'parity_export','exec'),m.__dict__);m.SMOOTH=c['smooth'];m.MIN_SMOOTH=c['min_smooth']
        sd=dates[dates<=signal][-c['smooth']:]
        rankings,_=m.compute_signals(raw,{str(d.date()):set(raw) for d in sd},sd)
        keys=['smooth','min_smooth','weights','vol_window','return_window','amount_min','vol_max']
        sig=p.signature({k:c[k] for k in keys});path=p.HERE/'training'/('signals_'+sig+'.json')
        if not path.exists():raise RuntimeError('Run training first: '+str(path))
        actual=p.read(path)[str(signal.date())]
        checks[t['id']]=rankings==actual
        if not checks[t['id']]:print('MISMATCH',t['id'],rankings[:10],actual[:10],flush=True)
    p.dump(p.HERE/'feature_parity.json',checks);assert all(checks.values()),checks
    print('FEATURE PARITY',len(checks),flush=True)

def control():
    stage=p.Stage('training')
    try:
        stage.folder=p.HERE/'control_2020';stage.folder.mkdir(exist_ok=True)
        stage.sessions=stage.dates[stage.dates>='2020-01-01']
        r=stage.simulate(p.Q['base'],'original2020')
        actual=pd.read_parquet(stage.folder/'runs'/(p.signature(p.Q['base'])+'_equity.parquet'))
        expected=pd.read_parquet(p.BASE/'test2_weekly/original_202001/daily_equity.parquet')
        expected=expected[expected.date<=stage.end]
        checks=dict(same_dates=actual.date.tolist()==expected.date.tolist(),
            same_daily_equity=bool(np.allclose(actual.equity.to_numpy(),expected.equity.to_numpy(),rtol=0,atol=1e-8)))
        p.dump(p.HERE/'control_parity.json',checks);assert all(checks.values()),checks
        print('CONTROL PARITY',checks)
    finally:stage.close()

def verify():
    f=p.read(p.HERE/'frozen.json');checks={}
    checks['frozen_sources']=all(p.sha(path)==f[key] for path,key in [(p.HERE/'pipeline.py','pipeline_sha256'),(p.ENTRY,'source_sha256'),(p.BASE/'start_date_study/study.py','engine_sha256'),(p.HERE/'protocol.json','protocol_sha256')])
    checks['frozen_results']=all(p.sha(p.HERE/(name+'.json'))==f[name+'_sha256'] for name in ['group_training','group_selection','combined_training','combined_selection'])
    checks['160_trials_8_groups']=len(p.Q['trials'])==160 and all(sum(t['group']==g for t in p.Q['trials'])==20 for g in p.Q['groups'])
    checks['controlled_variables']=all(all(t['config'][k]==p.Q['base'][k] for k in p.Q['base'] if k not in p.Q['group_keys'][t['group']]) for t in p.Q['trials'])
    checks['feature_parity']=all(p.read(p.HERE/'feature_parity.json').values())
    checks['original_control_parity']=all(p.read(p.HERE/'control_parity.json').values())
    groups=p.read(p.HERE/'group_selection.json')['winners'];combinations=p.read(p.HERE/'combined_candidates.json')
    rebuilt=[]
    for subset in p.Q['combined_subsets']:
        c=dict(p.Q['base'])
        for g in subset:
            for k in p.Q['group_keys'][g]:c[k]=groups[g]['config'][k]
        rebuilt.append(c)
    checks['combined_preregistered']=len(combinations)==20 and [t['config'] for t in combinations]==rebuilt
    for stage,end in [('training','2022-12-31'),('selection','2023-12-31'),('confirmation','2024-11-29'),('heldout','2026-09-30')]:
        manifest=p.read(p.HERE/stage/'inputs.json');checks[stage+'_input_boundary']=manifest['max_date']<=end and all(r['max_date']<=end for r in manifest['files'])
    for name,stage in [('group_training','training'),('combined_training','training')]:
        data=p.read(p.HERE/(name+'.json'))
        expected={}
        for g in data['shortlist']:
            rows=[r for r in data['results'] if r['group']==g and p.valid(r,data['baseline'],stage)]
            expected[g]=[r['id'] for r in sorted(rows,key=p.rankkey)[:3]]
        checks[name+'_shortlist']=data['shortlist']==expected
    for name in ['group_selection','combined_selection']:
        data=p.read(p.HERE/(name+'.json'))
        checks[name+'_winner']=all(w==sorted([r for r in data['results'] if r['group']==g and p.valid(r,data['baseline'],'selection')]+[dict(data['baseline'],group=g)],key=p.rankkey)[0] or
            w['config']==sorted([r for r in data['results'] if r['group']==g and p.valid(r,data['baseline'],'selection')]+[data['baseline']],key=p.rankkey)[0]['config'] for g,w in data['winners'].items())
    errors=[];n=0
    for stage in p.Q['periods']:
        for path in (p.HERE/stage/'runs').glob('*.json'):
            if path.name.endswith('_schedule.json'):continue
            r=p.read(path);q=pd.read_parquet(path.with_name(path.stem+'_equity.parquet'));t=pd.read_parquet(path.with_name(path.stem+'_trades.parquet'))
            nav=q.equity.to_numpy();returns=nav/np.r_[100000.,nav[:-1]]-1
            dd=1-nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]
            correct=np.isclose(nav[-1],r['final_equity']) and np.isclose(dd.max(),r['max_drawdown']) and np.isclose(returns.mean()/returns.std(ddof=1)*np.sqrt(252),r['sharpe'])
            correct=correct and q.cash.ge(-.01).all() and len(t)==r['trades'] and (t.loc[t.qty>0,'qty']%100).eq(0).all()
            correct=correct and not q.date.duplicated().any() and q.date.min()>=pd.Timestamp(p.Q['periods'][stage][0]) and q.date.max()<=pd.Timestamp(p.Q['periods'][stage][1])
            correct=correct and np.isclose(t[['commission','transfer','stamp']].to_numpy().sum(),r['fees']) and np.isclose(t.dividend_tax.sum(),r['dividend_tax'])
            if not correct:errors.append(str(path))
            n+=1
    checks['all_saved_metrics_and_lots']=not errors
    checks['evaluation_bound_to_freeze']=all(p.read(p.HERE/s/'evaluation.json')['frozen_sha256']==p.sha(p.HERE/'frozen.json') for s in ['confirmation','heldout'])
    p.dump(p.HERE/'validation.json',dict(checks=checks,unique_account_runs=n,errors=errors))
    assert all(checks.values()),checks
    print('PASS',len(checks),'unique account runs',n)
if __name__=='__main__':
    command=sys.argv[1] if len(sys.argv)>1 else 'all'
    {'features':feature_parity,'control':control,'all':verify}[command]()
