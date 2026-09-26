import hashlib,json
import pandas as pd
import group_research as g
import group_round3 as r3

def main():
 out=r3.OUT;r=pd.read_csv(out/'results.csv');ref=r[r.name=='pending1_control'].iloc[0]
 r['dominates_pending1']=(r.full_annualized_return>ref.full_annualized_return)&(r.full_max_drawdown>ref.full_max_drawdown)&(r.full_sharpe>ref.full_sharpe)
 assert not r.dominates_pending1.any()
 audit=pd.read_csv(out/'signal_audit.csv',parse_dates=['execute_date','signal_date'])
 assert (audit.signal_date<audit.execute_date).all() and audit.exposure.between(0,1).all()
 labels={'pending1_control':'基准2待定1','temperature_0.3':'温度低位过滤（开发期选出）','exposure_regime':'强弱市仓位调整（观察项）','risk_weight_equal':'等权持仓','risk_weight_vol60':'按总波动配权','temperature_0.7':'更严格温度过滤','cadence_1':'月度调仓','cadence_2':'双月调仓'}
 for i,z in r.iterrows():
  c=pd.read_csv(out/(z['name']+'_equity.csv'),parse_dates=['date']);t=pd.read_csv(out/(z['name']+'_trades.csv'),parse_dates=['date'])
  assert (c.cash>=-.01).all() and (t[t.side=='BUY'].quantity%100==0).all()
  assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
  amount=t.groupby('date').amount.sum();years=(c.date.iloc[-1]-c.date.iloc[0]).days/365.25
  r.loc[i,'annual_two_sided_turnover']=(amount/c.set_index('date').equity.reindex(amount.index)).sum()/years
 r.to_csv(out/'results_reviewed.csv',index=False)
 cfg=next(z for z in r3.configs() if z['name']=='temperature_0.3')
 rr,ee,_,union=r3.prepare(g.features(),[cfg]);panel=g.bt.load_daily_panel(union)
 g.bt.INITIAL_CASH=100000.;g.bt.SLIPPAGE=.004;g.bt.COMMISSION=.0006;g.bt.MIN_COMMISSION=10.
 c,t=g.bt.simulate(rr[cfg['name']],.05,8,24,ee[cfg['name']],1.5,panel,min_adjustment=3000)
 stress=g.bt.metrics(c,100000);(out/'stress.json').write_text(json.dumps(stress,indent=2),encoding='utf-8')
 snapshot=g.HERE/'pending_1_snapshot'
 hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in snapshot.iterdir() if p.is_file() and p.name!='sha256.json'}
 (snapshot/'sha256.json').write_text(json.dumps(hashes,indent=2,ensure_ascii=False),encoding='utf-8')
 lines=['# 基准2待定1留档与第三轮研究','', 'G02 顺势防守8已按用户要求保存为“基准2待定1”；原基准未覆盖。规则登记在 pending_1.json，源代码与净值、成交快照在 pending_1_snapshot，附SHA256校验。快照用于留档，不是独立可运行数据包。', '',
 '## 研究范围','', '10个方向、20个变体，加1个待定1对照：60/200日市场信号、涨跌家数比例、双指数确认、均线切换缓冲、不同防守分组、温度历史分位、风险配权、极端波动过滤、调仓频率及仓位控制。原有选股评分内部的120日状态机制保留，新的信号控制原选股与防守选股之间的切换。', '',
 '10万元，2020-01-02至2026-09-11。按2020—2023开发评分筛选，后续历史仅展示；历史已多次观察，并非独立样本外。', '',
 '|路线|年化|最大回撤|Sharpe|佣金元|年双边换手倍数|','|---|---:|---:|---:|---:|---:|']
 for n,label in labels.items():
  z=r[r.name==n].iloc[0];lines.append(f'|{label}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.full_sharpe:.3f}|{z.commission:.0f}|{z.annual_two_sided_turnover:.2f}|')
 z=r[r.name=='temperature_0.3'].iloc[0]
 lines+=['','没有版本同时超过待定1三项全期指标，本轮不替换待定1，也不自动新增待定编号。', '',
 '温度过滤：在中证500高于120日均线的基础上，中盘组过去60日收益中位数还需不处于已观察月度温度的最低30%，才使用原策略，否则防守。仅在季度信号时决策。温度不是估值。', '',
 f'温度版本开发年化{z.dev_annualized_return:.2%}，2024年化{z.validation_annualized_return:.2%}，2025后年化{z.observed_annualized_return:.2%}。佣金与滑点加倍后年化{stress["annualized_return"]:.2%}，最大回撤{abs(stress["max_drawdown"]):.2%}，Sharpe {stress["sharpe"]:.3f}。', '',
 '仓位版本在强市目标95%、弱市65%；其全期年化更高、回撤略低，但Sharpe下降，且开发期评分不领先，只列为观察项。仓位仅在调仓时调整。', '',
 '月度/双月版本表现下降不能全归因为手续费：持仓路径和换股次数也改变。极端波动过滤两个版本与待定1净值完全相同，说明过滤没有改变实际交易；21项配置并非21条独立有效策略。', '',
 '信号先于成交、现金非负、100股买入、无同日往返检查通过。仍沿用固定股票池、代理基本面、近似公司行动和不完整历史费率：佣金万三最低5元，双边0.2%滑点，卖出税率固定0.1%，未单列过户费。未在平台复核，不代表实盘预期。']
 (out/'结论.md').write_text('\n'.join(lines),encoding='utf-8')
 print(r[r.name.isin(labels)][['name','full_annualized_return','full_max_drawdown','full_sharpe','commission','annual_two_sided_turnover']].to_string(index=False));print('STRESS',stress)

if __name__=='__main__':main()
