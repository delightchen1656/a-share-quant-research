"""Frozen single-factor and chained attribution, no training or parameter search."""
from pathlib import Path
import sys, json, inspect, importlib.util, html
HERE=Path(__file__).resolve().parent
STAR=HERE.parents[1]
BASE=STAR/'baseline_3_2/retrain_2022'
sys.path.insert(0,str(BASE/'search_1000'))
import search as s
p=s.p;np=s.np;pd=s.pd;OUT=HERE/'results';END='2026-09-30'
SOURCE=STAR/'supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py'
spec=importlib.util.spec_from_file_location('reference',STAR/'baseline_3_1_start_dates_100k_20261008/run.py')
reference=importlib.util.module_from_spec(spec);spec.loader.exec_module(reference)
CONFIGS=[
 ('A','旧口径参照','static','open','old','old',.63,.50,None),
 ('B','仅换历史股票池','dynamic','open','old','old',.63,.50,'A'),
 ('C','仅换退出信号时点','static','previous','old','old',.63,.50,'A'),
 ('D','仅换到期分支','static','open','audited','old',.63,.50,'A'),
 ('E','合并三项执行修订','dynamic','previous','audited','old',.63,.50,'B'),
 ('F','统一执行下换新模型','dynamic','previous','audited','new',.63,.50,'E'),
 ('G','再换新门槛','dynamic','previous','audited','new',.75,.35,'F'),
 ('H','旧执行下仅换新模型','static','open','old','new',.63,.50,'A'),
 ('I','换池后再换信号时点','dynamic','previous','old','old',.63,.50,'B')]

def engine(panels,meta,actions,signal,exit_rule):
    env=dict(s.__dict__);env['old_exit']=reference.old_exit
    source=inspect.getsource(s.executor).replace('prepared_days=days,print=','prepared_days=days,CASH=500000.,print=').replace('/1e6-1','/500000.-1')
    if exit_rule=='old':
        needle="ns['g'].model={'max_positions':14,'top_per_day':8}"
        assert needle in source
        source=source.replace(needle,needle+";ns['_exit_action']=old_exit")
    if signal=='open':
        needle="                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)"
        source=source.replace('    exec(src,env)',f"    assert {needle!r} in src\n    src=src.replace({needle!r},'                signal=float(r.open)')\n    exec(src,env)")
    exec(source,env)
    return env['executor'](panels,meta,'2020-01-01',END,actions)

