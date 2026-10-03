"""100k capital: choose holding count and cost controls on development data."""
import json, ast
from pathlib import Path
import pandas as pd
import execution_engine as bt
HERE=Path(__file__).resolve().parent
OUT=HERE/'small_account_100k'

def metrics(c,start,end):
 z=c[c.date.between(start,end)];prev=c[c.date<pd.Timestamp(start)]
 return bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else bt.INITIAL_CASH)

def main():
 OUT.mkdir(exist_ok=True);bt.INITIAL_CASH=100000.
 f=bt.build_factor_cache();ranks=bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
 configs=[dict(name='reference20',count=20,buffer=40,months=1,min_adjustment=0)]
 for n in [5,8,10,12]:
  for months in [1,3]:
   for minimum in [0,3000]:
    configs.append(dict(name=f'n{n}_m{months}_min{minimum}',count=n,buffer=3*n,months=months,min_adjustment=minimum))
 universe=set()
 for q in ranks.values():universe.update(q.head(40).symbol)
 panel=bt.load_daily_panel(universe);rows=[];curves={};trades={}
 for cfg in configs:
  print(cfg['name'],flush=True)
  rr={d:q for d,q in ranks.items() if cfg['months']==1 or d.month in [1,4,7,10]}
  c,t=bt.simulate(rr,.05,cfg['count'],cfg['buffer'],.8,1.5,panel,min_adjustment=cfg['min_adjustment'])
  row=dict(cfg)
  for tag,s,e in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   for k,v in metrics(c,s,e).items():row[tag+'_'+k]=v
  years=(c.date.iloc[-1]-c.date.iloc[0]).days/365.25
  row.update(orders=len(t),commission=t.commission.sum(),stamp_tax=t.stamp_tax.sum(),min_fee_orders=int((t.commission<=5.000001).sum()),average_cash_fraction=(c.cash/c.equity).mean())
  # Turnover uses equity on each trading day, not initial capital.
  day_values=t.groupby('date').amount.sum()
  row['annual_turnover']=(day_values/c.set_index('date').equity.reindex(day_values.index)).sum()/years
  row['score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
  rows.append(row);curves[cfg['name']]=c;trades[cfg['name']]=t
  pd.DataFrame(rows).to_csv(OUT/'comparison.csv',index=False,encoding='utf-8-sig')
 result=pd.DataFrame(rows);cand=result[(result.name!='reference20')&(result.dev_max_drawdown>=-.35)]
 if cand.empty:raise RuntimeError('No reduced-holding candidate within development drawdown budget')
 win=cand.sort_values('score',ascending=False).iloc[0];name=win['name']
 cfg=next(q for q in configs if q['name']==name)
 (OUT/'frozen.json').write_text(json.dumps(dict(cfg,initial_cash=100000,exposure=.8,selection='2020-2023 net CAGR + .05 Sharpe - .5 abs(MDD); MDD <=35%; historical exploration'),ensure_ascii=False,indent=2),encoding='utf-8')
 c,t=curves[name],trades[name]
 c.to_csv(OUT/'daily_equity.csv',index=False,encoding='utf-8-sig');t.to_csv(OUT/'trades.csv',index=False,encoding='utf-8-sig')
 assert (c.cash>=-.01).all() and (t.loc[t.side=='BUY','quantity']%100==0).all()
 assert t[t.side=='BUY'].merge(t[t.side=='SELL'],on=['date','symbol']).empty
 src=(HERE/'supermind_mainboard_baseline_2.py').read_text(encoding='utf-8')
 src=src.replace('TARGET_COUNT = 20',f"TARGET_COUNT = {cfg['count']}").replace('BUFFER_COUNT = 40',f"BUFFER_COUNT = {cfg['buffer']}")
 if cfg['months']==3:
  src=src.replace('    if _is_first_session_of_month(today):','    if _is_first_session_of_month(today) and today.month in (1, 4, 7, 10):')
 if cfg['min_adjustment']:
  marker='        if tradable and not locked_down:\n            order_target_percent(symbol, target)'
  assert marker in src
  replacement='''        # Skip small adjustments to existing positions; full exits remain active.
        price = float(bar_dict[symbol].open)
        value = float(positions[symbol].amount) * price
        equity = float(context.portfolio.stock_account.total_value)
        if target > 0 and abs(equity * target - value) < 3000:
            continue
        if tradable and not locked_down:
            order_target_percent(symbol, target)'''
  src=src.replace(marker,replacement)
 src='# 10万元版本：请在平台回测设置初始资金100000元。\n'+src
 ast.parse(src);(OUT/'supermind_baseline2_100k.py').write_text(src,encoding='utf-8')
 lines=['# 沪深基准2：10万元账户','',f"选定：{name}，目标持有{cfg['count']}只，排名缓冲{cfg['buffer']}只，每{cfg['months']}个月调仓，已有仓位小于{cfg['min_adjustment']}元的调整跳过，清仓不受此门槛限制。80%目标仓位。",'',
 '|配置|年化|回撤|Sharpe|期末万元|订单|累计佣金元|年换手|','|---|---:|---:|---:|---:|---:|---:|---:|']
 for x in result.itertuples():lines.append(f'|{x.name}|{x.full_annualized_return:.2%}|{x.full_max_drawdown:.2%}|{x.full_sharpe:.3f}|{x.full_final_equity/10000:.2f}|{x.orders}|{x.commission:.0f}|{x.annual_turnover:.2f}|')
 lines+=['','选择仅使用2020—2023的扣费后开发指标；2024和2025后仅观察，但这些历史已反复研究，不是全新样本外。',
 '费用沿用同一比较口径：佣金万三、最低5元、买卖各0.2%滑点，卖出印花税固定0.1%（比较假设，不是完整历史税率），未单列过户费。停牌/封板、100股买入、5%日成交量约束。原引擎公司行动近似和固定股票池偏差仍存在。',
 '平台文件已生成并通过语法检查，尚未平台实测；实际残留持仓可能超过目标只数。',
 f"选定配置开发期年化{win.dev_annualized_return:.2%}、2024年化{win.validation_annualized_return:.2%}、2025后年化{win.observed_annualized_return:.2%}。"]
 (OUT/'README.md').write_text('\n'.join(lines),encoding='utf-8')
 print('WINNER',win.to_string(),flush=True);print(result[['name','full_annualized_return','full_max_drawdown','commission','orders']].to_string(index=False),flush=True)

if __name__=='__main__':main()
