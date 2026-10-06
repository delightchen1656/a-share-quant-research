from pathlib import Path
import json,hashlib,ast
import pandas as pd
import numpy as np
P=Path(__file__).resolve().parent;W=P.parent/'start_dates_202001';BASE=P.parents[1]
def read(p):return json.loads(p.read_text(encoding='utf-8'))
a=read(P/'results.json')[0];b=read(W/'results.json')[0]
checks={
 'same_market_inputs':read(P/'evaluation_inputs.json')==read(W/'evaluation_inputs.json'),
 'same_initial_signal':read(P/'rankings.json')['2019-12-31']==read(W/'rankings.json')['2019-12-31'],
 'original_engine_ast_unchanged':ast.dump(ast.parse((P/'weekly_engine.py').read_text(encoding='utf-8')))==ast.dump(ast.parse((BASE/'start_date_study/study.py').read_text(encoding='utf-8'))),
 'strategy_unchanged':hashlib.sha256((P.parent/'uploaded_source.py').read_bytes()).hexdigest()==read(P/'protocol.json')['strategy_sha256']}
e=pd.read_parquet(P/'daily_equity.parquet');nav=e.equity.to_numpy()
checks['equity_drawdown']=np.isclose(nav[-1],a['final_equity']) and np.isclose(-(nav/np.maximum.accumulate(np.r_[100000.,nav])[1:]-1).min(),a['max_drawdown'])
checks['cash_and_actions']=e.cash.ge(-.01).all() and a['unresolved_actions']==0
checks={k:bool(v) for k,v in checks.items()};assert all(checks.values()),checks
(P/'validation.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
rows=[]
for name,r in [('原上传版：20交易日调仓',a),('周调仓版',b)]:
    values=[name,f"{r['final_equity']:,.2f}",f"{r['total_return']:.2%}",f"{r['cagr']:.2%}",f"{r['max_drawdown']:.2%}",str(r['trades']),f"{r['fees']:,.2f}"]
    rows.append('<tr>'+''.join('<td>'+v+'</td>' for v in values)+'</tr>')
doc='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>D11原版与周调仓对照</title><style>body{font:16px Microsoft YaHei,sans-serif;max-width:1100px;margin:40px auto;line-height:1.8;color:#24364b}td,th{padding:12px;border-bottom:1px solid #ddd;text-align:right}</style><h1>D11原版与周调仓：同口径回放</h1><p>2020年1月1日休市，两账户均从2020-01-02开始，初始资金各10万元、空仓，终点2026-09-30。均为原权重-0.35/-0.20/+0.25/-0.20，同一行情库及现金、分红送转、税费、滑点账本。</p><table><tr><th>版本</th><th>期末资产(元)</th><th>累计收益</th><th>年化</th><th>最大回撤</th><th>成交笔数</th><th>交易费用(元)</th></tr>'''+''.join(rows)+'''</table><p>本次同口径结果中，20交易日调仓收益明显较高，回撤也略低。不能只凭总费用归因：两版资金规模与持仓路径不同。若需解释收益差额，需另做逐笔持仓、换手与股票贡献拆解。</p><p>这是本地日线开盘近似撮合，非平台服务器验证；送转零股与部分税务分类仍近似，历史股票池完整性未证明。期末持仓按收盘价估值，不强制平仓。仅回放既定策略，未选参或优化。</p></html>'''
(P/'comparison.html').write_text(doc,encoding='utf-8');print('PASS',len(checks))
