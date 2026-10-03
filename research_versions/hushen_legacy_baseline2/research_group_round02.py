"""Second exploratory batch: retain baseline alpha, add group preferences."""
import json
import numpy as np
import pandas as pd
import group_research as g

OUT=g.HERE/'group_round2_100k'
def main():
 OUT.mkdir(exist_ok=True);g.bt.INITIAL_CASH=100000.
 f=g.features();base=g.bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
 groups={'midcap':('float_cap_proxy',1),'lowvol':('vol60',0),'midamount':('amount20',1)}
 cs=[dict(name='control',mode='base',count=10,exposure=.8)]
 for key in groups:
  cs.append(dict(name='restrict_'+key,mode='restrict',group=key,count=10,exposure=.8))
  for bonus in [.05,.15,.30]:cs.append(dict(name=f'bonus_{key}_{bonus}',mode='bonus',group=key,bonus=bonus,count=10,exposure=.8))
 for a in [.2,.4,.6]:
  for n in [8,10,12]:cs.append(dict(name=f'blend_{a}_{n}',mode='blend',alpha=a,count=n,exposure=.8))
 for direction in ['defensive_bear','defensive_bull']:
  for n in [8,10,12]:cs.append(dict(name=f'{direction}_{n}',mode=direction,count=n,exposure=.8))
 for n in [8,10,12]:
  for exposure in [.8,.95]:cs.append(dict(name=f'group_{n}_{exposure}',mode='group',count=n,exposure=exposure))
 for dim in ['float_cap_proxy','vol60','turn20']:
  for preference in ['cool','middle']:cs.append(dict(name=f'temperature_{dim}_{preference}',mode='temperature',dim=dim,preference=preference,count=10,exposure=.8))
 protocol={'configs':cs,'selection':'2020-2023 CAGR + .05 Sharpe -.5 abs(MDD); dev MDD<=35%; later periods descriptive only','capital':100000,'cadence':'quarterly','min_adjustment':3000,'warning':'Second batch informed by previously viewed history; not clean out-of-sample. Inherited universe, corporate action and cost limitations remain. Temperature means trailing 60-day median return, not fundamental valuation.'}
 (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
 idx=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet');idx['date']=pd.to_datetime(idx.date)
 idx=idx.sort_values('date');allranks={};union=set()
 for cfg in cs:
  rr={}
  for d,x in base.items():
   if d.month not in [1,4,7,10]:continue
   q=x.copy();mode=cfg['mode']
   if mode in ['restrict','bonus']:
    dim,grp=groups[cfg['group']];mask=q[dim+'_group']==grp
    if mode=='restrict':q=q[mask]
    else:q['score']+=cfg['bonus']*mask
   if mode in ['blend','group','defensive_bear','defensive_bull']:
    defensive=g.score(q[q.float_cap_proxy_group==1],'quality')
    # Group score percentiles compete with baseline ranks, no return-curve mixing.
    if mode=='blend':
     ds=defensive.set_index('symbol').score.rank(pct=True)
     q['score']=(1-cfg['alpha'])*q.score.rank(pct=True)+cfg['alpha']*q.symbol.map(ds).fillna(0)
    elif mode=='group':q=defensive
    else:
     hist=idx[idx.date<=q.signal_date.iloc[0]].tail(120)
     bull=bool(hist.close.iloc[-1]>hist.close.mean())
     if (mode=='defensive_bear' and not bull) or (mode=='defensive_bull' and bull):q=defensive
   if mode=='temperature':
    dim=cfg['dim'];temps=q[q[dim+'_group']>=0].groupby(dim+'_group').ret60.median().sort_values()
    pick=temps.index[0 if cfg['preference']=='cool' else len(temps)//2]
    q['score']+=.15*(q[dim+'_group']==pick)
   q=q.sort_values(['score','symbol'],ascending=[False,True]) if mode!='base' else q
   rr[d]=q;union.update(q.head(3*cfg['count']).symbol)
  allranks[cfg['name']]=rr
 panel=g.bt.load_daily_panel(union);rows=[];best=-np.inf
 for i,cfg in enumerate(cs,1):
  print('RUN',i,len(cs),cfg['name'],flush=True)
  c,t=g.bt.simulate(allranks[cfg['name']],.05,cfg['count'],3*cfg['count'],cfg['exposure'],1.5,panel,min_adjustment=3000)
  if cfg['mode']=='base':
   prior=pd.read_csv(g.HERE/'small_account_100k/daily_equity.csv')
   assert np.allclose(c.equity,prior.equity,atol=.01,rtol=0),'Control does not reproduce baseline'
  row=dict(cfg)
  for tag,start,end in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   z=c[c.date.between(start,end)];prev=c[c.date<pd.Timestamp(start)]
   for k,v in g.bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else 100000).items():row[tag+'_'+k]=v
  row.update(commission=float(t.commission.sum()),stamp_tax=float(t.stamp_tax.sum()),orders=len(t))
  row['score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
  rows.append(row)
  c.to_csv(OUT/(cfg['name']+'_equity.csv'),index=False)
  t.to_csv(OUT/(cfg['name']+'_trades.csv'),index=False)
  pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
  if cfg['mode']!='base' and row['dev_max_drawdown']>=-.35 and row['score']>best:
   best=row['score'];(OUT/'candidate.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
 r=pd.DataFrame(rows);ref=r.iloc[0]
 r['full_dominates_control']=(r.full_annualized_return>ref.full_annualized_return)&(r.full_sharpe>ref.full_sharpe)&(r.full_max_drawdown>ref.full_max_drawdown)
 r.to_csv(OUT/'results.csv',index=False,encoding='utf-8-sig')
 print(r.sort_values('score',ascending=False)[['name','full_annualized_return','full_max_drawdown','full_sharpe','validation_annualized_return','observed_annualized_return','full_dominates_control']].to_string(index=False),flush=True)

if __name__=='__main__':main()
