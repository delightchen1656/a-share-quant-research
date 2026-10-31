import math
import numpy as np
import pandas as pd

def aggregate(daily):
    rows=[]
    prior=1e6
    for year,g in daily.groupby(pd.to_datetime(daily.date).dt.year):
        curve=np.r_[prior,g.equity.to_numpy()]
        rows.append(dict(year=int(year),annual_return=float(g.equity.iloc[-1]/prior-1),
                         maximum_drawdown=float((1-curve/np.maximum.accumulate(curve)).max()),
                         end_equity=float(g.equity.iloc[-1])))
        prior=g.equity.iloc[-1]
    curve=np.r_[1e6,daily.equity.to_numpy()]
    initial_day=pd.Timestamp(f'{pd.Timestamp(daily.date.iloc[0]).year}-01-01')-pd.Timedelta(days=1)
    elapsed=(pd.Timestamp(daily.date.iloc[-1])-initial_day).days
    return pd.DataFrame(rows),dict(cagr=float((daily.equity.iloc[-1]/1e6)**(365.25/elapsed)-1),
             cumulative_return=float(daily.equity.iloc[-1]/1e6-1),maximum_drawdown=float((1-curve/np.maximum.accumulate(curve)).max()),
             end_equity=float(daily.equity.iloc[-1]))



def independent_account(result,events,quotes):
    tx=result['transactions']
    trades=result['trades']
    daily=result['daily']
    transactions={d:g for d,g in tx.groupby('date')}
    records={}
    exdates={}
    for e in events:
        if e.get('supported'):
            records.setdefault(e['register_date'],[]).append(e)
            exdates.setdefault(e['ex_date'],[]).append(e)
    listed={}
    pending=[]
    claims=[]
    marks={}
    cash=1e6
    for row in daily.itertuples():
        cash_due_today=0.
        day=row.date
        i=int(quotes.days.get_loc(pd.Timestamp(day)))
        for e in exdates.get(day,[]):
            for c in claims:
                if c['event_id']==e['event_id'] and not c['booked']:
                    c['booked']=True
                    if c['extra']:
                        pending.append(dict(key=c['key'],qty=c['extra'],listing=e['listing_date']))
            s=e['symbol']
            if s in marks and not quotes.bar(s,i)['active']:
                marks[s]=(marks[s]-e['cash_ps'])/(1+e['bonus_ps']+e['transfer_ps'])
        for p in pending:
            if p['listing']<=day and not p.get('credited',False):
                listed[p['key']]=listed.get(p['key'],0)+p['qty']
                p['credited']=True
        for c in claims:
            if c['booked'] and not c['paid'] and c['pay']<=day:
                cash_due_today+=c['cash']
                c['paid']=True
        if day in transactions:
            for t in transactions[day].itertuples():
                key=(t.symbol,t.trade_id)
                if t.side=='buy':
                    listed[key]=listed.get(key,0)+t.qty
                    cash-=t.notional+t.fee
                else:
                    listed[key]-=t.qty
                    assert listed[key]>=0
                    cash+=t.notional-t.fee
        for e in records.get(day,[]):
            for key,qty in listed.items():
                if key[0]==e['symbol'] and qty>0:
                    extra=qty*(e['bonus_ps']+e['transfer_ps'])
                    if abs(extra-round(extra))>1e-7:
                        continue
                    claims.append(dict(key=key,event_id=e['event_id'],cash=qty*e['cash_ps'],extra=int(round(extra)),
                                       pay=e['pay_date'],booked=False,paid=False))
        cash+=cash_due_today
        symbols={k[0] for k,q in listed.items() if q>0}|{p['key'][0] for p in pending if not p.get('credited',False)}
        for s in symbols:
            bar=quotes.bar(s,i)
            if bar['active']:
                marks[s]=bar['close']
        inventory=sum(q*marks[k[0]] for k,q in listed.items() if q>0)
        inventory+=sum(p['qty']*marks[p['key'][0]] for p in pending if not p.get('credited',False))
        receivable=sum(c['cash'] for c in claims if c['booked'] and not c['paid'])
        np.testing.assert_allclose([cash,inventory,receivable,cash+inventory+receivable],
                                   [row.cash,row.inventory,row.cash_receivable,row.equity],atol=1e-5,rtol=1e-11)
    assert math.isclose(trades.pnl.sum(),daily.equity.iloc[-1]-1e6,abs_tol=1e-5)

