"""Independent weekly portfolio accounting, supports conditional ordinary actions."""
from functools import lru_cache
import json
import math
import numpy as np
import pandas as pd
from common import BASE,AUDIT,SPEC,quote_valid
from execution import plan_buy,fill_buy,sell_order,entitlement,price_band,band_contradiction,economic_terms,reference_terms,reference_adjust


class Quotes:
    def __init__(self):
        cal=pd.read_parquet(BASE/'inputs_pre2025/calendar_dev_v1.parquet')
        self.days=pd.DatetimeIndex(cal.loc[cal.is_trading_day.eq(1),'calendar_date'])
        self.fields=['open','high','low','close','volume','amount','preclose','pctChg']
    @lru_cache(maxsize=3400)
    def arrays(self,symbol):
        frame=pd.read_parquet(BASE/'inputs_pre2025/kline_dev_v1'/f'{symbol}.parquet').set_index('date').reindex(self.days)
        active,num=quote_valid(frame)
        return num.to_numpy(float),active.to_numpy(),frame.isST.astype(str).ne('0').to_numpy(),frame.tradestatus.astype(str).to_numpy()
    def bar(self,symbol,i):
        if i<0:
            return dict(active=False,st=True,status='missing',**{f:np.nan for f in self.fields})
        values,active,st,status=self.arrays(symbol)
        return dict(zip(self.fields,values[i]))|dict(active=bool(active[i]),st=bool(st[i]),status=status[i])


