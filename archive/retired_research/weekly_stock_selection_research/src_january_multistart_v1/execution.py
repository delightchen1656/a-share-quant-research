"""Causal pre-auction sizing; historical conditional legal price bands."""
import numpy as np
import pandas as pd
from common import fee,tick


def price_band(bar,date):
    if not pd.Timestamp('2018-01-01')<=pd.Timestamp(date)<=pd.Timestamp('2026-12-31'):
        return None
    pre=bar.get('preclose',np.nan)
    if not np.isfinite(pre) or pre<=0:
        return None
    # Date-specific mainboard risk-warning transition; future auditor verifies
    # against official effective-date rules before replay, never a fitted threshold.
    rate=.05 if bar.get('st',False) and pd.Timestamp(date)<pd.Timestamp('2026-07-06') else .10
    lower=tick(pre*(1-rate))
    upper=tick(pre*(1+rate))
    if lower<=0 or upper<=lower:
        return None
    return dict(lower=lower,upper=upper,tick=.01,rate=rate,
                scope='conditional_mainboard_rule_reconstruction_not_certified_exchange_feed')


def band_contradiction(bar,date):
    band=price_band(bar,date)
    if band is None:
        return 'missing_or_unverified_price_band'
    if bar.get('active',False):
        if bar.get('high',-np.inf)>band['upper']+.015 or bar.get('low',np.inf)<band['lower']-.015:
            return 'observed_extreme_contradicts_ordinary_band_or_special_session'
    return None


def plan_buy(bar,budget,prior_volume,date):
    # Deliberately never inspect final open/high/low/close/volume or amount here.
    if pd.Timestamp(date).weekday()!=0:
        return None,'not_Monday'
    if bar.get('status')!='1':
        return None,'preopen_status_missing_or_inactive'
    if bar.get('st',True):
        return None,'preopen_ST'
    band=price_band(bar,date)
    if band is None:
        return None,'unknown_preopen_band'
    limit=tick(band['upper']-band['tick'])
    qty=int(max(float(budget),0)/limit//100)*100
    while qty>0 and qty*limit+fee(qty*limit,'buy',date)>budget:
        qty-=100
    if qty<=0:
        return None,'insufficient_lot_cash'
    if not np.isfinite(prior_volume) or qty>max(prior_volume,0)*.01:
        return None,'entry_prior_volume_capacity'
    return dict(qty=qty,limit_price=limit,budget=float(budget),reserved_cost=qty*limit+fee(qty*limit,'buy',date)),None


def fill_buy(order,bar,date):
    opening=bar.get('open',np.nan)
    if not bar.get('active',False) or not np.isfinite(opening) or opening<=0:
        return None,'opening_quote_unavailable'
    band=price_band(bar,date)
    if band is None or opening<band['lower']-.004 or opening>order['limit_price']+.004:
        return None,'opening_outside_limit_or_unsupported_session'
    notional=order['qty']*opening
    cost=fee(notional,'buy',date)
    assert notional+cost<=order['budget']+1e-6
    return dict(qty=order['qty'],price=opening,notional=notional,fee=cost),None


def sell_order(bar,qty,entry_date,prior_volume,date):
    if pd.Timestamp(date).weekday()!=1:return None,'not_Tuesday'
    if pd.Timestamp(date)<=pd.Timestamp(entry_date):return None,'Tplus1'
    if qty<=0:return None,'no_listed_shares'
    if not bar.get('active',False) or not np.isfinite(bar.get('close',np.nan)) or bar['close']<=0:
        return None,'exit_inactive_or_missing'
    band=price_band(bar,date)
    if band is None:return None,'unknown_exit_band'
    limit=tick(band['lower']+band['tick'])
    if bar['close']<limit-.004:return None,'close_below_sell_limit'
    if qty>max(prior_volume,0)*.01:return None,'exit_prior_volume_capacity'
    value=qty*bar['close']
    return dict(qty=qty,price=bar['close'],notional=value,fee=fee(value,'sell',date)),None


def entitlement(qty,cash_ps,bonus_ps,transfer_ps):
    shares=float(qty)*(float(bonus_ps)+float(transfer_ps))
    if abs(shares-round(shares))>1e-7:
        raise ValueError('fractional_share_allocation_unverified')
    return dict(cash=float(qty)*float(cash_ps),extra_shares=int(round(shares)))


def economic_terms(event):
    return (float(event['economic_cash_per_share'] if 'economic_cash_per_share' in event else event['cash_ps']),
            float(event['economic_bonus_shares_per_share'] if 'economic_bonus_shares_per_share' in event else event['bonus_ps']),
            float(event['economic_transfer_shares_per_share'] if 'economic_transfer_shares_per_share' in event else event['transfer_ps']))


def reference_terms(event):
    cash,bonus,transfer=economic_terms(event)
    return (float(event.get('quote_reference_cash_per_share',cash)),
            float(event.get('quote_reference_share_multiplier',1+bonus+transfer)))


def reference_adjust(mark,event):
    cash,multiplier=reference_terms(event)
    if not np.isfinite(cash) or not np.isfinite(multiplier) or cash<0 or multiplier<=0:
        raise ValueError('unverified_quote_reference_terms')
    return (float(mark)-cash)/multiplier
