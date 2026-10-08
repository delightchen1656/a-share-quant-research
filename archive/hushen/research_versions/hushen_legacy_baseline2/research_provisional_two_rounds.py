"""Two bounded rounds, provisional local model only, not a parity pass."""
import json
import numpy as np
import pandas as pd
import moderate_tuning as m
g=m.g;OUT=g.HERE/'provisional_two_rounds_100k'

def main():
 OUT.mkdir(exist_ok=True);g.bt.INITIAL_CASH=100000.
 original=g.bt.apply_corporate_action
 def action(cash,positions,day,previous):
  cash=original(cash,positions,day,previous)
  for s,qty in positions.items():
   if s not in day.index or s not in previous:continue
   pre=float(day.loc[s,'preclose']);old=float(previous[s])
   if np.isfinite(pre) and pre>0 and 1+1e-8<old/pre<=1.02:cash+=qty*(old-pre)
  return cash
 g.bt.apply_corporate_action=action
 cs=[dict(m.DEFAULT,name='corrected_control',round=0)]
 for exp in [.75,.85]:
  for vol in [.05,.06]:cs.append(dict(m.DEFAULT,name=f'risk_{exp}_{vol}',exposure=exp,vol_ceiling=vol,round=1))
 for buf in [20,28]:
  for minimum in [2500,3500]:cs.append(dict(m.DEFAULT,name=f'execution_{buf}_{minimum}',buffer=buf,minimum=minimum,round=1))
 perturbations={'risk_power':[.8,1.2],'ma':[105,135],'count':[7,9]}
 protocol={'stage1':cs,'stage2_perturbations':perturbations,'selection':'Stage1 dev score=max(weaker 2-year CAGR+.05devSharpe-.5abs(devMDD)); require devCAGR>=95%control and abs(devMDD)<=105%control. Stage2 only diagnoses chosen center; never chooses a neighbor. Stable if at least 4 of 6 neighbors score>=95%control and both dev subperiods profitable. Compare same corrected engine.','scope':'User requested continued work: provisional research despite failed parity gate. Not platform-calibrated; do not replace pending1. All later history already viewed, not pristine OOS. No additional rounds after these.'}
 (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
 f=m.extra_features(g.features());rows=[];curves={};rankcache={}
 def run(cfg):
  name=cfg['name'];print('RUN',name,flush=True);rr=m.ranks(f,cfg);rankcache[name]=rr
  c,t=g.bt.simulate(rr,.05,cfg['count'],cfg['buffer'],cfg['exposure'],cfg['cap'],min_adjustment=cfg['minimum'])
  assert (c.cash>=-.01).all() and (t[t.side=='BUY'].quantity%100==0).all()
  assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
  if name=='corrected_control':
   prev=pd.read_csv(g.HERE/'approximate_parity_100k/include_small_corporate_actions_equity.csv')
   assert np.allclose(c.equity,prev.equity,atol=.01,rtol=0)
  row=dict(cfg,**m.measure(c),commission=float(t.commission.sum()),orders=len(t));rows.append(row);curves[name]=c
  c.to_csv(OUT/(name+'_equity.csv'),index=False);t.to_csv(OUT/(name+'_trades.csv'),index=False)
  pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False)
 for cfg in cs:run(cfg)
 r=pd.DataFrame(rows);ref=r.iloc[0]
 eligible=r[(r.dev_annualized_return>=.95*ref.dev_annualized_return)&(r.dev_max_drawdown>=1.05*ref.dev_max_drawdown)]
 win=eligible.sort_values('robust_score',ascending=False).iloc[0]
 center=next(c for c in cs if c['name']==win['name'])
 for key,values in perturbations.items():
  for v in values:
   cfg=dict(center,**{key:v});cfg.update(name=f'neighbor_{key}_{v}',round=2);cs.append(cfg);run(cfg)
 r=pd.DataFrame(rows);neighbors=r[r['round']==2]
 stable=(neighbors.robust_score>=.95*ref.robust_score)&(neighbors.early_annualized_return>0)&(neighbors.late_annualized_return>0)
 decision=dict(center=center,stable_neighbors=int(stable.sum()),required=4,stability_passed=bool(stable.sum()>=4),status='provisional_not_promoted',platform_parity='failed')
 (OUT/'decision.json').write_text(json.dumps(decision,indent=2),encoding='utf-8')
 stress=[];g.bt.SLIPPAGE=.004;g.bt.COMMISSION=.0006;g.bt.MIN_COMMISSION=10.
 for name in dict.fromkeys(['corrected_control',center['name']]):
  cfg=next(c for c in cs if c['name']==name);rr=rankcache[name]
  c,t=g.bt.simulate(rr,.05,cfg['count'],cfg['buffer'],cfg['exposure'],cfg['cap'],min_adjustment=cfg['minimum'])
  stress.append(dict(name=name,**m.measure(c)))
 pd.DataFrame(stress).to_csv(OUT/'stress.csv',index=False)
 lines=['# 两轮有限优化：仅本地研究','', '平台近似对齐未通过。应用户继续研究要求，本轮使用小额除权修正后的本地模型，所有方案在同一引擎下比较，不改待定1、不发布平台升级版。10万元，2020-01-02至2026-09-11。', '',
 '第一轮8个粗组合加原版对照；第二轮只检查第一轮开发期候选的6个邻域，不从邻域重新选赢家。预先限定两轮，不继续追逐全期高收益。', '',
 '|方案|年化|最大回撤|Sharpe|开发年化|2024年化|2025后年化|佣金元|','|---|---:|---:|---:|---:|---:|---:|---:|']
 for name in dict.fromkeys(['corrected_control',center['name'],'execution_28_2500']):
  z=r[r.name==name].iloc[0];lines.append(f'|{name}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.full_sharpe:.3f}|{z.dev_annualized_return:.2%}|{z.year2024_annualized_return:.2%}|{z.recent_annualized_return:.2%}|{z.commission:.0f}|')
 lines+=['',f"候选邻域通过{int(stable.sum())}/6项（预设至少4项）。邻域要求开发期评分至少为原版95%，且两个两年开发分段都盈利。这不是统计显著性保证。", '',
 '## 费用加倍','', '|方案|年化|最大回撤|Sharpe|','|---|---:|---:|---:|']
 for z in stress:lines.append(f"|{z['name']}|{z['full_annualized_return']:.2%}|{abs(z['full_max_drawdown']):.2%}|{z['full_sharpe']:.3f}|")
 lines+=['','## 邻域检查（不重新选参）','', '|参数变化|全期年化|回撤|开发稳健评分|','|---|---:|---:|---:|']
 for z in neighbors.itertuples():lines.append(f'|{z.name}|{z.full_annualized_return:.2%}|{abs(z.full_max_drawdown):.2%}|{z.robust_score:.4f}|')
 lines+=['','候选配置：'+json.dumps(center,ensure_ascii=False), '',
 '基础成本：佣金万三最低5元、双边滑点0.2%、卖出税率固定0.1%，未单列过户费。压力情景加倍佣金和滑点、不改变税率。股票池和代理因子偏差、送转近似仍在，历史已反复观察，不能称为样本外。参数选择只读取开发期指标，后期与全期指标仅报告。', '',
 '旧报告23.79%为未修正公司行动的待定1，本轮对照为修正后版本，两者差别不是调参收益。即使本地有所提高，也不代表与平台差距变小；本轮未声称新参数通过平台对齐门槛。']
 (OUT/'两轮优化结论.md').write_text('\n'.join(lines),encoding='utf-8')
 print('DECISION',decision);print(r[['name','full_annualized_return','full_max_drawdown','full_sharpe','robust_score']].to_string(index=False));print('STRESS',stress)

if __name__=='__main__':main()