def main():
    OUT.mkdir(parents=True,exist_ok=True);s.OUT=OUT;p.OUT=OUT
    files=[SOURCE,HERE.parent/'event_model.joblib',HERE.parent/'stop_model.joblib',BASE/'pipeline.py',BASE/'search_1000/search.py',p.BASE/'start_date_study.py']
    hashes={str(f):p.sha(f) for f in files}
    p.save(HERE/'protocol.json',{'capital':500000,'start':'2020-01-01','end':END,'configs':CONFIGS,'training':False,'selection':False,'hashes':hashes,'purpose':'retrospective attribution only; no independent OOS claim','costs':'inherited fixed historical approximation, not actual broker cost'})
    ns=p.namespace(SOURCE.read_text(encoding='utf-8'))
    old=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    new=[p.joblib.load(HERE.parent/f)['model'] for f in ['event_model.joblib','stop_model.joblib']]
    snapshot=BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(snapshot/f)==v['sha256'] for f,v in manifest.items())
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    scores={}
    for model in ['old','new']:
        x=ds[['date','symbol']].copy()
        for j,col in enumerate(['p','stop']):
            x[col]=ns['_batch_probabilities'](old[j],ds[p.F].to_numpy()) if model=='old' else new[j].predict_proba(ds[p.F])[:,1]
        x['score']=x.p-.22*x.stop;scores[model]=x
    candidates={}
    for key,name,pool,signal,exit_rule,model,pt,st,parent in CONFIGS:
        x=scores[model]
        if pool=='static':x=x[x.symbol.isin(old[0]['universe'])]
        candidates[key]=s.candidates(x,pt,st)
    cache={}
    for folder in [STAR/'baseline_3_2',STAR/'baseline_3_1_start_dates_500k_20261008',HERE.parent/'results']:
        for f in folder.rglob('corporate_actions.json'):cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    actions=s.prepare_actions(panels,{x for c in candidates.values() for v in c.values() for x in v},'2020-01-01',END)
    rows=[];curves={};trades={}
    for key,name,pool,signal,exit_rule,model,pt,st,parent in CONFIGS:
        result=engine(panels,meta,actions,signal,exit_rule)(candidates[key]);s.save_run(key,result)
        r,c,t,d=result;curves[key]=c;trades[key]=t
        assert c.cash.min()>=-.01 and np.isclose(r['final_asset']/500000-1,r['total_return'])
        row=dict(r,key=key,name=name,fees=float(t.fee.fillna(0).sum()),reference_differences=len(d))
        rows.append(row);p.save(OUT/'comparison.json',rows)
        print('RESULT',key,name,r['cagr'],r['max_drawdown'],flush=True)
    old_ref=json.loads((STAR/'baseline_3_1_start_dates_500k_20261008/results/comparison.json').read_text(encoding='utf-8'))[0]
    new_ref=json.loads((HERE.parent/'results/comparison.json').read_text(encoding='utf-8'))[-1]
    for key,ref in [('A',old_ref),('G',new_ref)]:
        row=next(x for x in rows if x['key']==key)
        for field in ['final_asset','cagr','max_drawdown','sharpe_rf0','fills']:assert np.isclose(row[field],ref[field],rtol=1e-10,atol=1e-7),(key,field)
    comparisons=[]
    for a,b in [('A','B'),('A','C'),('A','D'),('A','H'),('B','I'),('I','E'),('E','F'),('F','G')]:
        ra=next(x for x in rows if x['key']==a);rb=next(x for x in rows if x['key']==b)
        ea=curves[a].set_index('date').equity;eb=curves[b].set_index('date').equity
        unequal=~np.isclose(ea,eb,rtol=1e-10,atol=.0001)
        comparisons.append({'from':a,'to':b,'annualized_percentage_point_change':100*(rb['cagr']-ra['cagr']),'asset_change':rb['final_asset']-ra['final_asset'],'first_nav_difference':str(ea.index[unequal][0].date()) if unequal.any() else None})
    p.save(OUT/'deltas.json',comparisons)
    assert all(p.sha(Path(f))==h for f,h in hashes.items())
    p.save(OUT/'verification.json',{'passed':True,'runs':9,'old_result_reproduced':True,'new_result_reproduced':True,'source_hashes_unchanged':True,'snapshot_files':len(manifest)})
    table=[]
    for r in rows:
        vals=[r['key'],r['name'],f"{r['final_asset']/10000:.2f}",f"{r['cagr']:.2%}",f"{-r['max_drawdown']:.2%}",f"{r['sharpe_rf0']:.2f}",str(r['fills'])]
        table.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    page='<!doctype html><meta charset="utf-8"><title>科创3单项替换归因</title><style>body{font:16px Microsoft YaHei;margin:32px}td,th{padding:10px;border-bottom:1px solid #ddd}p{max-width:1000px;line-height:1.8}</style><h1>科创3：50万元单项替换归因</h1><p>2020-01-02—2026-09-30。无训练、无选优、无晋升。A与旧报告、G与新报告逐项一致。独立对照A→B/C/D/H；串联A→B→I→E→F→G。模型变化包含整个重训方案的差异，不等于仅训练日期的因果效果。</p><table><tr><th>编号</th><th>方案</th><th>最终资产万元</th><th>年化</th><th>回撤</th><th>Sharpe</th><th>成交数</th></tr>'+''.join(table)+'</table><p>旧开盘退出是last_price的本地代理，不是平台已核验执行；全期千一印花税、分红20%扣税和日量容量均为近似。本报告用于识别收益差异，不代表真实可成交、未来收益或独立样本外。</p>'
    (HERE/'report.html').write_text(page,encoding='utf-8')
    print('COMPLETE',flush=True)

if __name__=='__main__':main()
