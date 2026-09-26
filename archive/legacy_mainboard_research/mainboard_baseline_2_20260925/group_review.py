"""Summarize group experiments and stress the development-selected candidate."""
import json
import numpy as np
import pandas as pd
import group_research as g

LABEL={'float_cap_proxy':'流通市值代理','turn20':'换手率','vol60':'波动率','amount20':'成交额','ret60':'过去60日涨幅','price':'股价','dividend':'分红代理','downside':'下行波动'}
METHOD={'reversal':'反转','trend':'趋势','quality':'稳健代理'}
def label(row):
 kind=row['kind']
 if kind=='industry':return str(row['industry'])+' / '+METHOD[row['method']]
 if kind=='exchange':return row['exchange']+'市场 / '+METHOD[row['method']]
 if kind=='rotate':return LABEL[row['dim']]+'组间轮动 / '+METHOD[row['method']]
 s=LABEL[row['dim']]+['低组','中组','高组'][int(row['group'])]
 if kind=='cross':s+=' × '+LABEL[row['other']]+['低组','中组','高组'][int(row['other_group'])]
 return s+' / '+METHOD[row['method']]

def ranks_for(f,cfg):
 rr={}
 for d,x in f.groupby('execute_date'):
  if d.month not in [1,4,7,10]:continue
  q=x;kind=cfg['kind']
  if kind in ['single','cross']:q=q[q[cfg['dim']+'_group']==cfg['group']]
  if kind=='cross':q=q[q[cfg['other']+'_group']==cfg['other_group']]
  if kind=='exchange':q=q[q.exchange==cfg['exchange']]
  if kind=='rotate':
   gs=q[q[cfg['dim']+'_group']>=0].groupby(cfg['dim']+'_group').ret60.median()
   q=q[q[cfg['dim']+'_group']==gs.idxmax()] if len(gs) else q.iloc[:0]
  q=g.score(q,cfg['method']);rr[d]=q if len(q)>=10 else q.iloc[:0]
 return rr

