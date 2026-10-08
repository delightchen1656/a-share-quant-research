"""Fixed 2022-fit models, bounded exit-rule selection on 2023 only."""
from pathlib import Path
import sys,inspect,itertools,ast
HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
OLD=ROOT/'search_1000'
sys.path.insert(0,str(OLD))
import search as s
p=s.p;pd=s.pd;np=s.np
OUT=HERE/'results'
CONTROL={'stop':.07,'half':.24,'full':.34,'soft_days':30,'hard_days':60}

def exit_source(rule):
    return '''def _exit_action(price, state, amount, today, position_days):
    entry=state['entry']
    if entry<=0 or not np.isfinite(price):return None
    start=state['entry_date']
    age=(today-start).days if start is not None else int(position_days)
    gain=price/entry-1
    if gain<=-%(stop)r:return 'STOP',0
    if gain>=%(full)r:return 'TPALL',0
    if age>=%(hard_days)r:return 'TIME60',0
    if age>=%(soft_days)r and gain<.10:return 'TIME30',0
    target=int(amount/2)
    if gain>=%(half)r and not state['half'] and target>=200 and int(amount)-target>=200:return 'TPHALF',target
    return None
''' % rule

def exit_function(rule):
    ns={'np':np};exec(exit_source(rule),ns);return ns['_exit_action']

def configs():
    return [dict(id=i+1,stop=a,half=b,full=c,soft_days=d,hard_days=e)
        for i,(a,b,c,(d,e)) in enumerate(itertools.product([.05,.07,.09],[.18,.24,.30],[.34,.45,.60],[(20,40),(30,60),(40,80)]))]

def make_engine(panels,meta,start,end,actions):
    env=dict(s.__dict__);env['rule_state']={'exit':exit_function(CONTROL)}
    source=inspect.getsource(s.executor)
    needle="ns['g'].model={'max_positions':14,'top_per_day':8}"
    assert needle in source
    source=source.replace(needle,needle+"\n    ns['_exit_action']=lambda *args:rule_state['exit'](*args)")
    exec(source,env)
    return env['executor'](panels,meta,start,end,actions),env['rule_state']

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    if (OUT/'frozen.json').exists():raise RuntimeError('Frozen: no re-selection.')
    files=[OLD/'event_model.joblib',OLD/'stop_model.joblib',OLD/'supermind_baseline_3_2_search1000_daily.py',p.SOURCE]
    protocol={'fit':'unchanged champion891 models, fitted 2020-2022 only','selection':'2023 only',
        'count':81,'rules':configs(),'buy_thresholds':[.60,.40],'capital':1000000,
        'objective':'CAGR - .5*abs(maxDD) + .25*worst quarterly return',
        'eligibility':'fills>=40 and average exposure>=15%',
        'no_future_reselection':True,'source_hashes':{str(f):p.sha(f) for f in files}}
    p.save(HERE/'protocol.json',protocol)
    models=[p.joblib.load(OLD/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    p.OUT=OUT;p.HERE=HERE;p.PLATFORM=HERE/'supermind_baseline_3_2_exit_optimized_daily.py';s.OUT=OUT
    p.save(OUT/'corporate_actions.json',p.json.loads((OLD/'results/corporate_actions.json').read_text(encoding='utf-8')))
    ds,panels,meta=p.dataset(ROOT/'snapshots/2023-12-31','2023-01-01','2023-12-31')
    scored=p.signals(ds,models);cand=s.candidates(scored,.60,.40)
    symbols={x for values in cand.values() for x in values}
    actions=s.prepare_actions(panels,symbols,'2023-01-01','2023-12-31')
    execute,state=make_engine(panels,meta,'2023-01-01','2023-12-31',actions)
    reference=s.executor(panels,meta,'2023-01-01','2023-12-31',actions)(cand)
    match=execute(cand)
    pd.testing.assert_frame_equal(reference[2],match[2]);assert reference[0]==match[0]
    rows=[]
    for rule in configs():
        state['exit']=exit_function(rule);run=execute(cand)
        rows.append(dict(run[0],**rule))
        if rule['id']%9==0:print('EXIT SEARCH',rule['id'],'/81',flush=True)
    results=pd.DataFrame(rows);results.to_csv(OUT/'all_81_results.csv',index=False,encoding='utf-8-sig')
    valid=results[(results.fills>=40)&(results.avg_exposure>=.15)].sort_values(['objective','sharpe_rf0','id'],ascending=[False,False,True])
    best=valid.iloc[0].to_dict();rule={k:int(best[k]) if k.endswith('days') else float(best[k]) for k in CONTROL}
    state['exit']=exit_function(rule);s.save_run('winner_2023',execute(cand))
    p.export(models,.60,.40,ds.sample(min(5000,len(ds)),random_state=42))
    tree=ast.parse(p.PLATFORM.read_text(encoding='utf-8'))
    for i,node in enumerate(tree.body):
        if isinstance(node,ast.FunctionDef) and node.name=='_exit_action':tree.body[i]=ast.parse(exit_source(rule)).body[0]
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id=='STRATEGY_VERSION':node.value=ast.Constant(value='科创3-2：冻结模型退出优化V1')
    text=ast.unparse(ast.fix_missing_locations(tree));compile(text,str(p.PLATFORM),'exec');p.PLATFORM.write_text(text+'\n',encoding='utf-8')
    lock={'best':best,'rule':rule,'platform_sha256':p.sha(p.PLATFORM),'event_sha256':p.sha(HERE/'event_model.joblib'),
        'stop_sha256':p.sha(HERE/'stop_model.joblib'),'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'max_selection_date':'2023-12-31'}
    p.save(OUT/'frozen.json',lock);print('FROZEN',lock,flush=True)
    compare=[]
    for stage,start,end in [('2020_2022','2020-01-01','2022-12-31'),('2023','2023-01-01','2023-12-31'),('2024','2024-01-01','2024-12-31'),('2025_2026','2025-01-01',p.END)]:
        ds,panels,meta=p.dataset(ROOT/'snapshots'/end,start,end)
        scored=p.signals(ds,models);cand=s.candidates(scored,.60,.40);symbols={x for v in cand.values() for x in v}
        actions=s.prepare_actions(panels,symbols,start,end);execute,state=make_engine(panels,meta,start,end,actions)
        for name,cfg in [('champion891',CONTROL),('exit_v1',rule)]:
            state['exit']=exit_function(cfg);run=execute(cand);s.save_run(stage+'_'+name,run)
            compare.append(dict(run[0],stage=stage,version=name))
            print('EVALUATION',stage,name,'CAGR',round(run[0]['cagr'],4),'DD',round(run[0]['max_drawdown'],4),flush=True)
        assert p.sha(p.PLATFORM)==lock['platform_sha256']
    pd.DataFrame(compare).to_csv(OUT/'comparison.csv',index=False,encoding='utf-8-sig')
    assert all(p.sha(Path(f))==h for f,h in protocol['source_hashes'].items())
    p.save(OUT/'completion.json',{'completed':True,'models_retrained':False,'searched':81,'control_engine_parity':True,'originals_unchanged':True})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
