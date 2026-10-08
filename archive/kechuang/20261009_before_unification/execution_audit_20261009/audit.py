from pathlib import Path
import csv, json, re, hashlib
from collections import defaultdict
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SOURCE=HERE/'inputs'
def read(name):
    p=SOURCE/name
    if not p.exists(): p=ROOT/name
    return p
def main():
    trades=list(csv.DictReader(read('detal.csv').open(encoding='utf-8-sig')))
    positions=list(csv.DictReader(read('dailyposition.csv').open(encoding='utf-8-sig')))
    log=read('outlog.txt').read_text(encoding='utf-8-sig')
    snapshots={};date=None
    for r in positions:
        if r['日期']:
            date=r['日期'];snapshots[date]={'nav':float(r['总资产']),'cash':float(r['现金']),'positions':{}}
        elif r['证券']:
            symbol=re.search(r'(\d{6}\.SH)',r['证券']).group(1)
            snapshots[date]['positions'][symbol]={'qty':int(float(r['数量'])),'value':float(r['持仓'])}
    daily=defaultdict(list)
    for idx,r in enumerate(trades,2):
        r['source_line']=idx
        for k in ['成交价','数量','金额','佣金','印花税']:r[k]=float(r[k])
        for k in ['数量','金额']:r[k]=abs(r[k])
        daily[r['日期']].append(r)
    rows=[];checks=[];previous={};previous_cash=500000
    for date,snap in sorted(snapshots.items()):
        tx=daily[date];buys=sum(r['金额'] for r in tx if r['操作']=='买入');sells=sum(r['金额'] for r in tx if r['操作']=='卖出')
        fees=sum(r['佣金']+r['印花税'] for r in tx)
        rows.append({'date':date,'nav':snap['nav'],'cash':snap['cash'],'buy':buys,'sell':sells,'fees':fees,'cash_residual':round(snap['cash']-(previous_cash-buys+sells-fees),2),'nav_residual':round(snap['nav']-snap['cash']-sum(x['value'] for x in snap['positions'].values()),2)})
        symbols=set(previous)|set(snap['positions'])|{r['代码'] for r in tx}
        for symbol in symbols:
            before=previous.get(symbol,{}).get('qty',0);after=snap['positions'].get(symbol,{}).get('qty',0)
            st=[r for r in tx if r['代码']==symbol];b=sum(r['数量'] for r in st if r['操作']=='买入');s=sum(r['数量'] for r in st if r['操作']=='卖出')
            if before+b-s!=after:checks.append({'type':'holding_delta','date':date,'symbol':symbol,'before':before,'buy':b,'sell':s,'after':after,'note':'company actions require reconciliation'})
            if s>before:checks.append({'type':'sell_exceeds_prior_day','date':date,'symbol':symbol,'sell':s,'prior':before})
        previous=snap['positions'];previous_cash=snap['cash']
    audit_dates=set(re.findall(r'(\d{4}-\d{2}-\d{2}) 15:30:00.*EXECUTION_AUDIT buy=0.00 sell=0.00',log))
    small=[r for r in trades if r['操作']=='买入' and r['数量']<200]
    duplicates=len(trades)-len({tuple((k,str(v)) for k,v in r.items() if k!='source_line') for r in trades})
    summary={'trades':len(trades),'days':len(snapshots),'buys':sum(r['操作']=='买入' for r in trades),'sells':sum(r['操作']=='卖出' for r in trades),'buy_value':sum(r['金额'] for r in trades if r['操作']=='买入'),'sell_value':sum(r['金额'] for r in trades if r['操作']=='卖出'),'fees':sum(r['佣金']+r['印花税'] for r in trades),'final_nav':rows[-1]['nav'],'return':rows[-1]['nav']/500000-1,'small_buys':small,'duplicate_rows':duplicates,'zero_audit_with_trades':len(audit_dates & {d for d,t in daily.items() if t}),'holding_checks':checks,'nav_residual_max':max(abs(r['nav_residual']) for r in rows),'cash_residual_sum':sum(r['cash_residual'] for r in rows),'cash_residual_days':[r for r in rows if abs(r['cash_residual'])>.1],'warnings':sorted(set(l for l in log.splitlines() if 'WARN' in l)),'limitations':['No order IDs or submission sizes in exported trades; sub200 fill alone cannot distinguish partial fill from illegal submission.','Cash residuals include corporate actions and taxes; not automatically errors.','Daily data cannot prove intraday queue/limit tradability.']}
    (HERE/'audit_results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (HERE/'daily_reconciliation.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ['cash_residual_days','warnings','small_buys']},ensure_ascii=True,indent=2))
if __name__=='__main__':main()
