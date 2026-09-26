"""Alternative signals, weighting and exposure; pending 1 remains frozen."""
import json
import numpy as np
import pandas as pd
import group_research as g
OUT=g.HERE/'group_round3_100k'

def configs():
 cs=[dict(name='pending1_control',family='control',value=0)]
 for family,values in [('market_ma',[60,200]),('breadth',[.45,.55]),('dual_index',[60,120]),('hysteresis',[.01,.03]),('defensive_group',['lowvol','midamount']),('temperature',[.3,.7]),('risk_weight',['equal','vol60']),('tail_filter',[.8,.9]),('cadence',[1,2]),('exposure',['regime','vol_target'])]:
  for v in values:cs.append(dict(name=f'{family}_{v}',family=family,value=v))
 return cs

def prepare(f,cs):
 base=g.bt.ranked_months(f,(.25,.2,.55),(.65,.25,.1),120)
 indices={}
 for code in ['000905.SH','000300.SH']:
  z=pd.read_parquet(g.bt.DATA/f'indices/{code}.parquet');z['date']=pd.to_datetime(z.date);indices[code]=z.sort_values('date')
 allranks={};exposures={};states=[];union=set()
 for cfg in cs:
  rr={};ee={};last=False;temps=[]
  for d,x in base.items():
   signal=x.signal_date.iloc[0];family=cfg['family'];value=cfg['value']
   hist=indices['000905.SH'];hist=hist[hist.date<=signal]
   ma=hist.close.tail(120).mean();bull=bool(hist.close.iloc[-1]>ma)
   group=x[x.float_cap_proxy_group==1]
   temp=float(group.ret60.median());temps.append(temp)
   period=int(value) if family=='cadence' else 3
   if (d.month-1)%period:continue
   if family=='market_ma':bull=bool(hist.close.iloc[-1]>hist.close.tail(int(value)).mean())
   if family=='breadth':bull=bool((x.ret60>0).mean()>value)
   if family=='dual_index':
    other=indices['000300.SH'];other=other[other.date<=signal]
    bull=bool(hist.close.iloc[-1]>hist.close.tail(int(value)).mean() and other.close.iloc[-1]>other.close.tail(int(value)).mean())
   if family=='hysteresis':
    ratio=hist.close.iloc[-1]/ma-1
    bull=True if ratio>value else False if ratio < -value else last
   if family=='temperature':
    # Percentile relative to previously observable monthly group temperatures.
    rank=float(np.mean(np.asarray(temps)<=temp))
    bull=bool(bull and rank>=value)
   last=bull
   if family=='defensive_group':group=x[x.vol60_group==0] if value=='lowvol' else x[x.amount20_group==1]
   q=x.copy() if bull else g.score(group,'quality')
   if family=='tail_filter':q=q[q.vol60<=x.vol60.quantile(value)]
   if family=='risk_weight':q=q.copy();q['downside']=1. if value=='equal' else q.vol60.clip(lower=.002)
   exposure=.8
   if family=='exposure':
    if value=='regime':exposure=.95 if bull else .65
    else:exposure=float(np.clip(.15/(hist.close.pct_change().tail(60).std()*np.sqrt(252)),.4,.95))
   rr[d]=q.sort_values(['score','symbol'],ascending=[False,True]);ee[d]=exposure
   union.update(rr[d].head(24).symbol)
   states.append(dict(name=cfg['name'],execute_date=d,signal_date=signal,bull=bull,exposure=exposure))
  allranks[cfg['name']]=rr;exposures[cfg['name']]=ee
 return allranks,exposures,states,union

def main():
 OUT.mkdir(exist_ok=True);g.bt.INITIAL_CASH=100000.;cs=configs()
 (OUT/'protocol.json').write_text(json.dumps({'configs':cs,'selection':'Dev 2020-2023 CAGR+.05Sharpe-.5abs(MDD), MDD<=35%; later periods descriptive','limits':'Historical exploration, not fresh OOS. Same cost and universe limitations. 100k, 8 holdings, buffer24, min adjustment3000.'},indent=2),encoding='utf-8')
 rr,ee,states,union=prepare(g.features(),cs);pd.DataFrame(states).to_csv(OUT/'signal_audit.csv',index=False)
 panel=g.bt.load_daily_panel(union);rows=[];best=-np.inf
 for i,cfg in enumerate(cs,1):
  n=cfg['name'];print('RUN',i,len(cs),n,flush=True)
  c,t=g.bt.simulate(rr[n],.05,8,24,ee[n],1.5,panel,min_adjustment=3000)
  if cfg['family']=='control':
   prior=pd.read_csv(g.HERE/'pending_1_snapshot/defensive_bear_8_equity.csv');assert np.allclose(c.equity,prior.equity,rtol=0,atol=.01)
  row=dict(cfg)
  for tag,start,end in [('dev','2020-01-02','2023-12-31'),('validation','2024-01-01','2024-12-31'),('observed','2025-01-01','2026-09-11'),('full','2020-01-02','2026-09-11')]:
   z=c[c.date.between(start,end)];prev=c[c.date<pd.Timestamp(start)]
   for k,v in g.bt.metrics(z,float(prev.equity.iloc[-1]) if len(prev) else 100000).items():row[tag+'_'+k]=v
  row.update(orders=len(t),commission=float(t.commission.sum()),stamp_tax=float(t.stamp_tax.sum()))
  row['score']=row['dev_annualized_return']+.05*row['dev_sharpe']-.5*abs(row['dev_max_drawdown'])
  row['eligible']=bool(row['dev_max_drawdown']>=-.35)
  c.to_csv(OUT/(n+'_equity.csv'),index=False);t.to_csv(OUT/(n+'_trades.csv'),index=False)
  rows.append(row);pd.DataFrame(rows).to_csv(OUT/'results.csv',index=False)
  if row['eligible'] and row['score']>best:
   best=row['score'];(OUT/'candidate.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
 print(pd.DataFrame(rows)[['name','full_annualized_return','full_max_drawdown','full_sharpe','score']].sort_values('score',ascending=False).to_string(index=False))

if __name__=='__main__':main()
