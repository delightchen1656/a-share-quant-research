"""Exactly 1000 pre-registered combinations; cached identical execution engine."""
from pathlib import Path
import sys
import itertools
import inspect
import contextlib
import time
HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
sys.path.insert(0,str(PARENT))
import pipeline as p
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import HistGradientBoostingClassifier as HGB

OUT=HERE/'results'
EVENTS=[
    (5,100,10,120,.04),(3,100,10,120,.04),(5,250,20,180,.04),
    (7,100,10,120,.04),(7,250,20,180,.04),(15,100,10,120,.04),
    (15,250,20,180,.04),(5,100,10,240,.02),(7,100,10,240,.02),(7,500,40,120,.04)]
STOPS=[(7,20,3,180,.04,'balanced'),(7,100,10,120,.04,None),(3,250,20,120,.04,None),
       (7,100,10,120,.04,'balanced'),(15,100,10,120,.04,None)]
PT=[.50,.55,.60,.65,.70]
ST=[.30,.35,.40,.45]

def protocol():
    return {'fit':['2020-01-01','2022-12-31'],'select':['2023-01-01','2023-12-31'],
        'confirm':['2024-01-01','2024-12-31'],'evaluate':['2025-01-01',p.END],
        'event_configs':EVENTS,'stop_configs':STOPS,'config_fields':['leaves','min_leaf','l2','iterations','learning_rate','stop_class_weight'],
        'event_thresholds':PT,'stop_thresholds':ST,'count':1000,'early_stopping':False,
        'objective':'2023 CAGR - .5*abs(maxDD) + .25*worst quarterly return',
        'eligibility':'fills>=40 and average exposure>=15%; no near-empty winners',
        'tie_break':['Sharpe descending','CAGR descending','candidate_id ascending'],
        'development_gate':'positive 2023 total return and >=2 positive quarters',
        'selection_after_confirm':False,'capital':1000000,'rules':'all 3-2 execution and fee assumptions unchanged',
        'source_hashes':{str(f):p.sha(f) for f in [p.SOURCE,p.BASE/'start_date_study.py',PARENT/'pipeline.py',
            PARENT/'tuning_v1/supermind_baseline_3_2_tuned_daily.py',PARENT/'tuning_v2/supermind_baseline_3_2_tuning_v2_daily.py']},
        'snapshots':{date:p.sha(PARENT/'snapshots'/date/'manifest.json') for date in ['2022-12-31','2023-12-31']}}

def all_configs():
    return [{'id':i+1,'event_id':e,'stop_id':s,'p_threshold':pt,'s_threshold':st}
            for i,(e,s,pt,st) in enumerate(itertools.product(range(10),range(5),PT,ST))]

def load_models(tr):
    directory=HERE/'models';directory.mkdir(exist_ok=True)
    fitted=[];boundary=[]
    for kind,configs,target in [('event',EVENTS,'label'),('stop',STOPS,'stop_label')]:
        x=p.labeled(tr,target,'2020-01-01','2022-12-31');endcol='event_end' if kind=='event' else 'stop_end'
        assert x[endcol].max()<=pd.Timestamp('2022-12-31')
        ms=[]
        for i,cfg in enumerate(configs):
            leaves,minleaf,l2,iterations,lr=cfg[:5];weight='balanced' if kind=='event' else cfg[5]
            path=directory/(kind+'_'+str(i)+'.joblib')
            if path.exists():m=joblib.load(path)
            else:
                m=HGB(max_iter=iterations,learning_rate=lr,max_leaf_nodes=leaves,min_samples_leaf=minleaf,
                    l2_regularization=l2,class_weight=weight,early_stopping=False,random_state=42 if kind=='event' else 73)
                m.fit(x[p.F],x[target].astype(int));joblib.dump(m,path)
            ms.append(m);boundary.append({'kind':kind,'id':i,'rows':len(x),'max_anchor':str(x.date.max()),
                'max_label_end':str(x[endcol].max()),'sha256':p.sha(path)})
            print('MODEL',kind,i,'ready',flush=True)
        fitted.append(ms)
    p.save(OUT/'training_boundaries.json',boundary)
    return fitted

def candidates(scores,pt,st):
    eligible=scores[(scores.p>=pt)&(scores.stop<=st)].sort_values(['date','score','symbol'],ascending=[True,False,True])
    return {d:list(g.head(8).symbol) for d,g in eligible.groupby('date')}

def prepare_actions(panels,symbols,start,end):
    requests=set()
    for s in symbols:
        f=panels[s];ev=f[(abs(f.adjust_ratio-1)>1e-5)&(f.index>=start)&(f.index<=end)]
        requests.update((s,int(d.year)) for d in ev.index)
    ns=dict(p.replay.__dict__);ns['OUT']=OUT
    exec(inspect.getsource(p.replay.actions),ns)
    return ns['actions'](requests)

