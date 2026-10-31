import pathlib,pickle,json,itertools
from decimal import Decimal
import pandas as pd,numpy as np
from account_engine import run_account,AuditBlocked
from account_audit import audit_result
from action_adapter import load_actions
from market_adapter import build
O=pathlib.Path(__file__).parent

def clean(x):
 if isinstance(x,Decimal):return str(x)
 if isinstance(x,(np.integer,np.floating)):return x.item()
 raise TypeError(str(type(x)))
def score(a):
 a=[x for x in a if x['year']<=2022];r=[x['return_pct']for x in a];return float(np.median(r)-.5*max(abs(x['max_drawdown'])for x in a)-.5*np.std(r))
def main():
 with open(O/'verified_cache.pkl','rb')as f:s,cal,data,e=pickle.load(f)
 actions,cov,unknown,_=load_actions('研究尝试/方向1_超跌反弹/inputs_pre2025/execution_rules_2020_2024/actions','4f24a25000552f875dcc34c000d8855c1e7355ece88f0a7eca053aab747437f0',market_data=data);assert not unknown
 bars,factors=build(data);signals=[{'code':z.code,'name':z.name,'date':z.signal_date,'entry_date':z.entry_date}for z in s.itertuples()];results=[];blocks=[]
 cand=[{'id':f"TP{int(tp*100)}_SL{0 if sl is None else int(sl*100)}_H{h}",'tp':tp,'sl':sl,'h':h}for tp,sl,h in itertools.product([.06,.08,.10],[None,.06,.10],[2,3,5])]
 (O/'ROUND3_GRID.json').write_text(json.dumps(cand,indent=2),encoding='utf-8')
 for c in cand:
  try:r=run_account(signals,cal,bars,factors,actions,cov,'2020-01-01','2024-12-31',policy_verified=True,tp=c['tp'],sl=c['sl'],horizon=c['h'],rank='code',retain_unknown_quotes=True);audit=audit_result(r,signals,cal)
  except AuditBlocked as exc:blocks.append({'candidate':c,'reason':str(exc),'details':exc.details});continue
  n=pd.DataFrame(r['nav']);j=pd.DataFrame(r['journal']);coverage=[]
  for y,g in n.groupby(n.date.str[:4]):
   coverage.append({'year':int(y),'signals':int((s.entry_date.str[:4]==y).sum()),'entered':int(((j.kind=='buy')&(j.date.str[:4]==y)).sum()),'avg_exposure':g.apply(lambda z:float(z.stock_value)/float(z.equity),axis=1).mean(),'fees':str(sum((x.get('total',Decimal(0))for x in r['journal']if x['kind']in['buy','sell']and x['date'][:4]==y),Decimal(0)))})
  rr={'candidate':c,'summary':r['summary'],'yearly':r['yearly'],'coverage':coverage,'train_score':score(r['yearly']),'audit':audit};results.append(rr)
  for table in ['nav','trades','skips','unresolved_quotes']:pd.DataFrame(r[table]).to_csv(O/('ROUND3_'+c['id']+'_'+table+'.csv'),index=False)
  (O/'ROUND3_RESULTS.json').write_text(json.dumps({'results':results,'blocked':blocks},indent=2,default=clean),encoding='utf-8');print('OK',c['id'],r['summary']['total_return'],flush=True)
 chosen=max(results,key=lambda x:(x['train_score'],np.prod([1+a['return_pct']for a in x['yearly']if a['year']<=2022]),x['candidate']['sl']is None,x['candidate']['id']));baseline=next(x for x in results if x['candidate']['id']=='TP8_SL0_H3')
 frozen={'kind':'pre2023_training_selected_before_historical_reuse_reporting','candidate':chosen['candidate'],'training_score':chosen['train_score'],'not_new_blind_test':True,'full_economic_claim_blocked_by_unpriced_assets':True}
 (O/'ROUND3_TRAINING_SELECTED.json').write_text(json.dumps(frozen,indent=2),encoding='utf-8')
 (O/'ROUND3_SUMMARY.json').write_text(json.dumps({'status':'CONDITIONAL_LAST_MARK_UNPRICED_ASSETS; HISTORICAL_REUSE','training_selected':chosen,'baseline':baseline,'results':results,'blocked':blocks},indent=2,default=clean),encoding='utf-8');print('TRAIN_SELECTED',chosen['candidate']['id'])
if __name__=='__main__':main()
