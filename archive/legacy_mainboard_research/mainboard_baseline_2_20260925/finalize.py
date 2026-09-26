from pathlib import Path
import json, hashlib, ast
import pandas as pd
import research as r
import build_platform
import execution_engine

def main():
 h=r.HERE;o=r.OUT
 r.bt=execution_engine
 a=pd.read_csv(o/'results.csv');b=pd.read_csv(o/'round2/results.csv')
 all_results=pd.concat([a,b],ignore_index=True)
 selected=all_results[(all_results.name!='reference')&(all_results.name!='fixed_quality_pool')&(all_results.dev_max_drawdown>=-.30)].sort_values('selection_score',ascending=False).iloc[0]
 assert selected['name']=='deep_reversal_20_0.8'
 conf={'name':'deep_reversal_20_0.8','family':'deep_reversal','bull':[.25,.2,.55],'bear':[.65,.25,.1], 'count':20,'buffer':40,'exposure':.8,'initial_cash':10000000,'selection':'Exploratory defensive objective introduced after first two rounds; dev MDD <=30%, maximize existing development score','status':'local research baseline; platform unverified'}
 (h/'frozen.json').write_text(json.dumps(conf,ensure_ascii=False,indent=2),encoding='utf-8')
 f=r.bt.build_factor_cache();ranks=r.bt.ranked_months(f,tuple(conf['bull']),tuple(conf['bear']),120)
 curve,trade=r.bt.simulate(ranks,.05,20,40,.8,1.5)
 curve.to_csv(o/'baseline2_daily_equity.csv',index=False,encoding='utf-8-sig')
 trade.to_csv(o/'baseline2_trades.csv',index=False,encoding='utf-8-sig')
 ref_curve,_=r.bt.simulate(r.bt.ranked_months(f,(.25,.2,.55),(.5,.25,.25),120),.05,20,40,1.,1.5)
 ref_curve.to_csv(o/'reference_daily_equity.csv',index=False,encoding='utf-8-sig')
 win=b[b.name==conf['name']].iloc[0];ref=a[a.name=='reference'].iloc[0]
 for row,cr in [(win,curve),(ref,ref_curve)]:
  for label,s,e in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   for k,v in r.measure(cr,s,e).items():
    if label+'_'+k in row.index:row[label+'_'+k]=v
 pd.DataFrame([ref,win]).to_csv(o/'corrected_comparison.csv',index=False,encoding='utf-8-sig')
 build_platform.main()
 t=pd.read_csv(o/'baseline2_trades.csv',parse_dates=['date'])
 c=pd.read_csv(o/'baseline2_daily_equity.csv',parse_dates=['date'])
 reference=pd.read_csv(o/'reference_daily_equity.csv',parse_dates=['date'])
 audit={'trade_rows':len(t),'negative_cash_days':int((c.cash < -.01).sum()),
 'forbidden_symbols':int((~t.symbol.map(r.bt.is_ordinary_mainboard_a)).sum()),
 'buy_lot_errors':int((t[t.side=='BUY'].quantity%100!=0).sum()),
 'same_day_buy_sell_pairs':int(len(t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']))),
 'selection_uses_observed_period':False}
 assert not any(audit[k] for k in ['negative_cash_days','forbidden_symbols','buy_lot_errors','same_day_buy_sell_pairs'])
 returns=c.set_index('date').equity.pct_change().to_frame('baseline2').join(reference.set_index('date').equity.pct_change().rename('baseline1'))
 audit['return_correlation']=float(returns.corr().iloc[0,1])
 (o/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
 tables=pd.concat([a,b],ignore_index=True);tables.to_csv(o/'all_31_routes.csv',index=False,encoding='utf-8-sig')
 lines=['# 沪深基准2：八成反转','',f"冻结结构：{conf['name']}；初始资金1000万元，2020-01-02—2026-09-11。",'',
 '|指标|基准1|基准2|','|---|---:|---:|']
 for title,key in [('全期年化','full_annualized_return'),('最大回撤','full_max_drawdown'),('开发期年化','dev_annualized_return'),('2024年化','validation_annualized_return'),('2025后年化','observed_annualized_return')]:lines.append(f'|{title}|{ref[key]:.2%}|{win[key]:.2%}|')
 lines.extend([f"|Sharpe|{ref.full_sharpe:.3f}|{win.full_sharpe:.3f}|",f"|期末资产|{ref.full_final_equity/10000:.2f}万元|{win.full_final_equity/10000:.2f}万元|",'',
 '## 冻结规则','',f"强市因子：低成交额/接近高点/分红代理权重={conf['bull']}；弱市：远离高点/低于均线/分红代理={conf['bear']}。",f"持股{conf['count']}只，排名缓冲{conf['buffer']}只，总仓位{conf['exposure']:.0%}。按下行波动率倒数分配，单股上限为等权的1.5倍。中证500的120日均线区分强弱。",'',
 '## 验证与限制','',
 '共31条路线（含基准1）。初始收益优先方案未超过基准1；看过两轮结果后，将基准2定位为防守对照，开发期回撤上限改为30%，在符合条件者中按原开发期评分选择。该目标调整属于探索，不能声称预注册或全新样本外。2024与2025后没有进入数值评分，但研究者已看到其表现。',
 f"成交审计：{audit}。",'引擎继承基准1平台校准口径：T日信号、下个交易日开盘；佣金万三最低5元，双边0.2%滑点、卖出印花税固定0.1%、100股、5%全天成交量约束、封板与停牌过滤。税率固定用于比较，不代表各历史日期法定税率；没有另行模拟过户费。',
 '公司行动为近似重建，分红因子为复权变化代理；初始股票池仍可能有幸存者偏差。日量参与上限不等于开盘可成交容量。当前行业分类不能回填当作历史行业。',
 'SuperMind文件已生成并语法检查，尚未在平台验证。此版本登记为本地研究基准2，不代表已证实未来收益或已战胜基准1。', '',
 '运行round2.py可复跑第二轮，finalize.py生成冻结平台版与报告。第一轮research.py会重写候选冻结文件，复跑全流程需依次执行research.py、round2.py、finalize.py。'])
 (h/'README.md').write_text('\n'.join(lines),encoding='utf-8')
 files=[h/'research.py',h/'round2.py',h/'supermind_mainboard_baseline_2.py',o/'baseline2_daily_equity.csv',o/'baseline2_trades.csv']
 (h/'manifest.json').write_text(json.dumps({str(p.relative_to(h)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2),encoding='utf-8')
 print(win.to_string());print(audit)

if __name__=='__main__':main()
