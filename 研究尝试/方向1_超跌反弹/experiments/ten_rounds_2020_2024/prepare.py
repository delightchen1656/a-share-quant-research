"""No work occurs on import. Run only after parent confirms inputs are frozen.

--freeze: JSON {files:[{path,sha256}],responses:[{path,sha256,key}],
company_actions_file:...}; all paths relative to inputs_pre2025.
--query-plan: frozen input JSON containing planned supplier code/year keys.
Evidence paths resolve inside inputs_pre2025. Explicit empty responses count;
an absent response does not. Coverage describes supplier retrieval, not a claim
that the provider captures every possible historical corporate action.
"""
import argparse, hashlib, importlib.util, json, sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
INPUT=ROOT/'inputs_pre2025'

def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,value): Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
def local(relative):
    p=(INPUT/relative).resolve()
    if INPUT.resolve() not in p.parents or 'holdout_restricted' in p.parts:
        raise ValueError('Input outside whitelist')
    return p
def load_module(name,p):
    spec=importlib.util.spec_from_file_location(name,p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
def number(v): return float(str(v or '').strip() or 0)

def query_keys(plan):
    if isinstance(plan,dict):
        for name in ['requests','queries','keys','plan']:
            if name in plan:return query_keys(plan[name])
        raise ValueError('Unknown QUERY_PLAN schema; adapt interface before running')
    keys=set()
    for item in plan:
        if isinstance(item,str):key=item
        elif 'key' in item:key=item['key']
        else:key=str(item['code'])+'/'+str(item['year'])
        code,year=key.rsplit('/',1);keys.add((code[:6],int(year)))
    return keys

def prepare(freeze_path,query_plan_path):
    frozen=read(local(freeze_path))
    frozen_paths={x['path'] for x in frozen['files']}
    actions_file=frozen['company_actions_file']
    for required in ['MANIFEST.json','calendar.parquet',actions_file,query_plan_path]:
        if required not in frozen_paths: raise ValueError('Missing frozen input '+required)
    for info in frozen['files']:
        if sha(local(info['path']))!=info['sha256']:raise ValueError('Freeze hash mismatch '+info['path'])
    manifest=read(INPUT/'MANIFEST.json')
    if manifest['cutoff']!='2024-12-31':raise ValueError('Wrong data boundary')
    lookup={(x['code'],x['mode']):x for x in manifest['files']}
    codes=sorted({x['code'] for x in manifest['files'] if x['mode']=='raw'})
    if len(codes)!=947:raise ValueError('Unexpected universe')
    covered=set()
    for info in frozen['responses']:
        if info.get('status','success')!='success':raise ValueError('Unsuccessful supplier evidence')
        if sha(local(info['path']))!=info['sha256']:raise ValueError('Supplier evidence hash mismatch')
        code,year=info['key'].rsplit('/',1)
        if int(year)>2024:raise ValueError('Supplier evidence beyond research boundary')
        covered.add((code[:6],int(year)))
    expected=query_keys(read(local(query_plan_path)))|{(c,2020) for c in codes}
    if not expected<=covered:raise ValueError('Missing code/year supplier responses: '+str(sorted(expected-covered)[:20]))
    calendar=pd.read_parquet(INPUT/'calendar.parquet')
    dates=pd.to_datetime(calendar.date).dt.strftime('%Y-%m-%d').tolist()
    if dates!=sorted(set(dates)) or dates[-1]>'2024-12-31':raise ValueError('Invalid calendar')
    ordinal={d:i for i,d in enumerate(dates)}
    structure=load_module('clean_structure',ROOT/'structure.py')
    quotes={};factors={};allraw={};signals=[];missing_plan=set()
    rule=read(ROOT/'RULE.json');excluded={tuple(x) for x in rule['special_events_excluded']}
    for code in codes:
        frames=[]
        for mode in ['raw','qfq']:
            info=lookup[(code,mode)]
            relative=str(Path(info['path']).relative_to('inputs_pre2025'))
            path=local(relative)
            if sha(path)!=info['sha256']:raise ValueError('Market hash mismatch '+code)
            z=pd.read_parquet(path);z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d')
            if z.date.max()>'2024-12-31' or z.date.duplicated().any():raise ValueError('Invalid price boundary/duplicates')
            z=z.sort_values('date').reset_index(drop=True);frames.append(z)
        r,q=frames
        if not r.date.equals(q.date):raise ValueError('Raw/qfq mismatch '+code)
        f,qv,rv=structure.scan(q,r)
        for day in f.loc[f.candidate,'date']:
            if '2020-01-01'<=day<='2024-12-31':
                year=int(day[:4])
                required={(code,year)}
                if day[5:7] in ['11','12'] and year<2024:required.add((code,year+1))
                missing_plan.update(required-expected)
        amount20=rv.amount.shift(1).rolling(20).mean()
        flags=structure.limit_flags(r).set_index('date')
        for i in structure.independent(f.candidate):
            day=f.iloc[i].date
            if not '2020-01-01'<=day<='2024-12-31':continue
            if day not in ordinal:raise ValueError('Signal outside official calendar')
            if flags.loc[day,'reject_consecutive2'] or (code,day) in excluded:continue
            if not (rv.iloc[i].close<8 and f.iloc[i].below_ma20<=-.08):continue
            features={k:float(v) for k,v in f.iloc[i].to_dict().items() if k not in ['date','candidate','q_position']}
            signals.append(dict(code=code,name=code,date=day,is_leader=False,raw_close=float(rv.iloc[i].close),current_amount=float(rv.iloc[i].amount),amount20=float(amount20.iloc[i]),**features))
        rv=rv.set_index('date');qv=qv.set_index('date');allraw[code]=r.set_index('date')
        quotes[code]={row.date:row for row in rv.reset_index().itertuples(index=False)}
        factors[code]=(qv.close/rv.close).to_dict()
    if missing_plan:
        save(HERE/'COVERAGE_GAPS.json',dict(stage='before_any_account_run',missing_plan_keys=sorted([f'{c}/{y}' for c,y in missing_plan]),missing_response_keys=sorted([f'{c}/{y}' for c,y in missing_plan-covered])))
        raise ValueError('QUERY_PLAN misses '+str(len(missing_plan))+' rescanned base-signal code/year pairs; see COVERAGE_GAPS.json')
    actions={};records=read(local(actions_file));action_audit=[]
    for key,rows in records.items():
        code=key[:6]
        if code not in quotes:continue
        grouped={}
        for row in rows:
            day=row.get('dividOperateDate')
            if day and '2020-01-01'<=day<='2024-12-31':grouped.setdefault(day,[]).append(row)
        for day,choices in grouped.items():
            before=[d for d in quotes[code] if d<day]
            previous=float(quotes[code][before[-1]].close) if before else None
            ref=float(allraw[code].loc[day,'preclose']) if day in allraw[code].index else None
            def error(row):
                if previous is None or ref is None:return float('inf')
                stock=number(row.get('dividStocksPs'))+number(row.get('dividReserveToStockPs'))
                return abs((previous-number(row.get('dividCashPsBeforeTax')))/(1+stock)-ref)
            row=min(choices,key=error)
            cash=number(row.get('dividCashPsBeforeTax'));bonus=number(row.get('dividStocksPs'))
            stock=bonus+number(row.get('dividReserveToStockPs'))
            pay=row.get('dividPayDate');release=row.get('dividStockMarketDate')
            issues=[]
            if previous is None:issues.append('missing_previous_price')
            if ref is None:issues.append('missing_action_reference')
            if previous is not None and ref is not None and error(row)>.021:issues.append('bad_reference')
            if cash and not pay:issues.append('missing_payment_date')
            if stock and not release:issues.append('missing_stock_release_date')
            actions[(code,day)]=dict(cash=cash,stock=stock,taxable_stock=bonus,pay=pay or day,release=release or day,reference_error=error(row) if np.isfinite(error(row)) else None,unresolved_fields=issues)
            for candidate in choices:
                action_audit.append(dict(code=code,date=day,source_key=key,selected=(candidate==row),reference_error=error(candidate) if np.isfinite(error(candidate)) else None,unresolved_fields=issues,record=candidate))
    d=pd.DataFrame(signals).sort_values(['date','code'])
    suspended_entries=set();entry_audit=[]
    for event in d.itertuples():
        pos=ordinal[event.date]+1
        if pos>=len(dates):continue
        day=dates[pos]
        if day in quotes[event.code]:continue
        raw=allraw[event.code]
        suspended=day in raw.index and number(raw.loc[day,'tradestatus'])==0
        entry_audit.append(dict(code=event.code,signal_date=event.date,entry_date=day,status='confirmed_snapshot_suspension' if suspended else 'unresolved_missing_entry'))
        if suspended:suspended_entries.add((event.code,day))
    save(HERE/'ENTRY_AVAILABILITY.json',entry_audit)
    if any(r['status']=='unresolved_missing_entry' for r in entry_audit):raise ValueError('Unresolved entry quote gaps; see ENTRY_AVAILABILITY.json')
    d.to_parquet(HERE/'signals_rescanned.parquet',index=False)
    save(HERE/'INPUT_AUDIT.json',dict(universe=len(codes),supplier_response_pairs=len(covered),signals=len(d),actions=action_audit,manifest_sha256=sha(INPUT/'MANIFEST.json'),freeze_sha256=sha(local(freeze_path))))
    return d,dates,ordinal,quotes,factors,actions,covered,suspended_entries
