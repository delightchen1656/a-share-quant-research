"""Independent baseline calibration gate. Never use exported holdings as signals."""
import json
import numpy as np
import pandas as pd
import group_research as g
from group_round3 import prepare
HERE=g.HERE;OUT=HERE/'approximate_parity_100k'
EXPORT=HERE/'platform_runs/supermind_20200102_20260918_100k'
LIMITS={'final_equity_relative':.05,'p95_daily_equity_relative':.10,'max_daily_equity_relative':.15,'annualized_return_gap':.02,'max_drawdown_gap':.03,'daily_return_correlation_min':.90,'each_stage_return_annualized_gap':.04}

def compare(c,p):
 x=c.merge(p[['date','equity']],on='date',suffixes=('_local','_platform')).sort_values('date')
 e=x.equity_local/x.equity_platform-1
 years=(x.date.iloc[-1]-x.date.iloc[0]).days/365.25
 annualgap=abs((x.equity_local.iloc[-1]/100000)**(1/years)-(x.equity_platform.iloc[-1]/100000)**(1/years))
 ddgap=abs((x.equity_local/x.equity_local.cummax()-1).min()-(x.equity_platform/x.equity_platform.cummax()-1).min())
 stages=[]
 for start,end in [('2020-01-02','2023-12-31'),('2024-01-01','2024-12-31'),('2025-01-01','2026-09-11')]:
  z=x[x.date.between(start,end)];prev=x[x.date<pd.Timestamp(start)];yy=(z.date.iloc[-1]-z.date.iloc[0]).days/365.25
  initials=[float(prev['equity_'+s].iloc[-1]) if len(prev) else 100000 for s in ['local','platform']]
  annuals=[float((z['equity_'+s].iloc[-1]/i)**(1/yy)-1) for s,i in zip(['local','platform'],initials)]
  stages.append(dict(start=start,end=end,local_annualized=annuals[0],platform_annualized=annuals[1],gap=abs(annuals[0]-annuals[1])))
 result=dict(final_equity_relative=float(abs(e.iloc[-1])),p95_daily_equity_relative=float(e.abs().quantile(.95)),max_daily_equity_relative=float(e.abs().max()),annualized_return_gap=float(annualgap),max_drawdown_gap=float(ddgap),daily_return_correlation_min=float(x.equity_local.pct_change().corr(x.equity_platform.pct_change())),each_stage_return_annualized_gap=max(s['gap'] for s in stages),stages=stages)
 result['passed']=all(result[k]>=v if k.endswith('_min') else result[k]<=v for k,v in LIMITS.items())
 return result,x

def main():
 OUT.mkdir(exist_ok=True)
 (OUT/'protocol.json').write_text(json.dumps({'limits':LIMITS,'models':['original','include_small_corporate_actions','include_small_actions_and_early_sample_execution_proxy'],'principles':['Thresholds before corrected runs. No modification of stock ranking parameters. No platform realized holdings, fills, cash balances or future close substituted in simulations.','Execution proxy estimate uses median signed deviation in 2020-2023 matched trade keys only, then held constant. 2024 onward is audit, although already historically viewed.','Only proceed to parameter optimization if gate passes; no moving tolerance after results. This is approximate parity not statistical assurance.']},indent=2),encoding='utf-8')
 g.bt.INITIAL_CASH=100000.
 f=g.features();rr,_,_,union=prepare(f,[dict(name='control',family='control',value=0)])
 panel=g.bt.load_daily_panel(union);p=pd.read_csv(EXPORT/'platform_daily_equity.csv',parse_dates=['date'])
 original_action=g.bt.apply_corporate_action;original_slip=g.bt.SLIPPAGE
 def smaller_actions(cash,positions,day,previous_close):
  # Fix inherited 2% cutoff only; retain split approximation transparently.
  cash=original_action(cash,positions,day,previous_close)
  for s,qty in positions.items():
   if s not in day.index or s not in previous_close:continue
   pre=float(day.loc[s,'preclose']);old=float(previous_close[s])
   if not np.isfinite(pre) or pre<=0:continue
   ratio=old/pre
   if 1+1e-8<ratio<=1.02:cash+=qty*(old-pre)
  return cash
 prices=pd.read_csv(EXPORT/'trade_price_alignment.csv',parse_dates=['date'])
 prices=prices[(prices.date<'2024-01-01')&prices.open.notna()&(prices.open>0)].copy()
 prices['signed_gap']=(prices.effective_price/prices.open-1)*np.where(prices.side=='BUY',1,-1)
 # The estimate is for friction, never allow a negative-cost advantage.
 estimated=float(max(0,prices.signed_gap.median()))
 rows=[]
 for model in ['original','include_small_corporate_actions','include_small_actions_and_early_sample_execution_proxy']:
  g.bt.apply_corporate_action=original_action if model=='original' else smaller_actions
  g.bt.SLIPPAGE=estimated if model.endswith('proxy') else original_slip
  c,t=g.bt.simulate(rr['control'],.05,8,24,.8,1.5,panel,min_adjustment=3000)
  if model=='original':
   frozen=pd.read_csv(HERE/'pending_1_snapshot/defensive_bear_8_equity.csv');assert np.allclose(c.equity,frozen.equity,rtol=0,atol=.01)
  result,x=compare(c,p);result['model']=model;result['slippage']=g.bt.SLIPPAGE;result['local_metrics']=g.bt.metrics(c,100000);rows.append(result)
  c.to_csv(OUT/(model+'_equity.csv'),index=False);t.to_csv(OUT/(model+'_trades.csv'),index=False);x.to_csv(OUT/(model+'_comparison.csv'),index=False)
 g.bt.apply_corporate_action=original_action;g.bt.SLIPPAGE=original_slip
 (OUT/'results.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
 print(json.dumps(rows,indent=2))

if __name__=='__main__':main()
