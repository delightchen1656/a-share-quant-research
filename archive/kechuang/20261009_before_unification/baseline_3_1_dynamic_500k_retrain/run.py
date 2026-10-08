"""Independent 500k chronological retrain; frozen development protocol, no refit on holdout."""
from pathlib import Path
import sys, inspect, ast, json, contextlib
HERE=Path(__file__).resolve().parent
BASE=HERE.parent/'baseline_3_2/retrain_2022'
sys.path.insert(0,str(BASE/'search_1000'))
import search as s
p=s.p; pd=s.pd; np=s.np
OUT=HERE/'results'
PLATFORM=HERE/'supermind_3_1_dynamic_500k_retrained_daily.py'
OLD=HERE.parents[2]/'research_versions/kechuang_high_attack/baseline_3_1_daily_120k_dynamic20.py'
# Correct root through the shared pipeline, independent of local directory depth.
OLD=p.ROOT/'research_versions/kechuang_high_attack/baseline_3_1_daily_120k_dynamic20.py'
CAPITAL=500000.

def _target_fraction(price, equity):
    if equity<=0 or price<=0 or not np.isfinite(price):return None
    fraction=max(.10,price*200*1.01/equity)
    return fraction if fraction<=.20 else None

def _exit_action(price, state, amount, today, position_days):
    """Preserve old 3-1 branch precedence, including partial-profit-before-expiry."""
    if state['entry']<=0 or not np.isfinite(price):return None
    gain=price/state['entry']-1
    if price<=state['entry']*.93:return 'STOP',0
    if price>=state['entry']*1.34:return 'TPALL',0
    if price>=state['entry']*1.24 and not state['half']:
        target=int(amount/2)
        if target>=200 and amount-target>=200:return 'TPHALF',target
        return None
    age=(today-state['entry_date']).days if state['entry_date'] is not None else int(position_days)
    if age>=60:return 'TIME60',0
    if age>=30 and gain<.10:return 'TIME30',0
    return None

def engine(panels,meta,start,end,actions):
    env=dict(s.__dict__)
    env.update(size_fn=_target_fraction,exit_fn=_exit_action)
    source=inspect.getsource(s.executor)
    source=source.replace("ns['g'].model={'max_positions':14,'top_per_day':8}","ns['g'].model={'max_positions':14,'top_per_day':8}; ns['_exit_action']=exit_fn")
    source=source.replace("env.update(OUT=OUT,END=pd.Timestamp(end),prepared_days=days,print=lambda *a,**kw:None)","env.update(OUT=OUT,END=pd.Timestamp(end),prepared_days=days,CASH=500000.,size_fn=size_fn,print=lambda *a,**kw:None)")
    before="                desired=int(equity(True)*.10/px)"
    after="                fraction=size_fn(float(r.open),equity(True))\n                if fraction is None or cash<equity(True)*fraction*1.005:continue\n                desired=int(equity(True)*fraction/px)"
    source=source.replace('    exec(src,env)',f'    assert {before!r} in src\n    src=src.replace({before!r},{after!r})\n    exec(src,env)')
    source=source.replace('/1e6-1','/500000.-1')
    exec(source,env)
    return env['executor'](panels,meta,start,end,actions)

def patch_platform():
    text=PLATFORM.read_text(encoding='utf-8')
    tree=ast.parse(text)
    for i,n in enumerate(tree.body):
        if isinstance(n,ast.FunctionDef) and n.name=='_exit_action':tree.body[i]=ast.parse(inspect.getsource(_exit_action)).body[0]
    tree.body.append(ast.parse(inspect.getsource(_target_fraction)).body[0])
    text=ast.unparse(ast.fix_missing_locations(tree))
    needle="order_target_percent(symbol, 0.1)"
    assert needle in text
    text=text.replace(needle,"order_target_percent(symbol, float(target))")
    needle="if _place(symbol, 'BUY', None) is not None:"
    assert needle in text
    text=text.replace(needle,"fraction = _target_fraction(price, float(context.portfolio.stock_account.total_value))\n        if fraction is None or float(context.portfolio.stock_account.available_cash) < float(context.portfolio.stock_account.total_value)*fraction*1.005:\n            continue\n        if _place(symbol, 'BUY', fraction) is not None:")
    text=text.replace('科创3-2：2022截止重训测试版','科创3-1动态仓位：50万元时序重训候选')
    text='# Platform initial capital: 500000 CNY; daily frequency.\n'+text
    compile(text,str(PLATFORM),'exec')
    PLATFORM.write_text(text+'\n',encoding='utf-8')

def dataset(start,end):
    folder=BASE/'snapshots'/end
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(folder/f)==r['sha256'] for f,r in manifest.items())
    return p.dataset(folder,start,end)

def run_stage(models,start,end,pt,st,label):
    ds,panels,meta=dataset(start,end)
    cand=s.candidates(p.signals(ds,models),pt,st)
    actions=s.prepare_actions(panels,{x for v in cand.values() for x in v},start,end)
    result=engine(panels,meta,start,end,actions)(cand)
    s.save_run(label,result)
    return dict(result[0],stage=label)

