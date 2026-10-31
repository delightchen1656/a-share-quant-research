from pathlib import Path
import json
import numpy as np
import pandas as pd
END=pd.Timestamp('2026-09-30')
CASH=500000.
OUT=Path(__file__).resolve().parents[1]/'results/latest'
def old_exit(price,state,amount,today,position_days):
    entry=state['entry']
    if price<=entry*.93:return 'STOP',0
    if price>=entry*1.34:return 'TPALL',0
    if price>=entry*1.24 and not state['half']:
        target=int(amount/2)
        return ('TPHALF',target) if target>=200 and amount-target>=200 else None
    age=(today-state['entry_date']).days if state['entry_date'] is not None else position_days
    if age>=60:return 'TIME60',0
    if age>=30 and price/entry-1<.10:return 'TIME30',0
    return None
def dump(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def actions(requests):
    import baostock as bs
    path=OUT/'corporate_actions.json'
    cache=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    missing=[(s,y) for s,y in sorted(requests) if s+'/'+str(y) not in cache]
    if missing:
        if bs.login().error_code!='0': raise RuntimeError('BaoStock login')
        try:
            for i,(s,y) in enumerate(missing):
                r=bs.query_dividend_data(code='sh.'+s[:6],year=str(y),yearType='operate')
                if r.error_code!='0': raise RuntimeError(r.error_msg)
                cache[s+'/'+str(y)]=r.get_data().to_dict('records')
                if i%20==0:
                    dump(path,cache); print('ACTIONS',i,'/',len(missing),flush=True)
            dump(path,cache)
        finally: bs.logout()
    result={}
    def num(v): return float(v) if str(v).strip() else 0.
    for key,rows in cache.items():
        s=key.split('/')[0]
        for row in rows:
            if not row['dividOperateDate']: continue
            d=pd.Timestamp(row['dividOperateDate'])
            result[(s,d)]={'cash':num(row['dividCashPsBeforeTax']),
                'stock':num(row['dividStocksPs'])+num(row['dividReserveToStockPs']),
                'pay':pd.Timestamp(row['dividPayDate'] or row['dividOperateDate']),
                'stock_day':pd.Timestamp(row['dividStockMarketDate'] or row['dividOperateDate'])}
    return result

def run_starts(prep, action_map, requested_start):
    ns,models,dates,panels,candidates,meta,_=prep
    # Fast immutable day dictionaries; rows use native attribute access.
    days={d:{} for d in dates}
    for s,p in panels.items():
        for row in p.loc[dates[0]:END].itertuples():
            if row.Index in days: days[row.Index][s]=row
    starts=dates[dates>=pd.Timestamp(requested_start)][:1]
    all_curves,results,all_trades=[],[],[]
    reference_differences={}
    for start in starts:
        cash=CASH; holdings={}; curve=[]; trades=[]; receivables=[]; action_issues=[]; capacity_hits=0
        for di,date in enumerate(dates):
            if date<start: continue
            day=days[date]; prev=dates[di-1]; prevday=days[prev]
            # Credit cash / release bonus shares on actual vendor dates.
            still=[]
            for pay,amount in receivables:
                if pay<=date: cash+=amount
                else: still.append((pay,amount))
            receivables=still
            for s,pos in list(holdings.items()):
                row=day.get(s)
                for release,qty in list(pos['locked']):
                    if release<=date: pos['locked'].remove((release,qty))
                action=action_map.get((s,date))
                if action:
                    old=pos['qty']; amount=old*action['cash']*.8
                    if action['pay']<=date: cash+=amount
                    else: receivables.append((action['pay'],amount))
                    bonus=int(np.floor(old*action['stock']+1e-8))
                    pos['qty']+=bonus
                    if action['stock_day']>date: pos['locked'].append((action['stock_day'],bonus))
                    # Mark old close ex-action before open NAV/order sizing.
                    if row is not None: pos['last']=float(row.preclose)
                if row is not None and np.isfinite(row.adjust_ratio) and abs(row.adjust_ratio-1)>1e-5:
                    if not action: action_issues.append([s,str(date.date()),row.adjust_ratio])
                    elif abs(row.preclose-(row.prev_actual-action['cash'])/(1+action['stock'])) > max(.025,row.preclose*.0001):
                        # Differential distributions can legitimately use a virtual
                        # exchange reference distinct from actual shareholder payouts.
                        reference_differences[s+'/'+str(date.date())]={'preclose':float(row.preclose),'previous_close':float(row.prev_actual),'cash_per_share':action['cash'],'bonus_per_share':action['stock']}
                    pos['state']['entry']*=row.adjust_ratio
                out=pd.to_datetime(meta.loc[s,'outDate'],errors='coerce')
                if pd.notna(out) and date>=out:
                    trades.append({'date':date,'symbol':s,'side':'WRITE_OFF','qty':pos['qty'],'price':0,'amount':0})
                    del holdings[s]
            def equity(use_open=False):
                return cash+sum(a for _,a in receivables)+sum(p['qty']*(float(day[s].open) if use_open and s in day and day[s].open>0 else p['last']) for s,p in holdings.items())
            used={}
            def tradable(s,buy):
                r=day.get(s)
                if r is None or str(r.tradestatus)!='1' or r.volume<=0 or r.open<=0: return False
                limit=1.2 if buy else .8
                px=np.floor(r.preclose*limit*100+.5)/100
                return r.open < px-.001 if buy else r.open > px+.001
            for s in candidates.get(prev,[]):
                if len(holdings)>=models[0]['max_positions']: break
                if s in holdings or not tradable(s,True): continue
                r=day[s]; px=min(r.open*1.002,np.floor(r.preclose*1.2*100+.5)/100)
                nav=equity(True)
                fraction=max(.10,float(r.open)*200*1.01/nav)
                if fraction>.20:continue
                reserve=nav*fraction*1.005
                if cash<reserve:continue
                desired=int(nav*fraction/px)
                cap=min(50000,max(0,int(r.volume*.25)-used.get(s,0)))
                affordable=int(max(0,cash-5)/(px*1.0003))
                qty=min(desired,cap,affordable)
                if desired>cap: capacity_hits+=1
                if qty<200: continue
                amt=qty*px; fee=max(5,amt*.0003)
                if amt+fee>cash+1e-8: continue
                cash-=amt+fee; used[s]=used.get(s,0)+qty
                holdings[s]={'qty':qty,'last':float(r.open),'locked':[],
                     'state':{'entry':px,'half':False,'entry_date':date.date()}}
                trades.append({'date':date,'symbol':s,'side':'BUY','qty':qty,'price':px,'amount':amt,'fee':fee})
            for s,pos in list(holdings.items()):
                if pos['state']['entry_date']==date.date() or s not in prevday or not tradable(s,False): continue
                r=day[s]
                signal=float(r.open)
                dec=ns['_exit_action'](signal,pos['state'],pos['qty'],date.date(),0)
                if dec is None: continue
                sellable=pos['qty']-sum(q for _,q in pos['locked'])
                req=pos['qty']-dec[1]
                cap=min(50000,max(0,int(r.volume*.25)-used.get(s,0)))
                qty=min(req,sellable,cap)
                if req>cap: capacity_hits+=1
                if qty<=0 or (qty<200 and qty!=sellable): continue
                px=max(r.open*.998,np.floor(r.preclose*.8*100+.5)/100)
                amt=qty*px;fee=max(5,amt*.0003)+amt*.001
                cash+=amt-fee;pos['qty']-=qty;used[s]=used.get(s,0)+qty
                if dec[0]=='TPHALF':pos['state']['half']=True
                trades.append({'date':date,'symbol':s,'side':dec[0],'qty':qty,'price':px,'amount':amt,'fee':fee})
                if pos['qty']==0:del holdings[s]
            for s,p in holdings.items():
                if s in day and day[s].close>0:p['last']=float(day[s].close)
            if cash < -.01:raise AssertionError('negative cash')
            eq=equity();curve.append({'date':date,'equity':eq,'cash':cash,'positions':len(holdings),'exposure':sum(p['qty']*p['last'] for p in holdings.values())/eq})
        if action_issues:
            dump(OUT/'unresolved_actions.json',action_issues)
            raise ValueError('Unresolved held corporate actions '+str(action_issues[:5]))
        c=pd.DataFrame(curve);nav=c.equity/CASH
        ret=c.equity.pct_change();ret.iloc[0]=nav.iloc[0]-1
        years=(END-start).days/365.25
        dd=nav/np.maximum.accumulate(np.r_[1,nav.to_numpy()])[1:]-1
        result={'start':str(start.date()),'end':str(END.date()),'final_asset':float(c.equity.iloc[-1]),
                'total_return':float(nav.iloc[-1]-1),'cagr':float(nav.iloc[-1]**(1/years)-1),
                'max_drawdown':float(dd.min()),'sharpe_rf0':float(ret.mean()/ret.std()*np.sqrt(252)),
                'avg_exposure':float(c.exposure.mean()),'fills':len(trades),'capacity_capped_orders':capacity_hits}
        results.append(result);c['start']=result['start'];all_curves.append(c)
        for t in trades:t['start']=result['start']
        all_trades.extend(trades)
        print('RUN',len(results),'/',len(starts),result['start'],'CAGR',round(result['cagr'],4),flush=True)
    return results[0],all_curves[0],pd.DataFrame(all_trades),reference_differences
