"""Ungrouped controls isolate grouping effects from stock-scoring changes."""
import json
import pandas as pd
import group_research as g

def main():
 g.bt.INITIAL_CASH=100000.
 f=g.features(); days={d:q for d,q in f.groupby('execute_date') if d.month in [1,4,7,10]}
 ranks={method:{d:g.score(q,method) for d,q in days.items()} for method in g.METHODS}
 union=set(s for rr in ranks.values() for q in rr.values() for s in q.head(30).symbol)
 panel=g.bt.load_daily_panel(union);rows=[]
 for method,rr in ranks.items():
  c,t=g.bt.simulate(rr,.05,10,30,.8,1.5,panel,min_adjustment=3000)
  row={'name':'ungrouped_'+method,'method':method}
  for label,start,end in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   z=c[c.date.between(start,end)];prev=c[c.date<pd.Timestamp(start)]
   for k,v in g.bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else 100000).items():row[label+'_'+k]=v
  row.update(orders=len(t),commission=float(t.commission.sum()),stamp_tax=float(t.stamp_tax.sum()))
  rows.append(row)
  c.to_csv(g.OUT/('control_'+method+'_equity.csv'),index=False)
  t.to_csv(g.OUT/('control_'+method+'_trades.csv'),index=False)
 pd.DataFrame(rows).to_csv(g.OUT/'controls.csv',index=False)
 print(json.dumps(rows,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
