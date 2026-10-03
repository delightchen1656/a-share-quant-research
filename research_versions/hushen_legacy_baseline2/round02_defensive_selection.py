from pathlib import Path
import json
import pandas as pd
import research as r
bt=r.bt
OUT=r.OUT/'round2'

def main():
 OUT.mkdir(parents=True,exist_ok=True); f=bt.build_factor_cache(); configs=[]; ranks={}; union=set()
 for name,bull,bear in [
  ('quality_reversal',(.1,.1,.8),(.3,.2,.5)),
  ('balanced',(.2,.3,.5),(.35,.35,.3)),
  ('strong_quality',(.0,.35,.65),(.45,.15,.4)),
  ('patient_value',(.4,0,.6),(.3,.1,.6)),
  ('deep_reversal',(.25,.2,.55),(.65,.25,.1)),
  ('quality_anchor',(.0,.1,.9),(.2,.1,.7))]:
  ranks[name]=bt.ranked_months(f,bull,bear,120)
  for count,exp in [(20,1.),(30,1.),(20,.8)]:
   configs.append({'name':name+'_'+str(count)+'_'+str(exp),'family':name,'bull':bull,'bear':bear,'count':count,'buffer':count*2,'exposure':exp})
  for q in ranks[name].values():union.update(q.head(60).symbol)
 panel=bt.load_daily_panel(union); rows=[]; curves={}; trades={}
 for conf in configs:
  n=conf['name'];print(n,flush=True)
  c,t=bt.simulate(ranks[conf['family']],.05,conf['count'],conf['buffer'],conf['exposure'],1.5,panel)
  row={'name':n}
  for label,s,e in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   m=r.measure(c,s,e)
   for key in ['annualized_return','max_drawdown','sharpe','final_equity']:row[label+'_'+key]=m[key]
  row['eligible']=row['dev_max_drawdown']>=-.35
  row['selection_score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
  rows.append(row);curves[n]=c;trades[n]=t
  pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
 result=pd.DataFrame(rows); win=result[result.eligible].sort_values('selection_score',ascending=False).iloc[0]
 conf=next(v for v in configs if v['name']==win['name'])
 conf.update({'selection':'2020-2023 only; same score as round1','initial_cash':10000000,'status':'local research baseline; platform unverified'})
 (r.HERE/'frozen.json').write_text(json.dumps(conf,ensure_ascii=False,indent=2),encoding='utf-8')
 curves[win['name']].to_csv(r.OUT/'baseline2_daily_equity.csv',index=False,encoding='utf-8-sig')
 trades[win['name']].to_csv(r.OUT/'baseline2_trades.csv',index=False,encoding='utf-8-sig')
 pd.concat([c.assign(strategy=n) for n,c in curves.items()]).to_parquet(OUT/'all_curves.parquet',index=False)
 print('WINNER',conf,flush=True);print(result.to_string(index=False),flush=True)

if __name__=='__main__':main()
