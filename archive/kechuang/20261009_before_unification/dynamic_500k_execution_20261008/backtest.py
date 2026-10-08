"""Daily proxy for uploaded legacy models and patched dynamic sizing, not server replay."""
from pathlib import Path
import inspect, json, sys, html
HERE=Path(__file__).resolve().parent
STAR=HERE.parent
sys.path.insert(0,str(STAR/'baseline_3_1_start_dates_100k_20261008'))
import run as ref
s=ref.s;p=ref.p;pd=p.pd;np=p.np
OUT=HERE/'backtest_results';END='2026-09-30'
SOURCE=HERE/'supermind_3_legacy_dynamic_500k_execution_v1.py'

def executor(panels,meta,actions):
    env=dict(s.__dict__);env['old_exit']=ref.old_exit
    source=inspect.getsource(s.executor)
    source=source.replace("ns['g'].model={'max_positions':14,'top_per_day':8}","ns['g'].model={'max_positions':14,'top_per_day':8};ns['_exit_action']=old_exit")
    source=source.replace('prepared_days=days,print=','prepared_days=days,CASH=500000.,print=').replace('/1e6-1','/500000.-1')
    replacements={
      '            used={}':'            used={}\n            cash_budget=cash',
      '                desired=int(equity(True)*.10/px)':'''                fraction=max(.10,float(r.open)*200*1.01/equity(True))
                if fraction>.20:continue
                reserve=equity(True)*fraction*1.005
                if min(cash,cash_budget)<reserve:continue
                desired=int(equity(True)*fraction/px)''',
      '                cash-=amt+fee; used[s]=used.get(s,0)+qty':'                cash-=amt+fee; cash_budget-=reserve; used[s]=used.get(s,0)+qty',
      '                signal=float(prevday[s].close)*(r.adjust_ratio if np.isfinite(r.adjust_ratio) else 1.)':'                signal=float(r.open)'}
    env['replacements']=replacements
    source=source.replace('    exec(src,env)','    for before,after in replacements.items():\n        assert before in src,before\n        src=src.replace(before,after)\n    exec(src,env)')
    exec(source,env)
    return env['executor'](panels,meta,'2020-01-01',END,actions)

def main():
    OUT.mkdir(exist_ok=True);s.OUT=OUT;p.OUT=OUT
    original_hash=p.sha(SOURCE)
    ns=p.namespace(SOURCE.read_text(encoding='utf-8'))
    models=[p.fast(json.loads(p.zlib.decompress(p.base64.b64decode(ns[k])))) for k in ['_EMBEDDED_MODEL_B64','_EMBEDDED_STOP_MODEL_B64']]
    snapshot=ref.BASE/'snapshots'/END
    manifest=json.loads((snapshot/'manifest.json').read_text(encoding='utf-8'))
    assert all(p.sha(snapshot/f)==v['sha256'] for f,v in manifest.items())
    ds,panels,meta=p.dataset(snapshot,'2020-01-01',END)
    ds=ds[ds.symbol.isin(models[0]['universe'])].copy()
    ds['p']=ns['_batch_probabilities'](models[0],ds[p.F].to_numpy())
    ds['stop']=ns['_batch_probabilities'](models[1],ds[p.F].to_numpy());ds['score']=ds.p-.22*ds.stop
    cand=s.candidates(ds,.63,.50)
    cache={}
    for folder in [STAR/'baseline_3_2',STAR/'baseline_3_rebuild_20261008/ablation',STAR/'baseline_3_1_start_dates_500k_20261008']:
        for f in folder.rglob('corporate_actions.json'):cache.update(json.loads(f.read_text(encoding='utf-8')))
    p.save(OUT/'corporate_actions.json',cache)
    actions=s.prepare_actions(panels,{x for v in cand.values() for x in v},'2020-01-01',END)
    result=executor(panels,meta,actions)(cand)
    s.save_run('2020_continuous',result)
    metrics,curve,trades,diffs=result
    tx=trades[trades.side!='WRITE_OFF']
    commission=float(np.maximum(5,tx.amount*.0003).sum());stamp=float(tx.loc[tx.side!='BUY','amount'].sum()*.001)
    assert np.isclose(tx.fee.sum(),commission+stamp)
    assert curve.cash.min()>=-.01
    assert tx.loc[tx.side=='BUY','qty'].ge(200).all() and tx.qty.le(50000).all()
    nav=curve.equity.to_numpy()/500000
    assert np.isclose((nav/np.maximum.accumulate(np.r_[1,nav])[1:]-1).min(),metrics['max_drawdown'])
    assert np.isclose(nav[-1]-1,metrics['total_return'])
    assert p.sha(SOURCE)==original_hash
    metrics.update(initial_cash=500000,commission=commission,stamp_tax=stamp,total_fees=commission+stamp,
                   source_sha256=original_hash,reference_price_differences=len(diffs))
    p.save(OUT/'summary.json',metrics)
    p.save(OUT/'protocol.json',{'capital':500000,'end':END,'model_retrained':False,'source':str(SOURCE),'source_sha256':original_hash,
        'sizing':'dynamic max(.10,open*200*1.01/NAV),skip>.20; cash and local budget >=target*1.005',
        'universe':'old embedded static','signal':'previous-day features; OPEN proxy for legacy last_price/close exit',
        'execution':'buy before sell; T+1; halts/limit-lock skipped; 25% daily volume cap; max50000 shares/order; buy>=200',
        'cost':'each-side .2%slip; commission .0003 min5; stamp .001 full period; dividend tax20%; no transfer fee',
        'limitations':['not actual platform callback replay','does not simulate unresolved-order blocking/network/restart','corporate action risk reference adjusted by local engine unlike untouched legacy platform state','data only through2026-09-30'],
        'source_files_verified':len(manifest)})
    p.save(OUT/'verification.json',{'passed':True,'cash_nonnegative':True,'fees_reconciled':True,'drawdown_recomputed':True,'min_buy200':True,'platform_unchanged':True,'platform_server_tested':False})
    table=''.join('<tr><td>'+html.escape(k)+'</td><td>'+v+'</td></tr>' for k,v in [
        ('最终资产',f"{metrics['final_asset']:,.2f}元"),('累计收益',f"{metrics['total_return']:.2%}"),('年化',f"{metrics['cagr']:.2%}"),('最大回撤',f"{-metrics['max_drawdown']:.2%}"),('Sharpe',f"{metrics['sharpe_rf0']:.3f}"),('平均仓位',f"{metrics['avg_exposure']:.2%}"),('成交次数',str(metrics['fills'])),('佣金',f'{commission:,.2f}元'),('印花税',f'{stamp:,.2f}元')])
    (HERE/'backtest_report.html').write_text('<!doctype html><meta charset="utf-8"><style>body{font:16px Microsoft YaHei;margin:32px}td{padding:10px;border-bottom:1px solid #ccc}</style><h1>旧模型动态仓位50万元：本地日线近似回放</h1><p>2020-01-02至2026-09-30；不是截至今天的行情，不是平台实测。</p><table>'+table+'</table><p>模型不变。费用已扣；成本、容量及公司行动为本地近似；开盘价代理旧last_price退出。订单回报故障及异常暂停不在历史日线收益模拟中。历史股票池及模型研究偏差保留，不能视为独立样本外。</p>',encoding='utf-8')
    print(json.dumps(metrics,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