def simulate(method,scores,quotes,events,plan=None,start=None,end=None):
    days=quotes.days
    selected=scores.loc[scores.method.eq(method)&scores['rank'].le(10)]
    rank_by_mon={pd.Timestamp(d):g.sort_values('rank').symbol.tolist() for d,g in selected.groupby('monday')}
    if plan is None:
        plan=pd.read_parquet(AUDIT/'weekly_schedule.parquet')
    start=pd.Timestamp(start or SPEC['execution_start'])
    end=pd.Timestamp(end or SPEC['execution_end'])
    signal_by_date={pd.Timestamp(r.signal_date):pd.Timestamp(r.monday) for r in plan.loc[pd.to_datetime(plan.monday).between(start,end)].itertuples()}
    event_by_ex={}
    event_by_record={}
    for event in events:
        event_by_ex.setdefault(event['ex_date'],[]).append(event)
        if event.get('supported'):
            event_by_record.setdefault(event['register_date'],[]).append(event)
    positions={}
    transactions=[]
    planned_orders=[]
    trade_records=[]
    claims=[]
    cash=1e6
    allocations={}
    daily=[]
    logs=[]
    requested=set()
    bad=[]
    unknown=False
    def log(date,kind,**kw):
        logs.append(dict(method=method,date=str(date.date()),kind=kind,**kw))
    for i,date in enumerate(days):
        if date<start or date>end:
            continue
        key=str(date.date())
        cash_due_today=0.
        previous_marks={s:p['mark'] for s,p in positions.items()}
        # Exdate entitlements were fixed by holdings after the register close.
        for event in event_by_ex.get(key,[]):
            s=event['symbol']
            if s in positions and not event.get('supported'):
                unknown=True
                bad.append(dict(symbol=s,date=key,reason=event['reason']))
            for claim in claims:
                if claim['event_id']!=event['event_id'] or claim['booked']:
                    continue
                claim['booked']=True
                trade=trade_records[claim['trade_id']]
                trade['gross_dividend']+=claim['gross_cash']
                if claim['extra_shares']:
                    if s not in positions:
                        unknown=True
                        bad.append(dict(symbol=s,date=key,reason='share_entitlement_without_open_trade_state'))
                    else:
                        p=positions[s]
                        if event['listing_date']<=key:
                            p['qty']+=claim['extra_shares']
                        else:
                            p['unlisted'].append(dict(qty=claim['extra_shares'],listing_date=event['listing_date']))
                        trade['entitled_extra_shares']+=claim['extra_shares']
                log(date,'exdate_entitlement',symbol=s,cash=claim['gross_cash'],extra_shares=claim['extra_shares'])
            if s in positions and event.get('supported') and not quotes.bar(s,i)['active']:
                p=positions[s]
                p['mark']=reference_adjust(p['mark'],event)
        for claim in claims:
            if claim['booked'] and not claim['paid'] and claim['pay_date']<=key:
                cash_due_today+=claim['gross_cash']
                claim['paid']=True
                log(date,'dividend_cash_payment',symbol=claim['symbol'],amount=claim['gross_cash'])
        for s,p in list(positions.items()):
            requested.add((s,date.year))
            now_listed=[x for x in p['unlisted'] if x['listing_date']<=key]
            p['qty']+=sum(x['qty'] for x in now_listed)
            p['unlisted']=[x for x in p['unlisted'] if x['listing_date']>key]
            bar=quotes.bar(s,i)
            band_bad=band_contradiction(bar,date)
            if band_bad:
                unknown=True
                bad.append(dict(symbol=s,date=key,reason=band_bad))
            if bar['active']:
                old_mark=previous_marks.get(s,p['mark'])
                today=[e for e in event_by_ex.get(key,[]) if e['symbol']==s and e.get('supported')]
                cash_ps=sum(reference_terms(e)[0] for e in today)
                factor=np.prod([reference_terms(e)[1] for e in today]) if today else 1.
                expected=(old_mark-cash_ps)/factor
                gap=bar['preclose']-expected
                if abs(gap)>.015:
                    unknown=True
                    bad.append(dict(symbol=s,date=key,reason='unresolved_held_reference_change',difference=gap))
                p['mark']=bar['close']
            elif bar['status']!='0':
                unknown=True
                bad.append(dict(symbol=s,date=key,reason='held_missing_quote_not_verified_suspension'))
        if date in rank_by_mon:
            free=10-len(positions)
            orders=[s for s in rank_by_mon[date] if s not in positions][:free]
            target=allocations.get(date,cash/10)
            available=cash
            plans=[]
            # Budget buckets are reserved before final auction price/fill is read.
            for s in orders:
                budget=min(target,available)
                available-=budget
                bar=quotes.bar(s,i)
                previous=quotes.bar(s,i-1)
                order,reason=plan_buy(bar,budget,previous['volume'] if previous['active'] else 0,date)
                planned_orders.append(dict(method=method,date=key,symbol=s,budget=budget,
                    qty=order['qty'] if order else 0,limit_price=order['limit_price'] if order else None,
                    preclose=bar.get('preclose'),prior_volume=previous.get('volume'),status='planned' if order else 'cancelled_preopen',reason=reason))
                if order is None:
                    log(date,'buy_cancelled',symbol=s,reason=reason)
                else:
                    plans.append((s,order))
            for s,order in plans:
                bar=quotes.bar(s,i)
                fill,reason=fill_buy(order,bar,date)
                if fill is None:
                    log(date,'buy_cancelled',symbol=s,reason=reason)
                    continue
                cash-=fill['notional']+fill['fee']
                tid=len(trade_records)
                trade_records.append(dict(method=method,symbol=s,entry_date=key,entry_price=fill['price'],entry_qty=fill['qty'],
                    entry_notional=fill['notional'],entry_fee=fill['fee'],exit_notional=0.,exit_fee=0.,sold_shares=0,
                    gross_dividend=0.,entitled_extra_shares=0,status='open',exit_date=None))
                band_bad=band_contradiction(bar,date)
                if band_bad:
                    unknown=True
                    bad.append(dict(symbol=s,date=key,reason=band_bad))
                positions[s]=dict(qty=fill['qty'],unlisted=[],mark=bar['close'] if bar['active'] else fill['price'],trade_id=tid,entry_date=key)
                requested.add((s,date.year))
                transactions.append(dict(method=method,date=key,symbol=s,side='buy',trade_id=tid,**fill))
                log(date,'buy',symbol=s,qty=fill['qty'],price=fill['price'])
        if date.weekday()==1:
            for s,p in list(positions.items()):
                bar=quotes.bar(s,i)
                previous=quotes.bar(s,i-1)
                fill,reason=sell_order(bar,p['qty'],p['entry_date'],previous['volume'] if previous['active'] else 0,date)
                if fill is None:
                    log(date,'sell_delayed',symbol=s,reason=reason)
                    continue
                cash+=fill['notional']-fill['fee']
                trade=trade_records[p['trade_id']]
                trade['exit_notional']+=fill['notional']
                trade['exit_fee']+=fill['fee']
                trade['sold_shares']+=fill['qty']
                p['qty']=0
                transactions.append(dict(method=method,date=key,symbol=s,side='sell',trade_id=p['trade_id'],**fill))
                log(date,'sell',symbol=s,qty=fill['qty'],price=fill['price'])
                if not p['unlisted']:
                    trade.update(status='closed',exit_date=key)
                    del positions[s]
        # Record-close ownership, after any scheduled close sale.
        for event in event_by_record.get(key,[]):
            s=event['symbol']
            if s not in positions:
                continue
            p=positions[s]
            if p['unlisted']:
                unknown=True
                bad.append(dict(symbol=s,date=key,reason='nested_unlisted_share_entitlement'))
            try:
                amounts=entitlement(p['qty'],*economic_terms(event))
            except ValueError as exc:
                unknown=True
                bad.append(dict(symbol=s,date=key,reason=str(exc)))
                continue
            claims.append(dict(symbol=s,event_id=event['event_id'],trade_id=p['trade_id'],gross_cash=amounts['cash'],
                               extra_shares=amounts['extra_shares'],pay_date=event['pay_date'],booked=False,paid=False))
        cash+=cash_due_today
        inventory=sum((p['qty']+sum(x['qty'] for x in p['unlisted']))*p['mark'] for p in positions.values())
        receivable=sum(c['gross_cash'] for c in claims if c['booked'] and not c['paid'])
        nav=cash+inventory+receivable
        assert cash>=-1e-6 and len(positions)<=10,(method,key,cash,len(positions))
        if date in signal_by_date:
            allocations[signal_by_date[date]]=nav/10
        daily.append(dict(method=method,date=key,cash=cash,inventory=inventory,cash_receivable=receivable,equity=nav,
                          positions=len(positions),unknown=unknown,holdings=';'.join(sorted(positions))))
    for s,p in positions.items():
        trade_records[p['trade_id']]['end_share_value']=(p['qty']+sum(x['qty'] for x in p['unlisted']))*p['mark']
    for t in trade_records:
        t['pnl']=t['exit_notional']-t['exit_fee']+t.get('end_share_value',0)+t['gross_dividend']-t['entry_notional']-t['entry_fee']
    assert math.isclose(daily[-1]['equity']-1e6,sum(t['pnl'] for t in trade_records),abs_tol=1e-5),(method,daily[-1]['equity'],sum(t['pnl'] for t in trade_records))
    return dict(daily=pd.DataFrame(daily),trades=pd.DataFrame(trade_records),transactions=pd.DataFrame(transactions),logs=pd.DataFrame(logs),
                requested=sorted(requested),bad=bad,complete=not unknown,plans=pd.DataFrame(planned_orders))
