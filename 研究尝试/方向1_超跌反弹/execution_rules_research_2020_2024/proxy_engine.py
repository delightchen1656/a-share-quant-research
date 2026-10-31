import pathlib,pickle,json,itertools,math,hashlib
import pandas as pd,numpy as np
ROOT=pathlib.Path('研究尝试/方向1_超跌反弹');OUT=ROOT/'execution_rules_research_2020_2024'
with open(OUT/'verified_cache.pkl','rb') as f:s,cal,data,events=pickle.load(f)
idx={d:i for i,d in enumerate(cal)}; dates=[d for d in cal if d>='2020-01-01']; ev=events.set_index(['code','entry_date']); signalmap={d:g for d,g in s.groupby('entry_date')}
# Shadow units preserve total-return qfq ratios, actual entry lot sizing uses raw prices.
# This is deliberately a price-path proxy, not a company-action-complete economic account.
series={}
for code,(raw,q) in data.items():
 raw=raw.reindex(cal);q=q.reindex(cal)
 series[code]={'r':raw[['open','high','low','close','preclose','volume','tradestatus','isST']].to_numpy(float),'q':q[['open','high','low','close']].to_numpy(float)}
candidates=[]
for rank,tp,sl,h in itertools.product(['code','liquid','deep'],[.10,.15,.20],[None,.08,.12],[10,20]):
 candidates.append({'id':f'{rank}_TP{int(tp*100)}_SL{0 if sl is None else int(sl*100)}_H{h}','rank':rank,'tp':tp,'sl':sl,'h':h,'trail':False})
for rank in ['code','liquid','deep']:candidates.append({'id':f'{rank}_TP20_TRAIL12_H20','rank':rank,'tp':.2,'sl':.12,'h':20,'trail':True})
(OUT/'CANDIDATES.json').write_text(json.dumps(candidates,indent=2),encoding='utf-8')
def commission(v):return max(5.,v*.0003)
def transfer(v,d):return v*(.00002 if d<'2022-04-29' else .00001)
def stamp(v,d):return v*(.001 if d<'2023-08-28' else .0005)
def simulate(c,start='2020-01-01',end='2024-12-31',detail=False):
 cash=1e6;pos=[];eq=[];trades=[];unknownholding=set();stats={'all_signals':0,'entered':0,'no_open':0,'oneprice_up':0,'duplicate':0,'capacity':0,'unaffordable':0,'fee':0.,'stale_valuation_days':0};signalstats=[]
 def sell(p,j,qp,reason,d):
  nonlocal cash
  rr=series[p['code']]['r'][j];qq=series[p['code']]['q'][j]
  # Convert qfq proceeds to equivalent price-path P&L, retaining real entry cash size.
  proceeds=p['capital']*qp/p['qentry'];fee=commission(proceeds)+transfer(proceeds,d)+stamp(proceeds,d);cash+=proceeds-fee;stats['fee']+=fee
  trades.append({'code':p['code'],'entry':p['date'],'exit':d,'reason':reason,'pnl':proceeds-fee-p['cost'],'return':(proceeds-fee)/p['cost']-1,'gross_return':qp/p['qentry']-1,'days':j-p['j'],'entry_cost':p['cost'],'sell_fee':fee,'peak':p['peak']/p['qentry']-1});pos.remove(p)
 for d in dates:
  if d<start or d>end:continue
  j=idx[d]
  for p in list(pos):
   rr=series[p['code']]['r'][j];qq=series[p['code']]['q'][j];rO,rH,rL,rC,pre,v,status,st=rr;qO,qH,qL,qC=qq
   if not (np.isfinite(qO) and status==1 and v>0):continue
   down=(rH==rL and rC<pre)
   if down:continue
   sl=(p['maxclose'] if c['trail'] else p['qentry'])*(1-c['sl']) if c['sl'] else -np.inf;tp=p['qentry']*(1+c['tp'])
   if qO<=sl:sell(p,j,qO,'gap_sl',d)
   elif qO>=tp:sell(p,j,tp,'gap_tp',d)
   elif j>p['j']+c['h']:sell(p,j,qO,'overdue_open',d)
  g=signalmap.get(d)
  if g is not None:
   g=g.copy();stats['all_signals']+=len(g)
   if c['rank']=='code':g=g.sort_values('code')
   else:
    field='amount20' if c['rank']=='liquid' else 'ret20';g['_rank']=[ev.loc[(z.code,d),field] if (z.code,d) in ev.index else np.nan for z in g.itertuples()];g=g.sort_values(['_rank','code'],ascending=[c['rank']=='deep',True],na_position='last')
   for z in g.itertuples():
    code=z.code;rr=series[code]['r'][j];qq=series[code]['q'][j];rO,rH,rL,rC,pre,v,status,st=rr;qO=qq[0]
    if not(np.isfinite(rO) and rO>0 and status==1 and v>0 and np.isfinite(qO) and qO>0):stats['no_open']+=1;continue
    # Entry rejects only open-at-upper-limit using known preclose/isST; daily high/low is not used to pick an open entry.
    limit=.05 if st==1 else .10;up=round(pre*(1+limit)+1e-8,2)
    if np.isfinite(pre) and rO>=up-.001:stats['oneprice_up']+=1;continue
    if any(p['code']==code for p in pos):stats['duplicate']+=1;continue
    if len(pos)>=20:stats['capacity']+=1;continue
    budget=min(50000,cash);n=int(budget/rO/100)*100
    while n>0 and n*rO+commission(n*rO)+transfer(n*rO,d)>budget:n-=100
    if n<=0:stats['unaffordable']+=1;continue
    capital=n*rO;fee=commission(capital)+transfer(capital,d);cost=capital+fee;cash-=cost;stats['fee']+=fee;stats['entered']+=1
    pos.append({'code':code,'j':j,'date':d,'qentry':qO,'capital':capital,'cost':cost,'maxclose':qO,'peak':qO,'mark':qO,'markdate':d})
  for p in list(pos):
   rr=series[p['code']]['r'][j];qq=series[p['code']]['q'][j];rO,rH,rL,rC,pre,v,status,st=rr;qO,qH,qL,qC=qq
   if not (np.isfinite(qC) and status==1 and v>0):
    stats['stale_valuation_days']+=1
    if not np.isfinite(status):unknownholding.add(p['code'])
    continue
   p['peak']=max(p['peak'],qH);p['mark']=qC;p['markdate']=d
   if j>p['j'] and not(rH==rL and rC<pre):
    sl=(p['maxclose'] if c['trail'] else p['qentry'])*(1-c['sl']) if c['sl'] else -np.inf;tp=p['qentry']*(1+c['tp'])
    if qL<=sl:sell(p,j,min(qO,sl),'intraday_sl',d);continue
    if qH>=tp:sell(p,j,tp,'intraday_tp',d);continue
    if j>=p['j']+c['h']:sell(p,j,qC,'timeout',d);continue
   p['maxclose']=max(p['maxclose'],qC)
  mv=sum(p['capital']*p['mark']/p['qentry'] for p in pos);equity=cash+mv
  eq.append({'date':d,'equity':equity,'cash':cash,'positions':len(pos),'exposure':mv/equity})
 e=pd.DataFrame(eq);t=pd.DataFrame(trades);annual=[];prev=1e6
 for y,g in e.groupby(e.date.str[:4]):
  vals=np.r_[prev,g.equity.values]; dd=vals/np.maximum.accumulate(vals)-1
  annual.append({'year':int(y),'return':vals[-1]/prev-1,'drawdown':float(dd.min()),'avg_exposure':g.exposure.mean(),'avg_positions':g.positions.mean(),'year_end_equity':vals[-1]});prev=vals[-1]
 vals=np.r_[1e6,e.equity.values]
 summary={**c,**stats,'total_return':vals[-1]/1e6-1,'max_drawdown':float((vals/np.maximum.accumulate(vals)-1).min()),'open_positions':len(pos),'avg_exposure':e.exposure.mean(),'trades':len(t),'annual':annual}
 summary['unverified_quote_gap_codes']=sorted(unknownholding)
 summary['open_holdings']=[{'code':p['code'],'entry':p['date'],'last_mark':p['markdate'],'last_mark_age_sessions':idx[e.date.iloc[-1]]-idx[p['markdate']],'shadow_mark_value':p['capital']*p['mark']/p['qentry']}for p in pos]
 if detail:
  e.to_csv(OUT/(c['id']+'_equity.csv'),index=False);t.to_csv(OUT/(c['id']+'_trades.csv'),index=False)
 return summary

