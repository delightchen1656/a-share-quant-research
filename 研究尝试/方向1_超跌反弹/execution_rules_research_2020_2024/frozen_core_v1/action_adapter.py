"""Load only a parent-authorized manifest hash. Never trusts empty actions without responses."""
from pathlib import Path
from decimal import Decimal
import hashlib,json
from account_engine import Action

def load_actions(base,expected_manifest_hash):
 base=Path(base);p=base/'MANIFEST.json'
 assert hashlib.sha256(p.read_bytes()).hexdigest()==expected_manifest_hash
 manifest=json.loads(p.read_text(encoding='utf-8-sig'));assert manifest['cutoff']=='2024-12-31' and manifest['complete']
 for row in manifest['files']:
  f=base/row['path'];assert f.resolve().is_relative_to(base.resolve());assert hashlib.sha256(f.read_bytes()).hexdigest()==row['sha256']
 records=json.loads((base/manifest['company_actions_file']).read_text(encoding='utf-8-sig'));coverage=set();response_keys=set()
 for row in manifest['responses']:
  resp=json.loads((base/row['path']).read_text(encoding='utf-8-sig'));assert resp['error_code']=='0';assert resp['key']==row['key'];response_keys.add(row['key'])
  code,year=row['key'].split('/');coverage.add((code.split('.')[0],int(year)))
 assert set(records)==response_keys
 actions=[];uncertain=[]
 for key,rows in records.items():
  code,year=key.split('/');code=code.split('.')[0]
  for i,row in enumerate(rows):
   dates={k:row.get(k,'') for k in row if k.startswith('divid') and k.endswith('Date')}
   assert all(not x or x<='2024-12-31' for x in dates.values())
   val=lambda k:Decimal(str(row.get(k) or '0'))
   cash=val('dividCashPsBeforeTax');bonus=val('dividStocksPs');reserve=val('dividReserveToStockPs')
   if cash==0 and bonus==0 and reserve==0:continue
   reg=row.get('dividRegistDate') or None;ex=row.get('dividOperateDate') or None;pay=row.get('dividPayDate') or None;release=row.get('dividStockMarketDate') or None
   unresolved=[]
   if not reg:unresolved.append('record_date')
   if not ex:unresolved.append('ex_date')
   if cash and not pay:unresolved.append('pay_date')
   if bonus or reserve:
    unresolved.extend(['stock_acquisition_date','taxable_stock_income_ps'])
    if not release:unresolved.append('stock_release_date')
   a=Action(f'{key}:{i}',code,reg,ex,cash,bonus,reserve,pay,release,None,0 if bonus+reserve==0 else None,verified=not unresolved,unresolved_fields=unresolved,evidence='verified_manifest_supplier_response:'+key)
   # Executions with no ex-date cannot be scheduled as if known; retain as unresolved, not silently discard.
   if not ex:uncertain.append({'key':key,'action_id':a.action_id,'code':code,'reason':unresolved,'raw':row})
   else:actions.append(a)
 return actions,coverage,uncertain,manifest
