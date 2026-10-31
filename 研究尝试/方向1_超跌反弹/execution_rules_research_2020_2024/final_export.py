import pathlib,json,pickle,dataclasses
from decimal import Decimal
import pandas as pd
from account_engine import run_account,AuditBlocked
from account_audit import audit_result
from action_adapter import load_actions
from market_adapter import build
O=pathlib.Path(__file__).parent

def default(x):
 if isinstance(x,Decimal):return str(x)
 if dataclasses.is_dataclass(x):return dataclasses.asdict(x)
 raise TypeError(str(type(x)))
def main():
 freeze=json.loads((O/'CANDIDATE_FREEZE.json').read_text());r=freeze['primary']
 with open(O/'verified_cache.pkl','rb')as f:s,cal,data,e=pickle.load(f)
 actions,cov,unknown,_=load_actions('研究尝试/方向1_超跌反弹/inputs_pre2025/execution_rules_2020_2024/actions','4f24a25000552f875dcc34c000d8855c1e7355ece88f0a7eca053aab747437f0',market_data=data);bars,factors=build(data);signals=[{'code':z.code,'name':z.name,'date':z.signal_date,'entry_date':z.entry_date}for z in s.itertuples()];out={}
 for key,c in [('PRIMARY',r),('ORIGINAL',{'tp':.08,'sl':None,'h':3})]:
  kwargs=dict(policy_verified=True,tp=c['tp'],sl=c['sl'],horizon=c['h'],rank='code')
  try:strict=run_account(signals,cal,bars,factors,actions,cov,'2020-01-01','2024-12-31',**kwargs);strict_status={'passed':True,'audit':audit_result(strict,signals,cal)}
  except AuditBlocked as exc:strict_status={'passed':False,'reason':str(exc),'details':exc.details}
  result=run_account(signals,cal,bars,factors,actions,cov,'2020-01-01','2024-12-31',**kwargs,retain_unknown_quotes=True);audit=audit_result(result,signals,cal);unknown_codes=sorted(set(x['code']for x in result['unresolved_quotes']));holdings=[]
  for code,p in result['positions'].items():
   if code in unknown_codes:holdings.append({'code':code,'buy_date':p.buy_date,'qty':p.qty(),'last_price':p.last_price,'value':p.qty()*p.last_price})
  for table in ['nav','journal','trades','skips','delays','corporate_actions','tax_assessments','unresolved_quotes']:pd.DataFrame(result[table]).to_csv(O/('FINAL_'+key+'_'+table+'.csv'),index=False)
  exposure=sum(float(x['stock_value'])/float(x['equity'])for x in result['nav'])/len(result['nav']);coverage=[]
  for annual in result['yearly']:
   y=str(annual['year']);nj=[x for x in result['journal']if x['date'][:4]==y];nn=[x for x in result['nav']if x['date'][:4]==y]
   coverage.append({'year':annual['year'],'signals':int((s.entry_date.str[:4]==y).sum()),'entered':sum(x['kind']=='buy'for x in nj),'fees':sum((x.get('total',Decimal(0))for x in nj if x['kind']in['buy','sell']),Decimal(0)),'avg_exposure':sum(float(x['stock_value'])/float(x['equity'])for x in nn)/len(nn)})
  returns=[x['return_pct']for x in result['trades']];tail=pd.Series(returns)
  out[key]={'strict_status':strict_status,'summary':result['summary'],'yearly':result['yearly'],'audit':audit,'coverage':coverage,'avg_exposure':exposure,'unresolved_codes':unknown_codes,'unresolved_final_holdings':holdings,'tail':{'min_trade_return':tail.min(),'p10_trade_return':tail.quantile(.1),'median_trade_return':tail.median(),'win_rate':(tail>0).mean()},'skip_reasons':pd.Series([x['reason']for x in result['skips']]).value_counts().to_dict()}
 # Stress only terminal market value; no hypothetical liquidation, cash release, or new trades.
 scenarios=[]
 for mult in [0,.5,1,2]:
  row={'terminal_unpriced_value_multiplier':mult,'terminal_only_no_rebalance':True}
  for key in ['PRIMARY','ORIGINAL']:
   value=sum(x['value']for x in out[key]['unresolved_final_holdings']);change=value*Decimal(str(mult-1));row[key+'_return']=out[key]['summary']['total_return']+float(change)/1e6
  row['PRIMARY_minus_ORIGINAL']=row['PRIMARY_return']-row['ORIGINAL_return'];scenarios.append(row)
 out['terminal_value_scenarios']=scenarios;out['sensitivity_limits']='Shared terminal asset value does not alter terminal PnL difference in these fixed-ledger scenarios; unknown actual transfer timing/cash release/slot release can change later trades and ordering, so this is not a dynamic robustness proof or exact economic bounds.'
 (O/'FINAL_COMPARISON.json').write_text(json.dumps(out,indent=2,default=default),encoding='utf-8');print(json.dumps(out,indent=2,default=default))
if __name__=='__main__':main()