def main():
 r=pd.read_csv(g.OUT/'results.csv');p=json.loads((g.OUT/'protocol.json').read_text(encoding='utf-8'))
 assert len(r)==len(p['configurations'])
 controls=pd.read_csv(g.OUT/'controls.csv');win=json.loads((g.OUT/'candidate.json').read_text(encoding='utf-8'))
 base=pd.read_csv(g.HERE/'small_account_100k/comparison.csv').set_index('name').loc['n10_m3_min3000']
 r['label']=r.apply(label,axis=1)
 formal=r[r.kind!='industry'];both=formal[(formal.full_annualized_return>base.full_annualized_return)&(formal.full_max_drawdown>base.full_max_drawdown)]
 c=pd.read_csv(g.OUT/'candidate_equity.csv',parse_dates=['date']);t=pd.read_csv(g.OUT/'candidate_trades.csv',parse_dates=['date'])
 audit={'cash_nonnegative':bool((c.cash>=-.01).all()),'buy_lots_100':bool((t.loc[t.side=='BUY','quantity']%100==0).all()),'no_same_day_roundtrip':bool(t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty),'min_commission_5':bool((t.commission>=5-.00001).all()),'maximum_holdings':int(c.holdings.max()),'commission':float(t.commission.sum()),'stamp_tax':float(t.stamp_tax.sum()),'orders':len(t),'observed_full_period_dominators_not_selection':both.name.tolist()}
 (g.OUT/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
 # Identical rules, increased trading friction: not another parameter search.
 g.bt.INITIAL_CASH=100000.;rr=ranks_for(g.features(),win)
 panel=g.bt.load_daily_panel(set(s for q in rr.values() for s in q.head(30).symbol))
 g.bt.SLIPPAGE=.004;g.bt.COMMISSION=.0006;g.bt.MIN_COMMISSION=10.
 stress,st=g.bt.simulate(rr,.05,10,30,.8,1.5,panel,min_adjustment=3000)
 sm=g.bt.metrics(stress,100000);stress.to_csv(g.OUT/'stress_equity.csv',index=False)
 (g.OUT/'stress.json').write_text(json.dumps(sm,indent=2),encoding='utf-8')
 lines=['# 沪深主板：10万元分组研究结论','',f'共{len(r)}条分组策略，加3条不分组对照。区间2020-01-02至2026-09-11；不是科创板、创业板或全A股。','',
 '统一目标10只、80%仓位、季度调仓、排名前30保留缓冲、已有仓位小于3000元的调整跳过。低/中/高为每个信号日合格股票池的三分位，不是固定金额阈值。', '',
 '## 原版与开发期选出的分组候选','', '|路线|全期年化|全期最大回撤|Sharpe|期末万元|开发期年化|2024年化|2025后年化|累计佣金元|', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for name,z in [('原10万元基准2',base),(label(win),win)]:
  lines.append(f"|{name}|{z['full_annualized_return']:.2%}|{z['full_max_drawdown']:.2%}|{z['full_sharpe']:.3f}|{z['full_final_equity']/10000:.2f}|{z['dev_annualized_return']:.2%}|{z['validation_annualized_return']:.2%}|{z['observed_annualized_return']:.2%}|{z['commission']:.0f}|")
 lines+=['','## 各分组维度','', '下表每个维度选开发期评分最高且满足开发期回撤/覆盖条件的一条；不代表整类策略都好。','', '|维度|开发期选出的路线|全期年化|最大回撤|2024年化|2025后年化|','|---|---|---:|---:|---:|---:|']
 for dim in g.DIMENSIONS:
  a=r[(r.kind=='single')&(r.dim==dim)&r.eligible].sort_values('score',ascending=False)
  if len(a):
   z=a.iloc[0];lines.append(f'|{LABEL[dim]}|{z.label}|{z.full_annualized_return:.2%}|{z.full_max_drawdown:.2%}|{z.validation_annualized_return:.2%}|{z.observed_annualized_return:.2%}|')
 lines+=['','## 不分组对照','', '|选股法|全期年化|最大回撤|','|---|---:|---:|']
 for z in controls.itertuples():lines.append(f'|{METHOD[z.method]}|{z.full_annualized_return:.2%}|{z.full_max_drawdown:.2%}|')
 lines+=['','## 费用压力与限制','',f"候选将双边滑点从0.2%升为0.4%、佣金万三/最低5元升为万六/最低10元后：年化{sm['annualized_return']:.2%}，最大回撤{sm['max_drawdown']:.2%}。压力测试没有增加额外执行约束。",'',
 f'138条非行业路线中，全期同时超过原版年化且回撤更小的有{len(both)}条；这个数字仅描述结果，不用来重新选参。', '',
 '开发期2020—2023用于选择，2024与2025后用于观察；历史已反复测试且试验很多，不是真正未见样本外，不能保证未来有效。没有自动覆盖原基准。', '',
 '流通市值由成交量/换手率推算，不是总市值。行业采用2026年当前分类，有历史错配风险，31条行业路线排除正式选优。分红代理是复权因子变化，不是真实股息率，也不是财务质量。未覆盖可靠历史估值、财务、机构持仓、地域/产业链及相关性聚类。', '',
 '费用沿用比较口径：佣金万三最低5元、双边0.2%滑点、卖出固定0.1%税率，未单列过户费，不代表完整历史实盘费率。原引擎公司行动近似和固定股票池偏差仍存在，5%日成交量限制不能验证开盘容量。整数手、无同日买卖等检查通过也不等于全部实盘限制已验证。']
 (g.OUT/'结论.md').write_text('\n'.join(lines),encoding='utf-8')
 r.to_csv(g.OUT/'labeled_results.csv',index=False,encoding='utf-8-sig')
 print('\n'.join(lines));print('AUDIT',audit)

if __name__=='__main__':main()
