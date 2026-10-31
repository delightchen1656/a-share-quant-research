import pathlib,pickle,json,dataclasses
from decimal import Decimal
import pandas as pd,numpy as np
from account_engine import run_account,AuditBlocked
from account_audit import audit_result
from action_adapter import load_actions
from market_adapter import build
O=pathlib.Path(__file__).parent

def clean(x):
 if isinstance(x,Decimal):return str(x)
 if dataclasses.is_dataclass(x):return dataclasses.asdict(x)
 if isinstance(x,(np.integer,np.floating)):return x.item()
 raise TypeError(str(type(x)))
def score(a):
 a=[x for x in a if x['year']<=2022];r=[x['return_pct']for x in a];return float(np.median(r)-.5*max(abs(x['max_drawdown'])for x in a)-.5*np.std(r))
def main():
 cfg=json.loads((O/'ROUND2_FROZEN_CONFIG.json').read_text());filters=pd.read_csv(O/'ROUND2_SIGNAL_FILTERS.csv',dtype={'code':str});filters.code=filters.code.str.zfill(6)
 with open(O/'verified_cache.pkl','rb')as f:s,cal,data,e=pickle.load(f)
 actions,cov,unknown,manifest=load_actions('研究尝试/方向1_超跌反弹/inputs_pre2025/execution_rules_2020_2024/actions','4f24a25000552f875dcc34c000d8855c1e7355ece88f0a7eca053aab747437f0',market_data=data);assert not unknown
 bars,factors=build(data);exits=[{'id':'PRIOR','tp':.08,'sl':None,'h':3,'trail':False},{'id':'TEMP','tp':.2,'sl':None,'h':20,'trail':False},{**cfg['NEW'],'id':'NEW'}];results=[];events=[];blocks=[]
 for pool in cfg['pools']:
  f=filters.copy();f['pass']=True if pool=='ALL' else f['pass_'+pool];keys={(z.code,z.signal_date)for z in f[f['pass']].itertuples()}
  signals=[{'code':z.code,'name':z.name,'date':z.signal_date,'entry_date':z.entry_date}for z in s.itertuples()if(z.code,z.signal_date)in keys]
  for ex in exits:
   cid=pool+'_'+ex['id']
   try:
    r=run_account(signals,cal,bars,factors,actions,cov,'2020-01-01','2024-12-31',policy_verified=True,tp=ex['tp'],sl=ex['sl'],horizon=ex['h'],rank='code',trail=False,retain_unknown_quotes=True);audit=audit_result(r,signals,cal)
   except AuditBlocked as exc:blocks.append({'id':cid,'reason':str(exc),'details':exc.details});print('BLOCK',cid,str(exc),flush=True);continue
   nav=pd.DataFrame(r['nav']);stats=[];j=pd.DataFrame(r['journal']);buykeys={(x['code'],x['signal_date'])for x in r['journal']if x['kind']=='buy'};skipkeys={(x['code'],x['date']):x['reason']for x in r['skips']}
   for y,g in nav.groupby(nav.date.str[:4]):
    v=g.apply(lambda x:float(x.stock_value)/float(x.equity),axis=1);jj=j[j.date.str[:4]==y];npass=int(f.loc[(f.year==int(y)),'pass'].sum());stats.append({'year':int(y),'original_signals':int((f.year==int(y)).sum()),'filter_passed':npass,'entered':int((jj.kind=='buy').sum()),'avg_exposure':v.mean(),'fees':str(sum((x.get('total',Decimal(0))for x in r['journal']if x['kind']in['buy','sell']and x['date'][:4]==y),Decimal(0)))})
   uncertainty=[]
   for code,p in r['positions'].items():
    q=data[code][0];active=q[(q.tradestatus==1)&(q.volume>0)&(q.close>0)];last=active.loc[:'2024-12-31'].index[-1]
    if last<'2024-12-31':uncertainty.append({'code':code,'last_active':last,'qty':p.qty(),'last_mark_value':str(p.qty()*p.last_price)})
   rr={'id':cid,'pool':pool,'exit':ex,'summary':r['summary'],'yearly':r['yearly'],'coverage':stats,'train_score':score(r['yearly']),'audit':audit,'final_stale_holdings':uncertainty}
   results.append(rr)
   ff=f.copy();ff['config']=cid;ff['outcome']=[('filtered_at_signal_close' if not yes else ('entered' if(code,day)in buykeys else skipkeys.get((code,ent),'pending_or_unfilled')))for code,day,ent,yes in zip(ff.code,ff.signal_date,ff.entry_date,ff['pass'])];events.append(ff)
   for tab in ['nav','journal','trades','skips','delays','corporate_actions','tax_assessments','unresolved_quotes']:pd.DataFrame(r[tab]).to_csv(O/('ROUND2_'+cid+'_'+tab+'.csv'),index=False)
   print('OK',cid,r['summary']['total_return'],r['summary']['unresolved_quote_events'],flush=True)
   (O/'ROUND2_RESULTS.json').write_text(json.dumps({'results':results,'blocked':blocks},indent=2,default=clean),encoding='utf-8')
 if results:
  chosen=max(results,key=lambda x:(x['train_score'],np.prod([1+a['return_pct']for a in x['yearly']if a['year']<=2022]),x['id']))
  pd.concat(events,ignore_index=True).to_csv(O/'ROUND2_ALL_SIGNAL_OUTCOMES.csv',index=False)
  final={'status':'HISTORICAL_REUSE_NOT_NEW_BLIND_TEST; conditional where unpriced holdings','training_selected_config':chosen,'results':results,'blocked':blocks,'thresholds':cfg,'no_additional_parameter_search':True}
  (O/'ROUND2_SUMMARY.json').write_text(json.dumps(final,indent=2,default=clean),encoding='utf-8');print('TRAIN_SELECTED',chosen['id'])
if __name__=='__main__':main()
