"""Load parent-authorized actions; merge duplicate entitlements before accounting.
Conflicting rows require unique quote-reference/factor evidence, otherwise block if held.
"""
from pathlib import Path
from decimal import Decimal
from collections import defaultdict
import hashlib,json,math
from account_engine import Action,money

RIGHT_DATES=['dividRegistDate','dividOperateDate','dividPayDate','dividStockMarketDate']
def num(row,key):return Decimal(str(row.get(key) or '0'))
def entitlement_key(row):
 return tuple(row.get(k) or None for k in RIGHT_DATES)+tuple(num(row,k)for k in ['dividCashPsBeforeTax','dividStocksPs','dividReserveToStockPs'])
def canonicalize_records(records,market_data=None):
 groups=defaultdict(list);audit=[];out=[]
 for key,rows in records.items():
  for i,row in enumerate(rows):
   code=key.split('/')[0].split('.')[0];ex=row.get('dividOperateDate')
   groups[(code,ex or f'UNSCHEDULED:{key}:{i}')].append({'key':key,'row_id':i,'row':row})
 for (code,ex),rows in groups.items():
  variants={}
  for row in rows:variants.setdefault(entitlement_key(row['row']),row)
  vals=list(variants.values());chosen=vals[0];conflict=len(vals)>1;resolution='single_entitlement' if len(rows)==1 else 'identical_entitlement_rows_merged';tests=[]
  if conflict:
   resolution='unresolved_conflicting_entitlements'
   if market_data is not None and code in market_data:
    raw,q=market_data[code];previous=raw.loc[raw.index<ex];previous=previous[(previous.tradestatus==1)&(previous.close>0)]
    if len(previous) and ex in raw.index and ex in q.index:
     prev=previous.index[-1];price=Decimal(str(raw.loc[prev,'close']));reference=Decimal(str(raw.loc[ex,'preclose']))
     observed=(float(q.loc[ex,'close'])/float(raw.loc[ex,'close']))/(float(q.loc[prev,'close'])/float(price))
     matches=[]
     for v in vals:
      row=v['row'];cash=num(row,'dividCashPsBeforeTax');stock=num(row,'dividStocksPs')+num(row,'dividReserveToStockPs')
      ref=money((price-cash)/(1+stock));factor=float(price/ref)if ref>0 else float('nan');error=observed/factor-1
      ok=(ref==reference and math.isfinite(error) and abs(error)<.00001)
      tests.append({'source':f"{v['key']}:{v['row_id']}",'cash_ps':str(cash),'stock_ps':str(stock),'predicted_rounded_reference':str(ref),'raw_reference':str(reference),'observed_factor_jump':observed,'predicted_factor_from_rounded_reference':factor,'relative_error':error,'match':ok})
      if ok:matches.append(v)
     if len(matches)==1:chosen=matches[0];conflict=False;resolution='unique_rounded_ex_reference_and_factor_match'
  row=dict(chosen['row']);source_ids=[f"{v['key']}:{v['row_id']}"for v in rows]
  if conflict and len({v['row'].get('dividRegistDate')or None for v in rows})>1:row['dividRegistDate']=None
  out.append({'code':code,'row':row,'source_ids':source_ids,'conflict':conflict,'resolution':resolution})
  if len(rows)>1:audit.append({'code':code,'ex_date':ex,'source_ids':source_ids,'variants':len(vals),'conflict_unresolved':conflict,'resolution':resolution,'selected_source':f"{chosen['key']}:{chosen['row_id']}"if not conflict else None,'tests':tests})
 return out,audit

def load_actions(base,expected_manifest_hash,market_data=None):
 base=Path(base);p=base/'MANIFEST.json';assert hashlib.sha256(p.read_bytes()).hexdigest()==expected_manifest_hash
 manifest=json.loads(p.read_text(encoding='utf-8-sig'));assert manifest['cutoff']=='2024-12-31' and manifest['complete']
 for row in manifest['files']:
  f=base/row['path'];assert f.resolve().is_relative_to(base.resolve());assert hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256']
 records=json.loads((base/manifest['company_actions_file']).read_text(encoding='utf-8-sig'));coverage=set();response_keys=set()
 for row in manifest['responses']:
  resp=json.loads((base/row['path']).read_text(encoding='utf-8-sig'));assert resp['error_code']=='0';assert resp['key']==row['key'];response_keys.add(row['key']);code,year=row['key'].split('/');coverage.add((code.split('.')[0],int(year)))
 assert set(records)==response_keys
 canonical,audit=canonicalize_records(records,market_data);manifest=dict(manifest);manifest['canonicalization_audit']=audit;actions=[];uncertain=[]
 for item in canonical:
  code=item['code'];row=item['row'];dates={k:row.get(k,'')for k in row if k.startswith('divid')and k.endswith('Date')};assert all(not x or x<='2024-12-31'for x in dates.values())
  cash=num(row,'dividCashPsBeforeTax');bonus=num(row,'dividStocksPs');reserve=num(row,'dividReserveToStockPs')
  if cash==0 and bonus==0 and reserve==0 and not item['conflict']:continue
  reg=row.get('dividRegistDate')or None;ex=row.get('dividOperateDate')or None;pay=row.get('dividPayDate')or None;release=row.get('dividStockMarketDate')or None;unresolved=[]
  if item['conflict']:unresolved.append('conflicting_supplier_entitlements:'+','.join(item['source_ids']))
  if not reg:unresolved.append('record_date')
  if not ex:unresolved.append('ex_date')
  if cash and not pay:unresolved.append('pay_date')
  if bonus or reserve:
   unresolved.extend(['stock_acquisition_date','taxable_stock_income_ps'])
   if not release:unresolved.append('stock_release_date')
  action_id=f'{code}:{ex}';a=Action(action_id,code,reg,ex,cash,bonus,reserve,pay,release,None,0 if bonus+reserve==0 else None,verified=not unresolved,unresolved_fields=unresolved,evidence='verified_manifest_supplier_responses:'+','.join(item['source_ids'])+';'+item['resolution'])
  if not ex:uncertain.append({'action_id':action_id,'code':code,'reason':unresolved,'raw':row})
  else:actions.append(a)
 return actions,coverage,uncertain,manifest
