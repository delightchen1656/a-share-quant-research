"""Execution primitives for the independent weekly study; no prior strategy code."""
import math
import numpy as np
import pandas as pd
from common import fee,tick


def active_bar(bar):
    return bool(bar.get('active',False))


def buy_order(bar,target_cash,cash,prior_volume,date):
    if not active_bar(bar) or not np.isfinite(bar.get('open',np.nan)) or bar['open']<=0:
        return None,'entry_inactive_or_missing'
    if bar.get('st',True):
        return None,'entry_ST'
    upper=tick(bar['preclose']*1.10)
    if bar['open']>=upper-.004:
        return None,'opening_upper_limit_no_fill_assumption'
    budget=min(float(target_cash),float(cash))
    price=bar['open']
    qty=int(budget/price//100)*100
    while qty>0 and qty*price+fee(qty*price,'buy',date)>budget:
        qty-=100
    if qty<=0:
        return None,'insufficient_lot_cash'
    if qty>max(prior_volume,0)*.01:
        return None,'entry_prior_volume_capacity'
    return dict(qty=qty,price=price,notional=qty*price,fee=fee(qty*price,'buy',date)),None


def sell_order(bar,qty,entry_date,prior_volume,date):
    if pd.Timestamp(date).weekday()!=1:
        return None,'not_Tuesday'
    if pd.Timestamp(date)<=pd.Timestamp(entry_date):
        return None,'Tplus1'
    if qty<=0:
        return None,'no_listed_shares'
    if not active_bar(bar) or not np.isfinite(bar.get('close',np.nan)) or bar['close']<=0:
        return None,'exit_inactive_or_missing'
    lower=tick(bar['preclose']*(.95 if bar.get('st',False) else .90))
    if bar['close']<=lower+.004:
        return None,'closing_lower_limit_no_fill_assumption'
    if qty>max(prior_volume,0)*.01:
        return None,'exit_prior_volume_capacity'
    price=bar['close']
    return dict(qty=qty,price=price,notional=qty*price,fee=fee(qty*price,'sell',date)),None


def entitlement(qty,cash_ps,bonus_ps,transfer_ps):
    shares=float(qty)*(float(bonus_ps)+float(transfer_ps))
    if abs(shares-round(shares))>1e-7:
        raise ValueError('fractional_share_allocation_unverified')
    return dict(cash=float(qty)*float(cash_ps),extra_shares=int(round(shares)))


def ordinary_label(entry_open,exit_close,entry_active,exit_active,mon_close,tue_preclose,market_return):
    if not entry_active or not exit_active:
        return np.nan
    if not np.isfinite(entry_open) or entry_open<=0 or abs(mon_close-tue_preclose)>.015:
        return np.nan
    return exit_close/entry_open-1-market_return
