"""Independent accounting/selection checks for phase 1; not full execution certification."""
from pathlib import Path
import json, hashlib, html
import pandas as pd
import numpy as np
HERE=Path(__file__).resolve().parent; OUT=HERE/'results'
def read(f):return json.loads(f.read_text(encoding='utf-8'))
lock=read(OUT/'frozen.json'); trials=read(OUT/'all_trials_2023.json')
assert len(trials)==81 and len({x['id'] for x in trials})==81
best=max([x for x in trials if x['fills']>=20 and np.isfinite(x['cagr'])],key=lambda x:(x['cagr'],-([7,15,31][x['event']]+[7,15,31][x['stop']]),-x['id']))
assert best==lock['selected']
assert all(pd.Timestamp(x['max_label_end'])<=pd.Timestamp('2022-12-31') for x in read(OUT/'model_metrics.json'))
assert all(hashlib.sha256((HERE/f).read_bytes()).hexdigest()==h for f,h in lock['hashes'].items())
results=read(OUT/'comparison.json')
assert len(results)==5
for r in results:
    c=pd.read_parquet(OUT/r['stage']/'daily_equity.parquet')
    t=pd.read_parquet(OUT/r['stage']/'trades.parquet')
    nav=c.equity.to_numpy()/500000
    assert c.cash.min()>=-.01
    assert np.isclose(r['final_asset'],c.equity.iloc[-1])
    assert np.isclose(r['total_return'],nav[-1]-1)
    assert np.isclose(r['max_drawdown'],(nav/np.maximum.accumulate(np.r_[1.,nav])[1:]-1).min())
    assert np.isclose(r['cagr'],nav[-1]**(365.25/(pd.Timestamp(r['end'])-pd.Timestamp(r['start'])).days)-1)
    executed=t[t.side!='WRITE_OFF']
    fees=np.maximum(5,executed.amount*.0003)+np.where(executed.side=='BUY',0,executed.amount*.001)
    assert np.isclose(fees.sum(),r['fees'])
    assert executed.loc[executed.side=='BUY','qty'].ge(200).all()
    assert executed.qty.le(50000).all()
checks={'passed':True,'trial_count':81,'selection_recomputed':True,'label_end_before2023':True,'hashes_verified':True,'accounts_checked':5,'full_engine_audit':False}
(OUT/'phase1_verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
rows=[]
for r in results:
    vals=[r['stage'],f"{r['final_asset']:,.2f}",f"{r['cagr']:.2%}",f"{abs(r['max_drawdown']):.2%}",f"{r['sharpe_rf0']:.2f}",f"{r['avg_exposure']:.2%}",str(r['fills'])]
    rows.append('<tr>'+''.join('<td>'+html.escape(v)+'</td>' for v in vals)+'</tr>')
page='''<!doctype html><meta charset="utf-8"><title>科创3重建第一阶段</title><style>body{font:16px Microsoft YaHei;margin:36px;color:#203349}td,th{padding:12px;border-bottom:1px solid #ddd}p{max-width:1000px;line-height:1.8}</style><h1>科创3：50万元从零重训｜第一阶段</h1><p>6个新模型、81组2023年扣费年化选择。全部组合开发年化为负，16号只是相对最优，不晋升正式基准。原3-1和历史模型不变。</p><table><tr><th>阶段</th><th>最终资产元</th><th>年化</th><th>最大回撤</th><th>Sharpe</th><th>平均仓位</th><th>成交</th></tr>'''+''.join(rows)+'''</table><p>2020—2022训练，2023选择；冻结后评价2024及2025—2026-09-30。全期包含训练期。固定10%单票、14只上限；历史动态股票池；昨日收盘退出信号、次日开盘撮合；到期优先。这些执行修订不同于旧3-1开盘价代理回放，不能直接将收益差异全部归因于重训。</p><p>仍使用单边0.2%滑点、万三最低5元佣金、全期千一卖出印花税、20%分红扣税，未单列过户费。日量25%容量只是撮合近似。本报告不是平台实测或完整研究流程验收。</p><p>未完成：简单组合对照、历史税费重建、等长及起点稳健性、延迟/容量/成本压力、订单故障审计和前向模拟。平台文件仅自动导出草稿，未作服务器测试，不应作为可直接部署交付。</p>'''
(HERE/'report.html').write_text(page,encoding='utf-8')
print(json.dumps(checks))