def executor(panels,meta,start,end,actions):
    cal=pd.read_csv(p.DATA/'metadata/trade_calendar_20261004.csv')
    dates=pd.DatetimeIndex(pd.to_datetime(cal.loc[cal.is_trading_day.eq(1),'calendar_date']))
    dates=dates[(dates>=pd.Timestamp(start)-pd.Timedelta(days=12))&(dates<=end)]
    days={d:{} for d in dates}
    for symbol,f in panels.items():
        for row in f.loc[dates[0]:end].itertuples():
            if row.Index in days:days[row.Index][symbol]=row
    ns=p.namespace(p.SOURCE.read_text(encoding='utf-8'));ns['g'].model={'max_positions':14,'top_per_day':8}
    src=inspect.getsource(p.replay.run_starts)
    begin=src.index('    days={d:{} for d in dates}')
    finish=src.index('    all_curves,results,all_trades=')
    src=src[:begin]+"    days=prepared_days\n    starts=dates[dates>=pd.Timestamp('"+start+"')][:1]\n"+src[finish:]
    src=src[:src.index('    out=pd.DataFrame(results)')]+"    return results[0],all_curves[0],pd.DataFrame(all_trades),reference_differences\n"
    env=dict(p.replay.__dict__);env.update(OUT=OUT,END=pd.Timestamp(end),prepared_days=days,print=lambda *a,**kw:None)
    exec(src,env)
    def run(signal_candidates):
        with np.errstate(invalid='ignore'):
            r,curve,trades,diffs=env['run_starts']((ns,[{'max_positions':14,'top_per_day':8}],dates,panels,signal_candidates,meta,set()),actions)
        ret=curve.set_index('date').equity.pct_change();ret.iloc[0]=curve.equity.iloc[0]/1e6-1
        quarter=(1+ret).groupby(ret.index.to_period('Q')).prod()-1
        r.update(worst_quarter=float(quarter.min()),positive_quarters=int((quarter>0).sum()),
            objective=float(r['cagr']-.5*abs(r['max_drawdown'])+.25*quarter.min()))
        return r,curve,trades,diffs
    return run

def save_run(name,result):
    r,curve,trades,diffs=result;directory=OUT/name;directory.mkdir(exist_ok=True)
    p.save(directory/'metrics.json',r);curve.to_parquet(directory/'daily_equity.parquet',index=False)
    trades.to_parquet(directory/'trades.parquet',index=False);p.save(directory/'reference_price_differences.json',diffs)
    p.save(directory/'unresolved_actions.json',[])

