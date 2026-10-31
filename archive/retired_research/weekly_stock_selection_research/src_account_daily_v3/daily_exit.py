"""User-chosen daily proxy, deliberately not a timestamped execution claim."""
import pandas as pd
import numpy as np
from common import fee
from execution import price_band,band_contradiction

def daily_sell(bar,qty,entry_date,date,exit_due=False,emergency=False):
    date=pd.Timestamp(date)
    due=bool(exit_due or emergency or date.weekday()==1)
    state=dict(exit_due=due,emergency=bool(emergency),triggered_today=False)
    if not due:return None,'not_due',state
    if date<=pd.Timestamp(entry_date):return None,'Tplus1',state
    if not bar.get('active',False):return None,'exit_inactive_or_missing',state
    band=price_band(bar,date)
    if band is None or band_contradiction(bar,date):
        return None,'unknown_or_contradictory_exit_band',state
    if not np.isfinite([bar.get(k,np.nan) for k in ['open','high','low','close']]).all():
        return None,'exit_inactive_or_missing',state
    floor=band['lower']
    touched=date.weekday()==1 and bar['low']<=floor+.004
    state['triggered_today']=bool(touched and not emergency)
    state['emergency']=bool(emergency or touched)
    if qty<=0:return None,'no_listed_shares',state
    if state['emergency']:
        if bar['high']<=floor+.004:return None,'full_session_limit_lock',state
        price=floor
        kind='daily_reopen_floor'
        ambiguous=bool(state['triggered_today'] and bar['open']>floor+.004 and bar['close']<=floor+.004)
    else:
        if bar['close']<=floor+.004:
            state['emergency']=True
            return None,'close_locked_overdue_exit',state
        price=bar['close']
        kind='scheduled_close' if date.weekday()==1 else 'overdue_valid_close'
        ambiguous=False
    value=qty*price
    return dict(qty=qty,price=price,notional=value,fee=fee(value,'sell',date),exit_kind=kind,
                ambiguous_order=ambiguous,outside_daily_range=bool(price<bar['low']-.004 or price>bar['high']+.004)),None,state
