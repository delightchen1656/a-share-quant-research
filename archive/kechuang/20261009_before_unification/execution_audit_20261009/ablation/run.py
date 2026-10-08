"""Paired daily-proxy ablations; execution callback failures are not synthesized."""
from pathlib import Path
import sys,inspect,json,html
HERE=Path(__file__).resolve().parent
STAR=HERE.parents[1]
sys.path.insert(0,str(STAR/'baseline_3_1_start_dates_100k_20261008'))
import run as ref
s=ref.s;p=ref.p;pd=p.pd;np=p.np
OUT=HERE/'results';START='2026-01-01';END='2026-09-30'
CONFIGS=[('A旧动态',True,True,False,False),('B仅固定10%',False,True,False,False),('C仅允许现金不足缩量',True,False,False,False),('D仅修正到期分支',True,True,False,True),('E固定加缩量',False,False,False,False),('F再换新版股数预算',False,False,True,False),('G新版组合',False,False,True,True)]
def corrected_exit(price,state,amount,today,position_days):
    result=ref.old_exit(price,state,amount,today,position_days)
    if result is not None:return result
    age=(today-state['entry_date']).days
    if age>=60:return 'TIME60',0
    if age>=30 and price/state['entry']-1<.10:return 'TIME30',0
    return None
def executor(panels,meta,actions,cfg):
    name,dynamic,fullcash,newqty,expiry=cfg
    env=dict(s.__dict__);env['chosen_exit']=corrected_exit if expiry else ref.old_exit
    source=inspect.getsource(s.executor)
    source=source.replace("ns['g'].model={'max_positions':14,'top_per_day':8}","ns['g'].model={'max_positions':14,'top_per_day':8};ns['_exit_action']=chosen_exit")
    source=source.replace('prepared_days=days,print=','prepared_days=days,CASH=500000.,print=').replace('/1e6-1','/500000.-1')
    sizing='''                nav=equity(True)
                fraction=max(.10,float(r.open)*200*1.01/nav) if DYNAMIC else .10
                if fraction>.20:continue
                reserve=nav*fraction*1.005
                if FULLCASH and cash<reserve:continue
                desired=int(nav*fraction/px)'''.replace('DYNAMIC',str(dynamic)).replace('FULLCASH',str(fullcash))
    if newqty:
        sizing='''                nav=equity(True)
                padded=float(r.open)*1.002
                desired=int(min(nav*.10/float(r.open),(min(cash,cash_budget)-5.01)/(padded*1.0003)))
                reserve=desired*padded+max(5.,desired*padded*.0003)+.01
                if reserve>min(cash,cash_budget):continue'''
    replacements={'            used={}':'            used={}\n            cash_budget=cash','                desired=int(equity(True)*.10/px)':sizing,'                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)':'                signal=float(r.open)'}
    if newqty:replacements['                cash-=amt+fee; used[s]=used.get(s,0)+qty']='                cash-=amt+fee; cash_budget-=reserve; used[s]=used.get(s,0)+qty'
    env['replacements']=replacements
    source=source.replace('    exec(src,env)','    for before,after in replacements.items():\n        assert before in src,before\n        src=src.replace(before,after)\n    exec(src,env)')
    exec(source,env)
    return env['executor'](panels,meta,START,END,actions)
def main():
    OUT.mkdir(parents=True,exist_ok=True);s.OUT=OUT;p.OUT=OUT
    files=[Path(r'C:\Users\22241\.codex\attachments\e69a4b9a-10c8-4d0a-9cf6-9b56177d08a1\已粘贴的文本.txt'),Path(r'C:\Users\22241\.codex\attachments\49ab7006-7ea7-4701-afb4-7cda9085ccf4\已粘贴的文本.txt')]
    ns=p.namespace(files[0].read_text(encoding='utf-8-sig'));new=p.namespace(files[1].read_text(encoding='utf-8-sig'))
    keys=['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64'];assert all(ns[k]==new[k] for k in keys)
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in keys]
    snapshot=ref.BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text());assert all(p.sha(snapshot/f)==v['sha256'] for f,v in manifest.items())
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    ds=ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy());ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy());ds['score']=ds.p-.22*ds.stop
    cand=s.candidates(ds,.63,.50)
    cache=json.loads((STAR/'baseline_3_1_start_dates_500k_20261008/results/corporate_actions.json').read_text(encoding='utf-8'))
    p.save(OUT/'corporate_actions.json',cache)
    actions=s.prepare_actions(panels,{x for v in cand.values() for x in v},START,END)
    p.save(HERE/'protocol.json',{'start':START,'end':END,'capital':500000,'configs':CONFIGS,'source_hashes':[p.sha(f) for f in files],'model_equal':True,'retrained':False,'cost':'0.2% slip each side,commission0.03%min5,sellstamp0.1%,dividend20%,local proxy','limitations':['same local signals for all variants, not platform signal parity','all callbacks assumed successful; blocking not simulated','entry dates accurate in all runs; old missing-date behavior cannot be inferred','opening price proxy for platform daily bar/last_price','historical price adjustment applied by shared engine']})
    rows=[];basekeys=None
    for cfg in CONFIGS:
        result=executor(panels,meta,actions,cfg)(cand);s.save_run(cfg[0][0],result)
        m,curve,tx,diffs=result
        assert curve.cash.min()>=-.01 and tx.loc[tx.side=='BUY','qty'].ge(200).all()
        keys=set(zip(tx.date.astype(str),tx.symbol,tx.side))
        if basekeys is None:basekeys=keys
        row=dict(m,name=cfg[0],fees=float(tx.fee.sum()),changed_keys_vs_A=len(keys^basekeys));rows.append(row)
        p.save(OUT/'summary.json',rows);print(json.dumps(row,ensure_ascii=True),flush=True)
    p.save(OUT/'verification.json',{'runs':len(rows),'cash_and_min_buy_checks':True,'model_blobs_equal':True,'platform_tested':False})
    headers=['变更','期末资产','累计','年化','回撤','Sharpe','平均仓位','成交','费用','相对A资产差']
    tr=[]
    for r in rows:
        vals=[r['name'],f"{r['final_asset']:,.2f}",f"{r['total_return']:.2%}",f"{r['cagr']:.2%}",f"{abs(r['max_drawdown']):.2%}",f"{r['sharpe_rf0']:.3f}",f"{r['avg_exposure']:.2%}",str(r['fills']),f"{r['fees']:,.2f}",f"{r['final_asset']-rows[0]['final_asset']:,.2f}"]
        tr.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
    (HERE/'report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:15px Microsoft YaHei;margin:30px}td,th{padding:10px;border-bottom:1px solid #ddd}table{border-collapse:collapse}</style><h1>动态旧版与固定修复版：逐项本地对比</h1><p>50万元，2026年初至2026-09-30；共享本地信号和日线撮合，非平台复现。B/C/D是相对A单独改动，E/F/G是累计改动。</p><table><tr>'+''.join('<th>'+v+'</th>' for v in headers)+'</tr>'+''.join(tr)+'</table><p>回调故障、异常停单、买入日期缺失及平台信号差异未模拟，不能由本表定量归因。费用为旧引擎统一近似。</p>',encoding='utf-8')
if __name__=='__main__':main()
