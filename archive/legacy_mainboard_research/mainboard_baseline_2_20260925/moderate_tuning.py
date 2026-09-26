"""Predeclared coarse one-at-a-time sensitivity; no Cartesian search."""
import json
import numpy as np
import pandas as pd
import group_research as g
OUT=g.HERE/'moderate_tuning_100k'
DEFAULT=dict(count=8,buffer=24,exposure=.8,minimum=3000,cap=1.5,ma=120,band=[1/3,2/3],bull=[.25,.2,.55],defense=[.55,.3,.15],risk_floor=.002,risk_power=1.,cadence=3,amount_floor=50000000.,vol_ceiling=.08,weight_window=20,high_window=120,turn_window=20)
VARIANTS=dict(count=[6,10],buffer=[16,32],exposure=[.7,.9],minimum=[2000,4000],cap=[1.25,1.75],ma=[90,150],band=[[.25,.75],[.4,.6]],bull=[[.35,.2,.45],[.15,.2,.65]],defense=[[.45,.4,.15],[.65,.2,.15]],risk_floor=[.001,.004],risk_power=[.5,1.5],cadence=[2,4],amount_floor=[75000000.,100000000.],vol_ceiling=[.05,.06],weight_window=[15,30],high_window=[90,180],turn_window=[15,30])

def extra_features(f):
 cache=OUT/'extra_features.parquet'
 if cache.exists():return pd.read_parquet(cache)
 parts=[]
 for i,(s,q) in enumerate(f.groupby('symbol'),1):
  a=pd.read_parquet(g.bt.qfq_path(s));raw=pd.read_parquet(g.bt.raw_path(s))
  for z in [a,raw]:z['date']=pd.to_datetime(z.date)
  a=a[a.tradestatus.astype(str)=='1'].sort_values('date').set_index('date');raw=raw.sort_values('date').set_index('date')
  close=a.close.astype(float);ret=close.pct_change(fill_method=None);x=pd.DataFrame(index=a.index)
  for n in [15,20,30]:x['risk'+str(n)]=ret.clip(upper=0).pow(2).rolling(n).mean().pow(.5)
  for n in [90,180]:x['high'+str(n)]=close/close.rolling(n).max()
  x['vol20']=ret.rolling(20).std()
  for n in [15,30]:x['turn'+str(n)]=raw.turn.astype(float).rolling(n).mean()
  parts.append(pd.concat([q.reset_index(drop=True),x.reindex(pd.DatetimeIndex(q.signal_date)).reset_index(drop=True)],axis=1))
  if i%700==0:print('FEATURE',i,flush=True)
 out=pd.concat(parts,ignore_index=True);out.to_parquet(cache,index=False);return out

def ranks(f,cfg):
 index=pd.read_parquet(g.bt.DATA/'indices/000905.SH.parquet');index['date']=pd.to_datetime(index.date);index=index.sort_values('date')
 rr={}
 for d,x in f.groupby('execute_date'):
  if (d.month-1)%cfg['cadence']:continue
  q=x[(x.amount20>=cfg['amount_floor'])&(x.vol20<=cfg['vol_ceiling'])].sort_values('symbol').copy()
  history=index[index.date<=x.signal_date.iloc[0]].tail(cfg['ma']);strong=bool(history.close.iloc[-1]>history.close.mean())
  if cfg['high_window']!=120:q['near_high']=q['high'+str(cfg['high_window'])]
  if cfg['turn_window']!=20:q['turn20']=q['turn'+str(cfg['turn_window'])]
  if cfg['weight_window']==20 and cfg['risk_floor']==.002:q['downside']=q.downside
  else:q['downside']=q['risk'+str(cfg['weight_window'])].clip(lower=cfg['risk_floor'])
  if strong:
   b=cfg['bull'];q['score']=b[0]*g.bt.rank01(q.amount20.to_numpy(),True)+b[1]*g.bt.rank01(q.near_high.to_numpy())+b[2]*g.bt.rank01(q.dividend.to_numpy())
  else:
   pct=q.float_cap_proxy.rank(pct=True);lo,hi=cfg['band'];q=q[(pct>=lo)&(pct<hi)].copy()
   b=cfg['defense'];q['score']=b[0]*q.dividend.rank(pct=True)+b[1]*(1-q.downside.rank(pct=True))+b[2]*(1-q.turn20.rank(pct=True))
  q['downside']=q.downside.pow(cfg['risk_power'])
  rr[d]=q.sort_values(['score','symbol'],ascending=[False,True])
 return rr