def verify(lock):
    ns=p.namespace(PLATFORM.read_text(encoding='utf-8'))
    assert ns['_target_fraction'](100,500000)==.10
    assert ns['_target_fraction'](300,500000)==300*202/500000
    assert ns['_target_fraction'](500,500000) is None
    assert ns['_target_fraction'](100,0) is None
    from datetime import date, timedelta
    today=date(2023,6,30)
    tested=0
    for gain in [-.2,-.07,0,.1,.24,.3,.34,.5]:
        for age in [1,29,30,59,60,80]:
            for amount in [200,399,400,1000]:
                for half in [False,True]:
                    state={'entry':100.,'entry_date':today-timedelta(days=age),'half':half}
                    assert ns['_exit_action'](100*(1+gain),state,amount,today,age)==_exit_action(100*(1+gain),state,amount,today,age)
                    tested+=1
    assert p.sha(PLATFORM)==lock['platform_sha256']
    for f,h in lock['model_hashes'].items():assert p.sha(HERE/f)==h
    return {'passed':True,'exit_local_platform_cases':tested,'sizing_boundary_cases':4,
            'frozen_hashes_unchanged':True,'platform_server_tested':False}

def main():
    OUT.mkdir(exist_ok=True)
    p.OUT=OUT;s.OUT=OUT;p.HERE=HERE;p.PLATFORM=PLATFORM
    inputs=[OLD,p.SOURCE,BASE/'pipeline.py',BASE/'search_1000/search.py',p.BASE/'start_date_study.py']
    hashes={str(f):p.sha(f) for f in inputs}
    protocol={'capital':CAPITAL,'fit':['2020-01-01','2022-12-31'],'select':['2023-01-01','2023-12-31'],
        'confirm':['2024-01-01','2024-12-31'],'evaluate':['2025-01-01',p.END],
        'model_candidates_leaves':[7,15,31],'iterations':180,'learning_rate':.04,'l2':3,'class_weight':'balanced',
        'model_selection':'2023 AP, ties fewer leaves','thresholds':{'event':[.50,.63,.75],'stop':[.35,.50,.65]},
        'threshold_selection':'2023 Sharpe descending then CAGR; minimum 20 fills',
        'sizing':'max(10%, open*200*1.01/NAV); skip above20%; require full target cash*1.005',
        'exit':'original 3-1 7/24/34 and30/60; preserve partial-profit-before-expiry precedence',
        'execution_adaptation':'audited dynamic historical universe; previous-close exits at next open, not last_price',
        'cost':'0.2% each-side slippage, commission0.03% min5, sellstamp0.1% throughout; dividend20% deduction',
        'constraints':'T+1, halts, opening limits, daily volume25%, max50000 shares/order, buy>=200',
        'source_hashes':hashes,'no_refit_on_validation':True}
    if not (OUT/'frozen.json').exists():
        if (HERE/'protocol.json').exists():assert json.loads((HERE/'protocol.json').read_text())==protocol
        else:p.save(HERE/'protocol.json',protocol)
        cache={}
        for f in BASE.rglob('corporate_actions.json'):cache.update(json.loads(f.read_text(encoding='utf-8')))
        p.save(OUT/'corporate_actions.json',cache)
        tr,_,_=dataset('2020-01-01','2022-12-31')
        va,panels,meta=dataset('2023-01-01','2023-12-31')
        models=p.train(tr,va)
        scores=p.signals(va,models)
        all_cand=[s.candidates(scores,pt,st) for pt in [.50,.63,.75] for st in [.35,.50,.65]]
        actions=s.prepare_actions(panels,{x for c in all_cand for v in c.values() for x in v},'2023-01-01','2023-12-31')
        execute=engine(panels,meta,'2023-01-01','2023-12-31',actions)
        rows=[]
        for pt in [.50,.63,.75]:
            for st in [.35,.50,.65]:
                result=execute(s.candidates(scores,pt,st));s.save_run(f'select_{pt}_{st}',result)
                row=dict(result[0],p_threshold=pt,s_threshold=st);rows.append(row)
                print('SELECT',pt,st,row['cagr'],flush=True)
        p.save(OUT/'threshold_selection.json',rows)
        valid=[r for r in rows if r['fills']>=20 and np.isfinite(r['sharpe_rf0'])]
        if not valid:raise RuntimeError('No eligible candidate; do not open later stages')
        best=max(valid,key=lambda x:(x['sharpe_rf0'],x['cagr']))
        p.export(models,best['p_threshold'],best['s_threshold'],va.sample(min(5000,len(va)),random_state=42))
        patch_platform()
        lock={'selected':best,'development_profit_gate_passed':best['total_return']>0,
            'frozen_at':pd.Timestamp.now(tz='Asia/Shanghai').isoformat(),'selection_end':'2023-12-31',
            'platform_sha256':p.sha(PLATFORM),'model_hashes':{f:p.sha(HERE/f) for f in ['event_model.joblib','stop_model.joblib']}}
        p.save(OUT/'frozen.json',lock);print('FROZEN',best,flush=True)
    lock=json.loads((OUT/'frozen.json').read_text());best=lock['selected']
    models=[p.joblib.load(HERE/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    records=[dict(best,stage='2023_selection')]
    for name,start,end in [('2020_2022_fit','2020-01-01','2022-12-31'),('2024_confirmation','2024-01-01','2024-12-31'),
        ('2025_latest','2025-01-01',p.END),('2020_continuous','2020-01-01',p.END)]:
        row=run_stage(models,start,end,best['p_threshold'],best['s_threshold'],name);records.append(row)
        print('EVALUATE',name,row['cagr'],row['max_drawdown'],flush=True)
        p.save(OUT/'comparison.json',records)
        verify(lock)
    assert all(p.sha(Path(f))==h for f,h in hashes.items())
    p.save(OUT/'verification.json',verify(lock))
    p.save(OUT/'completion.json',{'completed':True,'old_files_unchanged':True,'refit_after_freeze':False})
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
