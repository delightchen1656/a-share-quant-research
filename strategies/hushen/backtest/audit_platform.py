"""Read-only audit of three preserved SuperMind exports; no eval of uploaded code."""
from pathlib import Path
import csv,json,re,ast,collections,hashlib,html
ROOT=Path(__file__).resolve().parents[3]
OUT=ROOT/'strategies/hushen/results/platform_20261009'
IN=OUT/'inputs';OUT.mkdir(parents=True,exist_ok=True);IN.mkdir(exist_ok=True)
def rows(name):
    return list(csv.DictReader((IN/name).read_text(encoding='utf-8-sig').splitlines()))
def parse(line):
    v=line[line.index('({')+1:line.rindex(')')]
    v=re.sub(r'DateTime\([^)]*\)',lambda m:repr(m.group()),v)
    v=re.sub(r'\b(?:SIDE|ORDER_TYPE|ORDER_STATUS)\.([A-Z_]+)',lambda m:repr(m.group(1)),v)
    return ast.literal_eval(v)
tr=rows('detal.csv');positions=rows('dailyposition.csv');logs=(IN/'outlog.txt').read_text(encoding='utf-8-sig').splitlines()
fills=[];orders=[]
for line_no,line in enumerate(logs,1):
    if 'INFOFILL Trade({' in line:fills.append(dict(parse(line),date=line[:10],line=line_no))
    if 'INFOORDER Order({' in line:orders.append(dict(parse(line),date=line[:10],line=line_no))
fm=collections.defaultdict(list)
for f in fills:fm[(f['date'],f['order_book_id'],f['side'],f['last_quantity'])].append(f)
checks=[]
for i,t in enumerate(tr,2):
    qty=int(float(t['数量']));price=float(t['成交价']);value=abs(qty)*price;side='BUY' if qty>0 else 'SELL'
    match=fm[(t['日期'],t['代码'],side,abs(qty))]
    issue=[]
    if len(match)!=1:issue.append('fill_match_count='+str(len(match)))
    if abs(float(t['金额'])-qty*price)>.011:issue.append('amount')
    if qty>0 and qty%100:issue.append('buy_lot')
    if abs(float(t['佣金'])-max(5,value*.0003))>.011:issue.append('commission')
    tax=value*.0005 if qty<0 else 0
    if abs(float(t['印花税'])-tax)>.011:issue.append('stamp_rate')
    if len(match)==1:
        f=match[0]
        for name,key in [('成交价','last_price'),('佣金','commission'),('印花税','tax')]:
            if abs(float(t[name])-float(f[key]))>.011:issue.append('log_'+key)
        if (qty>0 and price>f['frozen_price']+1e-7) or (qty<0 and price<f['frozen_price']-1e-7):issue.append('limit_breach')
    checks.append(dict(csv_row=i,date=t['日期'],symbol=t['代码'],qty=qty,expected_stamp=round(tax,2),platform_stamp=float(t['印花税']),issues=issue))
snaps={};current=None
for i,r in enumerate(positions,2):
    if r['日期']:
        current=r['日期'];snaps[current]=dict(nav=float(r['总资产']),cash=float(r['现金']),holdings={},line=i)
    elif r['证券']:
        s=re.search(r'\(([^)]+)\)',r['证券']).group(1)
        snaps[current]['holdings'][s]=dict(qty=int(float(r['数量'])),value=float(r['持仓']),close=float(r['收盘价']))
daily=[];prior={};cash=100000.
for date,snap in sorted(snaps.items()):
    expected={s:v['qty'] for s,v in prior.items()};sellable=expected.copy();issues=[]
    day=[f for f in fills if f['date']==date];flow=0
    for f in day:
        q=int(f['last_quantity'])*(1 if f['side']=='BUY' else -1);s=f['order_book_id']
        if q<0:
            if -q>sellable.get(s,0):issues.append('T1_or_corporate_action:'+s)
            sellable[s]=sellable.get(s,0)+q
        expected[s]=expected.get(s,0)+q
        flow-=q*f['last_price']+f['commission']+f['tax']
    actual={s:v['qty'] for s,v in snap['holdings'].items()}
    quantity_diff={s:actual.get(s,0)-expected.get(s,0) for s in actual.keys()|expected.keys() if actual.get(s,0)!=expected.get(s,0)}
    mv=sum(v['value'] for v in snap['holdings'].values());identity=snap['nav']-snap['cash']-mv
    badmarks=[s for s,v in snap['holdings'].items() if abs(v['qty']*v['close']-v['value'])>.021]
    daily.append(dict(date=date,nav=snap['nav'],cash=snap['cash'],nav_residual=round(identity,6),quantity_changes_not_in_trades=quantity_diff,cash_nontrade_change=round(snap['cash']-cash-flow,6),mark_errors=badmarks,issues=issues))
    prior=snap['holdings'];cash=snap['cash']
ids=collections.Counter(f['exec_id'] for f in fills);orderids=collections.Counter(f['order_id'] for f in fills)
summary=dict(trades=len(tr),fills=len(fills),days=len(snaps),orders=len({o['order_id'] for o in orders}),duplicate_exec_ids=[i for i,n in ids.items() if n>1],failed_orders=[o for o in orders if o['status'] in ('REJECTED','CANCELLED')],issues=dict(collections.Counter(v for c in checks for v in c['issues'])),commission=sum(f['commission'] for f in fills),platform_stamp=sum(f['tax'] for f in fills),expected_stamp=sum(f['last_price']*f['last_quantity']*.0005 for f in fills if f['side']=='SELL'),final=snaps[max(snaps)],cash_events=[d for d in daily if abs(d['cash_nontrade_change'])>.03],quantity_events=[d for d in daily if d['quantity_changes_not_in_trades']],nav_errors=[d for d in daily if abs(d['nav_residual'])>.03 or d['mark_errors']],t1_flags=[d for d in daily if d['issues']],runtime_errors=[l for l in logs if 'ERROR' in l or 'ALPHA FAILED' in l])
(OUT/'audit.json').write_text(json.dumps(dict(summary=summary,trade_checks=checks,daily_checks=daily),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