def measure(c):
 row={}
 for tag,a,b in [('early','2020-01-02','2021-12-31'),('late','2022-01-01','2023-12-31'),('dev','2020-01-02','2023-12-31'),('year2024','2024-01-01','2024-12-31'),('recent','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
  z=c[c.date.between(a,b)];prev=c[c.date<pd.Timestamp(a)]
  for k,v in g.bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else 100000).items():row[tag+'_'+k]=v
 row['robust_score']=min(row['early_annualized_return'],row['late_annualized_return'])+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
 return row

def main():
 OUT.mkdir(exist_ok=True);g.bt.INITIAL_CASH=100000.
 cs=[dict(name='control',family='control',**DEFAULT)]
 for family,values in VARIANTS.items():
  for i,v in enumerate(values):cs.append(dict(dict(DEFAULT,**{family:v}),name=family+'_'+str(i+1),family=family))
 protocol={'configurations':cs,'method':'One-at-a-time, two coarse neighbors each, no recombination or further search after results. Select using 2020-2023 only: weaker two-year CAGR + .05 dev Sharpe - .5 dev absolute MDD. Family must have BOTH neighbors no worse than control score and both profitable in each dev subperiod. Candidate dev CAGR >=95% control and dev drawdown no worse than control. Later periods descriptive, not selection. Stress doubles costs without retuning.','limitations':'All history previously inspected, no clean holdout. Local/platform parity unresolved. Existing eligible universe retained, tightening liquidity/volatility only; listing threshold, 3-year dividend proxy definition and lawful execution/cost constraints not optimized.'}
 (OUT/'protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
 f=extra_features(g.features());rr={c['name']:ranks(f,c) for c in cs}
 union=set(s for c in cs for q in rr[c['name']].values() for s in q.head(c['buffer']).symbol)
 panel=g.bt.load_daily_panel(union);rows=[]
 for i,cfg in enumerate(cs,1):
  print('RUN',i,len(cs),cfg['name'],flush=True)
  c,t=g.bt.simulate(rr[cfg['name']],.05,cfg['count'],cfg['buffer'],cfg['exposure'],cfg['cap'],panel,min_adjustment=cfg['minimum'])
  if cfg['name']=='control':
   old=pd.read_csv(g.HERE/'pending_1_snapshot/defensive_bear_8_equity.csv');assert np.allclose(c.equity,old.equity,atol=.01,rtol=0)
  assert (c.cash>=-.01).all() and (t[t.side=='BUY'].quantity%100==0).all()
  row=dict(cfg,**measure(c),commission=float(t.commission.sum()),orders=len(t));rows.append(row)
  c.to_csv(OUT/(cfg['name']+'_equity.csv'),index=False);t.to_csv(OUT/(cfg['name']+'_trades.csv'),index=False)
  pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False)
 r=pd.DataFrame(rows);ref=r.iloc[0];families=[]
 for family,q in r[r.family!='control'].groupby('family'):
  ok=bool((q.robust_score>=ref.robust_score).all() and (q.early_annualized_return>0).all() and (q.late_annualized_return>0).all())
  families.append(dict(family=family,stable_development_neighbors=ok,minimum_score=float(q.robust_score.min()),maximum_score=float(q.robust_score.max())))
 stable=[z['family'] for z in families if z['stable_development_neighbors']]
 eligible=r[r.family.isin(stable)&(r.dev_annualized_return>=.95*ref.dev_annualized_return)&(r.dev_max_drawdown>=ref.dev_max_drawdown)]
 best=eligible.sort_values('robust_score',ascending=False).iloc[0] if len(eligible) else ref
 cfg=next(c for c in cs if c['name']==best['name'])
 (OUT/'selection.json').write_text(json.dumps(dict(configuration=cfg,reason='predeclared robustness criteria; control retained if none qualifies',stable_families=stable),indent=2),encoding='utf-8')
 pd.DataFrame(families).to_csv(OUT/'family_stability.csv',index=False)
 stresses=[]
 g.bt.SLIPPAGE=.004;g.bt.COMMISSION=.0006;g.bt.MIN_COMMISSION=10.
 for name in dict.fromkeys(['control',cfg['name']]):
  z=next(c for c in cs if c['name']==name);c,t=g.bt.simulate(rr[name],.05,z['count'],z['buffer'],z['exposure'],z['cap'],panel,min_adjustment=z['minimum'])
  stresses.append(dict(name=name,**measure(c)))
 pd.DataFrame(stresses).to_csv(OUT/'stress.csv',index=False)
 print('SELECTED',cfg);print('FAMILIES',families)
 print(r[['name','full_annualized_return','full_max_drawdown','full_sharpe','robust_score']].sort_values('robust_score',ascending=False).to_string(index=False))

if __name__=='__main__':main()
