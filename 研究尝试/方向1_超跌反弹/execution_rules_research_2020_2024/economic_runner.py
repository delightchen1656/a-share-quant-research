import argparse,json,pickle,pathlib,dataclasses
from decimal import Decimal
import pandas as pd,numpy as np
from account_engine import run_account,AuditBlocked
from account_audit import audit_result
from market_adapter import build
from action_adapter import load_actions
O=pathlib.Path(__file__).parent

def clean(x):
 if isinstance(x,Decimal):return str(x)
 if dataclasses.is_dataclass(x):return dataclasses.asdict(x)
 if isinstance(x,(np.integer,np.floating)):return x.item()
 raise TypeError(str(type(x)))
def score(a):
 r=np.array([x['return_pct'] for x in a]);return float(np.median(r)-.5*max(abs(x['max_drawdown']) for x in a)-.5*np.std(r))
def main():
 p=argparse.ArgumentParser();p.add_argument('--actions',required=True);p.add_argument('--manifest-hash',required=True);p.add_argument('--diagnostic-retain-unknown',action='store_true');p.add_argument('--resume-completed',action='store_true');args=p.parse_args();prefix='DIAGNOSTIC_' if args.diagnostic_retain_unknown else ''
 with open(O/'verified_cache.pkl','rb') as f:s,cal,data,e=pickle.load(f)
 actions,coverage,unknown,manifest=load_actions(args.actions,args.manifest_hash,market_data=data)
 (O/'ACTION_CANONICALIZATION_AUDIT.json').write_text(json.dumps(manifest['canonicalization_audit'],indent=2),encoding='utf-8')
 bars,factors=build(data);signal=[]
 for z in s.itertuples():
  row=e[(e.code==z.code)&(e.entry_date==z.entry_date)].iloc[0]
  signal.append({'code':z.code,'name':z.name,'date':z.signal_date,'entry_date':z.entry_date,'amount20':row.get('amount20',0),'ret20':z.ret20})
 cand=json.loads((O/'CANDIDATES.json').read_text());cand.append({'id':'code_TP8_SL0_H3_PRIOR_BASELINE','rank':'code','tp':.08,'sl':None,'h':3,'trail':False});results=[];blocks=[]
 if args.resume_completed:
  status=json.loads((O/(prefix+'ECONOMIC_RUN_STATUS.json')).read_text());results=status['completed']
 def execute(c,start='2020-01-01',end='2024-12-31'):
  result=run_account(signal,cal,bars,factors,actions,coverage,start,end,policy_verified=True,tp=c['tp'],sl=c['sl'],horizon=c['h'],rank=c['rank'],trail=c['trail'],retain_unknown_quotes=args.diagnostic_retain_unknown);check=audit_result(result,signal,cal);return result,check
 # Non-schedulable actions are not assumed absent; any code with possible ownership is marked and blocks exact claims.
 if unknown:
  (O/'UNSCHEDULED_ACTIONS.json').write_text(json.dumps(unknown,indent=2,default=clean),encoding='utf-8')
 for i,c in enumerate(cand):
  if any(x['candidate']['id']==c['id'] for x in results):continue
  try:
   result,check=execute(c);results.append({'candidate':c,'summary':result['summary'],'yearly':result['yearly'],'audit':check})
  except AuditBlocked as exc:blocks.append({'candidate':c,'reason':str(exc),'details':exc.details})
  (O/(prefix+'ECONOMIC_RUN_STATUS.json')).write_text(json.dumps({'completed':results,'blocked':blocks,'unscheduled_actions':len(unknown)},indent=2,default=clean),encoding='utf-8')
  print(i,c['id'],'OK' if results and results[-1]['candidate']==c else blocks[-1]['reason'],flush=True)
 if blocks or unknown:
  print('EXACT_ECONOMIC_CONCLUSION_BLOCKED',len(blocks),len(unknown));return
 selected=max([x for x in results if 'PRIOR_BASELINE' not in x['candidate']['id']],key=lambda r:(score(r['yearly']),r['summary']['total_return'],not r['candidate']['trail'],r['candidate']['id']))
 baseline=next(r for r in results if r['candidate']['id']=='code_TP20_SL0_H20');folds=[]
 for year in [2022,2023,2024]:
  chosen=max(results,key=lambda r:(score([a for a in r['yearly'] if a['year']<year]),np.prod([1+a['return_pct']for a in r['yearly']if a['year']<year]),not r['candidate']['trail'],r['candidate']['id']))
  r,check=execute(chosen['candidate'],f'{year}-01-01',f'{year}-12-31');b,bcheck=execute(baseline['candidate'],f'{year}-01-01',f'{year}-12-31');folds.append({'year':year,'chosen':chosen['candidate'],'validation':r['summary'],'validation_yearly':r['yearly'],'baseline':b['summary'],'baseline_yearly':b['yearly'],'audits':[check,bcheck]})
 prior=next(x for x in results if 'PRIOR_BASELINE' in x['candidate']['id'])
 for c in [selected['candidate'],baseline['candidate'],prior['candidate']]:
  r,check=execute(c)
  for table in ['nav','journal','trades','skips','delays','corporate_actions','tax_assessments','unresolved_quotes']:
   pd.DataFrame(r[table]).to_csv(O/(prefix+c['id']+'_ECONOMIC_'+table+'.csv'),index=False)
  (O/(prefix+c['id']+'_ECONOMIC_summary.json')).write_text(json.dumps({'summary':r['summary'],'yearly':r['yearly'],'audit':check},indent=2,default=clean),encoding='utf-8')
 report={'status':'CONDITIONAL_LAST_MARK_UNPRICED_ASSETS' if args.diagnostic_retain_unknown else 'ECONOMIC_ACCOUNT_WITH_DISCLOSED_DAILY_EXECUTION_ASSUMPTIONS','selected':selected,'baseline':baseline,'prior_baseline':prior,'folds':folds}
 (O/(prefix+'ECONOMIC_SUMMARY.json')).write_text(json.dumps(report,indent=2,default=clean),encoding='utf-8')
 print('COMPLETE',selected['candidate']['id'])
if __name__=='__main__':main()