def slow_parity(scores,panels,meta,config,fast_result):
    with (OUT/'reference_engine.log').open('a',encoding='utf-8') as log,contextlib.redirect_stdout(log):
        r=p.replay_stage(scores,panels,meta,'2023-01-01','2023-12-31',config['p_threshold'],config['s_threshold'],'parity_'+str(config['id']))
    for field in ['final_asset','total_return','cagr','max_drawdown','sharpe_rf0','avg_exposure','fills']:
        assert np.isclose(r[field],fast_result[0][field],rtol=1e-10,atol=1e-8,equal_nan=True),(field,r[field],fast_result[0][field])
    ref=pd.read_parquet(OUT/('parity_'+str(config['id']))/'trades.parquet')
    pd.testing.assert_frame_equal(ref.reset_index(drop=True),fast_result[2].reset_index(drop=True))

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    pr=protocol();file=HERE/'protocol.json'
    if file.exists():assert p.json.loads(file.read_text())==p.json.loads(p.json.dumps(pr)),'Protocol/input changed; cannot resume.'
    else:p.save(file,pr);p.save(HERE/'candidates.json',all_configs())
    p.OUT=OUT;p.HERE=HERE;p.PLATFORM=HERE/'supermind_baseline_3_2_search1000_daily.py'
    if not (OUT/'corporate_actions.json').exists():
        p.save(OUT/'corporate_actions.json',p.json.loads((PARENT/'tuning_v2/results/corporate_actions.json').read_text(encoding='utf-8')))
    if not (OUT/'frozen.json').exists():
        tr,_,_=p.dataset(PARENT/'snapshots/2022-12-31','2020-01-01','2022-12-31')
        va,panels,meta=p.dataset(PARENT/'snapshots/2023-12-31','2023-01-01','2023-12-31')
        ev,st=load_models(tr)
        ep=[m.predict_proba(va[p.F])[:,1] for m in ev];sp=[m.predict_proba(va[p.F])[:,1] for m in st]
        possible=va.loc[(np.max(ep,axis=0)>=min(PT))&(np.min(sp,axis=0)<=max(ST)),'symbol'].unique()
        action_map=prepare_actions(panels,possible,'2023-01-01','2023-12-31')
        execute=executor(panels,meta,'2023-01-01','2023-12-31',action_map)
        checkpoint=OUT/'checkpoint.json';rows=p.json.loads(checkpoint.read_text()) if checkpoint.exists() else []
        done={r['id'] for r in rows};started=time.monotonic();initial=len(done);last_pair=None
        for cfg in all_configs():
            if cfg['id'] in done:continue
            pair=(cfg['event_id'],cfg['stop_id'])
            if pair!=last_pair:
                scores=va[['date','symbol']].copy();scores['p']=ep[pair[0]];scores['stop']=sp[pair[1]]
                scores['score']=scores.p-.22*scores.stop;last_pair=pair
            run=execute(candidates(scores,cfg['p_threshold'],cfg['s_threshold']))
            if cfg['id'] in [1,114,1000]:slow_parity(scores,panels,meta,cfg,run)
            rows.append(dict(run[0],**cfg))
            if len(rows)%25==0:
                p.save(checkpoint,rows)
                elapsed=time.monotonic()-started
                p.save(OUT/'progress.json',{'completed':len(rows),'total':1000,'elapsed_seconds':elapsed,
                    'estimated_remaining_seconds':(1000-len(rows))*elapsed/max(1,len(rows)-initial)})
                print('SEARCH',len(rows),'/ 1000',flush=True)
        assert len(rows)==1000 and len({r['id'] for r in rows})==1000
        table=pd.DataFrame(rows);table.to_csv(OUT/'all_1000_results.csv',index=False,encoding='utf-8-sig')
        valid=table[(table.fills>=40)&(table.avg_exposure>=.15)].sort_values(['objective','sharpe_rf0','cagr','id'],ascending=[False,False,False,True])
        assert len(valid)>0
        valid.head(20).to_csv(OUT/'top20_2023.csv',index=False,encoding='utf-8-sig')
        best=valid.iloc[0].to_dict();selected=[ev[int(best['event_id'])],st[int(best['stop_id'])]]
        chosen_scores=p.signals(va,selected)
        save_run('winner_2023',execute(candidates(chosen_scores,best['p_threshold'],best['s_threshold'])))
        p.export(selected,best['p_threshold'],best['s_threshold'],va.sample(5000,random_state=42))
        text=p.PLATFORM.read_text(encoding='utf-8').replace('科创3-2：2022截止重训测试版','科创3-2：千组参数冻结候选')
        p.PLATFORM.write_text(text,encoding='utf-8')
        lock={'best':best,'eligible_count':len(valid),'gate_passed':bool(best['total_return']>0 and best['positive_quarters']>=2),
            'platform_sha256':p.sha(p.PLATFORM),'event_sha256':p.sha(HERE/'event_model.joblib'),'stop_sha256':p.sha(HERE/'stop_model.joblib'),
            'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'selection_max_date':'2023-12-31'}
        p.save(OUT/'frozen.json',lock);print('FROZEN',lock,flush=True)
    # Resume after freeze only evaluates the same winner; it never reselects.
    lock=p.json.loads((OUT/'frozen.json').read_text());best=lock['best']
    selected=[joblib.load(HERE/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    control=[joblib.load(PARENT/'tuning_v2'/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    comparisons=[]
    for stage,start,end in [('2020_2022','2020-01-01','2022-12-31'),('2023','2023-01-01','2023-12-31'),
                            ('2024','2024-01-01','2024-12-31'),('2025_2026','2025-01-01',p.END)]:
        ds,panels,meta=p.dataset(PARENT/'snapshots'/end,start,end)
        pairs=[('v2',control,.65,.45),('winner',selected,best['p_threshold'],best['s_threshold'])]
        scored=[p.signals(ds,ms) for _,ms,_,_ in pairs]
        signals=[candidates(s,pt,st) for s,(_,_,pt,st) in zip(scored,pairs)]
        symbols={s for c in signals for vals in c.values() for s in vals}
        action_map=prepare_actions(panels,symbols,start,end);execute=executor(panels,meta,start,end,action_map)
        for (kind,_,_,_),cand in zip(pairs,signals):
            run=execute(cand);save_run(stage+'_'+kind,run)
            comparisons.append(dict(run[0],stage=stage,version=kind))
            print('EVALUATION',stage,kind,'CAGR',round(run[0]['cagr'],4),'DD',round(run[0]['max_drawdown'],4),flush=True)
        assert p.sha(p.PLATFORM)==lock['platform_sha256'] and p.sha(HERE/'event_model.joblib')==lock['event_sha256'] and p.sha(HERE/'stop_model.joblib')==lock['stop_sha256']
    pd.DataFrame(comparisons).to_csv(OUT/'comparison.csv',index=False,encoding='utf-8-sig')
    assert all(p.sha(Path(f))==digest for f,digest in pr['source_hashes'].items())
    p.save(OUT/'completion.json',{'completed':True,'searched':1000,'originals_unchanged':True,'frozen_winner_only_evaluated':True})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