def score(a):
 r=np.array([x['return'] for x in a]);dd=max(abs(x['drawdown']) for x in a);return float(np.median(r)-.5*dd-.5*np.std(r))
def main():
 results=[]
 for i,c in enumerate(candidates):
  res=simulate(c);results.append(res)
  if i%10==0:print('progress',i,flush=True)
 (OUT/'PROXY_RESULTS.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
 records=[]
 for r in results:
  for a in r['annual']:records.append({**{k:v for k,v in r.items() if k!='annual'},**a,'score_full':score(r['annual'])})
 pd.DataFrame(records).to_csv(OUT/'proxy_candidate_annual.csv',index=False)
 selected=max(results,key=lambda r:(score(r['annual']),r['total_return'],not r['trail'],r['id']))
 baseline=next(r for r in results if r['id']=='code_TP20_SL0_H20')
 folds=[]
 for y in [2022,2023,2024]:
  chosen=max(results,key=lambda r:(score([a for a in r['annual'] if a['year']<y]),np.prod([1+a['return'] for a in r['annual'] if a['year']<y]),not r['trail'],r['id']))
  c=next(c for c in candidates if c['id']==chosen['id']);test=simulate(c,f'{y}-01-01',f'{y}-12-31');b=simulate(next(c for c in candidates if c['id']==baseline['id']),f'{y}-01-01',f'{y}-12-31');folds.append({'year':y,'selected':c['id'],'validation':test,'baseline':b})
 for c in candidates:
  if c['id'] in [selected['id'],baseline['id']]:simulate(c,detail=True)
 report={'status':'PRICE_PATH_PROXY_NOT_ECONOMIC_NET_RETURN','selected':selected,'baseline':baseline,'walk_forward':folds,'grid_size':len(candidates),'limitations':['qfq total-return shadow units ignore corporate-action payment/listing timing and dividend tax','entry limit detection conservatively rejects all upper-limit opens; no orderbook','historical transfer fee convention and tax schedule must be checked','year-end stale quotes remain last marked, unresolved delisting economic losses not invented']}
 (OUT/'PROXY_SUMMARY.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
