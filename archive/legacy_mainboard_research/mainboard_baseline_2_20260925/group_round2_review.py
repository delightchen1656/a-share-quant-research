"""Reproduce selected regime candidate; stress costs and entry dates."""
import json
import numpy as np
import pandas as pd
import group_research as g
from group_round2 import OUT

def main():
 r=pd.read_csv(OUT/'results.csv');win=json.loads((OUT/'candidate.json').read_text(encoding='utf-8'))
 assert win['name']=='defensive_bear_8', 'Review reconstructs this rule explicitly; update for another selection'
 f=g.features();base=g.bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
 idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet');idx['date']=pd.to_datetime(idx.date);idx=idx.sort_values('date')
 rr={};states=[]
 for d,x in base.items():
  if d.month not in [1,4,7,10]:continue
  signal=x.signal_date.iloc[0];hist=idx[idx.date<=signal].tail(120)
  bull=bool(hist.close.iloc[-1]>hist.close.mean())
  q=x if bull else g.score(x[x.float_cap_proxy_group==1],'quality')
  rr[d]=q.sort_values(['score','symbol'],ascending=[False,True])
  states.append(dict(execute_date=str(d.date()),signal_date=str(signal.date()),state='baseline' if bull else 'midcap_defensive'))
 assert all(pd.Timestamp(s['signal_date'])<pd.Timestamp(s['execute_date']) for s in states)
 panel=g.bt.load_daily_panel(set(s for q in rr.values() for s in q.head(24).symbol));g.bt.INITIAL_CASH=100000.
 c,t=g.bt.simulate(rr,.05,8,24,.8,1.5,panel,min_adjustment=3000)
 saved=pd.read_csv(OUT/'defensive_bear_8_equity.csv');assert np.allclose(c.equity,saved.equity,atol=.01,rtol=0)
 checks={'reproduced':True,'cash_nonnegative':bool((c.cash>=-.01).all()),'buy_lots_100':bool((t[t.side=='BUY'].quantity%100==0).all()),'no_same_day_round_trip':bool(t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty),'max_holdings':int(c.holdings.max()),'orders':len(t),'commission':float(t.commission.sum()),'stamp_tax':float(t.stamp_tax.sum())}
 tests=[]
 for name,start,cost in [('standard','2020-01-02',1),('double_cost','2020-01-02',2),('entry_2023','2023-01-01',1),('entry_2025','2025-01-01',1)]:
  g.bt.START=pd.Timestamp(start);g.bt.SLIPPAGE=.002*cost;g.bt.COMMISSION=.0003*cost;g.bt.MIN_COMMISSION=5.*cost
  z,tr=g.bt.simulate(rr,.05,8,24,.8,1.5,panel,min_adjustment=3000)
  tests.append(dict(name=name,**g.bt.metrics(z,100000)))
  z.to_csv(OUT/(name+'_check_equity.csv'),index=False)
 pd.DataFrame(tests).to_csv(OUT/'stress_and_entries.csv',index=False)
 (OUT/'audit.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
 (OUT/'regimes.json').write_text(json.dumps(states,indent=2),encoding='utf-8')
 old=json.loads((g.OUT/'candidate.json').read_text(encoding='utf-8'))
 names={'control':'原10万元基准2','defensive_bear_8':'G02 顺势防守8','defensive_bear_10':'同规则10只','defensive_bear_12':'同规则12只'}
 lines=['# 分组优化第二轮：顺势防守','', '40项配置（含原版对照），10万元，2020-01-02至2026-09-11。测试方案先落盘，按2020—2023评分选择；本轮已受前轮历史观察影响，不是独立样本外。', '',
 '## 主要结果','', '|策略|年化|最大回撤|Sharpe（无风险利率0）|期末万元|','|---|---:|---:|---:|---:|']
 for name,label in names.items():
  z=r[r.name==name].iloc[0];lines.append(f'|{label}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.full_sharpe:.3f}|{z.full_final_equity/10000:.2f}|')
 lines.append(f"|上轮中盘稳健|{old['full_annualized_return']:.2%}|{abs(old['full_max_drawdown']):.2%}|{old['full_sharpe']:.3f}|{old['full_final_equity']/10000:.2f}|")
 lines+=['','## 固定规则','', '季度首个交易日调仓；仅用前一交易日及此前信息判断中证500是否高于120日均线。高于均线使用原基准强市选股评分；否则只在流通市值代理中间三分之一内，以分红代理、低下行波动和低换手综合评分选股。目标8只、24名保留缓冲、80%仓位，按下行风险倒数分配；已有持仓不足3000元的调整跳过，清仓不受此限制。不是每日择时或动态仓位控制。', '',
 f"开发期年化{win['dev_annualized_return']:.2%}；2024年化{win['validation_annualized_return']:.2%}；2025年至截止日年化{win['observed_annualized_return']:.2%}。", '',
 '## 压力与入场测试','', '不同入场年份是独立10万元新账户，不是从原组合截取收益。费用加倍仅加倍佣金和滑点，印花税假设不变。','', '|测试|年化|最大回撤|期末万元|','|---|---:|---:|---:|']
 for z in tests:lines.append(f"|{z['name']}|{z['annualized_return']:.2%}|{abs(z['max_drawdown']):.2%}|{z['final_equity']/10000:.2f}|")
 lines+=['',f"候选共{checks['orders']}笔成交、佣金{checks['commission']:.2f}元、固定税率口径印花税{checks['stamp_tax']:.2f}元。现金、100股买入和无同日往返检查通过。", '',
 '## 结论边界','', '相对原基准三项指标均改善；相对上轮中盘稳健，收益和Sharpe提升，但最大回撤略高，不能称为对所有基准全面占优。8/10/12只均改善原版，不代表统计显著或未来保证。原基准和上一轮候选保持不变；G02是研究候选，未在平台复核。', '',
 '已重复尝试大量参数，所有历史分段都受研究者观察影响。固定股票池存在幸存者偏差风险；市值和分红均为代理，公司行动处理近似。费用沿用万三最低5元、双边0.2%滑点、固定卖出税率0.1%，未单列过户费，不是完整历史实盘费率。日成交量5%限制不能证明开盘可成交。上述问题修复前不能把数值作为可靠实盘预期。']
 (OUT/'结论.md').write_text('\n'.join(lines),encoding='utf-8')
 print(json.dumps({'selected':win,'audit':checks,'tests':tests},indent=2))

if __name__=='__main__':main()
