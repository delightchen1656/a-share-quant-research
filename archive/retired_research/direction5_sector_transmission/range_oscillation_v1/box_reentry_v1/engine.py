"""Daily-bar fixed-box simulation. Conditional event accounting, no production use."""
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
import math
import numpy as np
import pandas as pd


def tick(x, mode='nearest'):
    rounding={'nearest':ROUND_HALF_UP,'up':ROUND_CEILING,'down':ROUND_FLOOR}[mode]
    return float(Decimal(str(float(x))).quantize(Decimal('.01'),rounding=rounding))


def fee(value,side):
    return max(5.,value*.0003)+value*.00001+(value*.0005 if side=='sell' else 0.)


def valid(bar):
    return str(bar.get('tradestatus',''))=='1' and all(np.isfinite(bar.get(c,np.nan)) and bar[c]>0 for c in ['open','high','low','close','volume','amount'])


def one_limit(bar,side):
    if not valid(bar) or not np.isfinite(bar.get('preclose',np.nan)) or bar['preclose']<=0:
        return False
    rate=.05 if str(bar.get('isST','0'))=='1' else .10
    limit=tick(bar['preclose']*(1+rate if side=='buy' else 1-rate))
    return abs(bar['high']-bar['low'])<.000001 and abs(bar['close']-limit)<.005


def execution(bar,reference,side,limit=False):
    if limit:
        return tick(reference,'up')
    if side=='buy':
        return min(tick(reference*1.0005,'up'),bar['high'])
    return max(tick(reference*.9995,'down'),bar['low'])


def simulate(symbol,name,lower,upper,frame,events,initial=50000.):
    """frame includes 2023 last session context; only later rows can generate orders."""
    width=upper-lower
    lower,upper=lower+.05*width,upper-.05*width
    initial_lower,initial_upper=lower,upper
    cash=initial
    position=None
    pending_buy=False
    pending_stop=False
    last_mark=np.nan
    trades=[]
    logs=[]
    daily=[]
    entitlements=[]
    account_unknown=False
    entry_disabled=False
    counts=dict(signals=0,buy_fills=0,cancelled_buys=0,stop_blocked=0,dual_touch=0,tplus1_stop=0,tplus1_tp=0)
    by_ex={}
    by_record={}
    for event in events:
        by_ex.setdefault(event['ex_date'],[]).append(event)
        if event.get('supported'):
            by_record.setdefault(event['register_date'],[]).append(event)
    previous=None
    def log(date,kind,**kwargs):
        logs.append(dict(symbol=symbol,date=str(date.date()),kind=kind,**kwargs))
    for day,series in frame.iterrows():
        bar=series.to_dict()
        active=valid(bar)
        if day.year<2024:
            previous=bar
            if active:
                last_mark=bar['close']
            continue
        key=str(day.date())
        old_lower,old_upper=lower,upper
        cash_shift=0.
        known_event=False
        for event in by_ex.get(key,[]):
            known_event=True
            if event['supported']:
                dividend=event['cash_per_share']
                lower-=dividend
                upper-=dividend
                cash_shift+=dividend
                if position is not None:
                    position['stop']-=dividend
                log(day,'cash_exdate_level_adjustment',cash_per_share=dividend,lower=lower,upper=upper)
            else:
                entry_disabled=True
                account_unknown=True
                log(day,'unsupported_corporate_action',reason=event['reason'])
        # Entitlement is fixed at register close, becomes ex-cash economic value
        # on exdate, not an extra asset while the quote is still cum-dividend.
        for entitlement in entitlements:
            if entitlement['ex_date']==key and not entitlement['booked']:
                entitlement['booked']=True
                trade=trades[entitlement['trade_index']]
                trade['gross_dividend']+=entitlement['gross']
                trade['dividend_tax_reserve']+=entitlement['gross']*.2
                log(day,'dividend_receivable_recognized',gross=entitlement['gross'])
            if entitlement['payment_date']<=key and entitlement['booked'] and not entitlement['paid']:
                cash+=entitlement['gross']*.8
                entitlement['paid']=True
                log(day,'dividend_cash_paid_net_reserve',gross=entitlement['gross'],available_cash=entitlement['gross']*.8)
        comparable_previous=(previous['close']-cash_shift) if previous is not None and valid(previous) else np.nan
        if active and np.isfinite(comparable_previous) and np.isfinite(bar.get('preclose',np.nan)):
            reference_gap=bar['preclose']-comparable_previous
            if abs(reference_gap)>.015:
                entry_disabled=True
                account_unknown=True
                log(day,'unexplained_quote_reference',difference=reference_gap,known_exdate=known_event)
        if lower<=0 or upper<=lower:
            entry_disabled=True
            account_unknown=True
            log(day,'invalid_adjusted_box')
        prior_volume=previous['volume'] if previous is not None and valid(previous) else 0.
        exited=False
        entered=False
        if position is not None:
            trade=trades[position['trade_index']]
            if not active:
                if str(bar.get('tradestatus',''))!='0':
                    account_unknown=True
                    log(day,'missing_held_quote_unknown_not_assumed_suspension')
            else:
                reason=None
                reference=None
                take_limit=False
                if pending_stop:
                    reason,reference='delayed_stop_open',bar['open']
                elif bar['open']<=position['stop']:
                    reason,reference='gap_stop',bar['open']
                elif bar['open']>=tick(upper,'up'):
                    reason,reference,take_limit='take_profit_open',upper,True
                elif bar['low']<=position['stop']:
                    reason,reference='stop_intraday',position['stop']
                    if bar['high']>tick(upper,'up'):
                        counts['dual_touch']+=1
                        log(day,'both_stop_and_target_stop_first')
                elif bar['high']>tick(upper,'up'):
                    reason,reference,take_limit='take_profit_intraday',upper,True
                if reason:
                    if one_limit(bar,'sell') or position['qty']>prior_volume*.01:
                        if 'stop' in reason:
                            pending_stop=True
                            counts['stop_blocked']+=1
                        log(day,'exit_blocked',reason=reason,one_price_lower=one_limit(bar,'sell'),prior_volume_capacity=prior_volume*.01)
                    else:
                        price=execution(bar,reference,'sell',take_limit)
                        value=position['qty']*price
                        cost=fee(value,'sell')
                        cash+=value-cost
                        trade.update(exit_date=key,exit_price=price,exit_fee=cost,exit_reason=reason,
                                     exit_notional=value,price_return=price/trade['entry_price']-1,status='closed')
                        log(day,'sell',reason=reason,price=price,qty=position['qty'],fee=cost)
                        position=None
                        pending_stop=False
                        exited=True
        if pending_buy:
            # Exactly the next market session attempt; never carry a failed buy.
            pending_buy=False
            why=None
            price=None
            quantity=0
            if not active:
                why='inactive_or_missing'
            elif str(bar.get('isST',''))!='0':
                why='ST_no_new_entry'
            elif entry_disabled:
                why='event_or_reference_basis_unsupported'
            elif one_limit(bar,'buy'):
                why='one_price_limit_up'
            elif not lower<bar['open']<upper:
                why='opening_outside_contracted_band'
            else:
                price=execution(bar,bar['open'],'buy')
                if price>=upper:
                    why='effective_price_at_or_above_target'
                else:
                    quantity=int(cash/price//100)*100
                    while quantity>0 and quantity*price+fee(quantity*price,'buy')>cash:
                        quantity-=100
                    if quantity<=0:
                        why='insufficient_round_lot_cash'
                    elif quantity>prior_volume*.01:
                        why='prior_volume_capacity'
            if why:
                counts['cancelled_buys']+=1
                log(day,'buy_cancelled',reason=why)
            else:
                value=quantity*price
                cost=fee(value,'buy')
                cash-=value+cost
                trade=dict(symbol=symbol,historical_name=name,entry_date=key,entry_price=price,qty=quantity,
                           entry_fee=cost,entry_notional=value,initial_stop=.9*price,entry_target=upper,
                           gross_dividend=0.,dividend_tax_reserve=0.,status='open',exit_date=None,
                           exit_price=None,exit_fee=0.,exit_notional=0.,exit_reason=None,price_return=None)
                trades.append(trade)
                position=dict(qty=quantity,stop=.9*price,trade_index=len(trades)-1)
                counts['buy_fills']+=1
                entered=True
                log(day,'buy',price=price,qty=quantity,fee=cost,stop=.9*price,target=upper)
                if bar['low']<=position['stop']:
                    pending_stop=True
                    counts['tplus1_stop']+=1
                    log(day,'entry_day_stop_tplus1_delayed')
                if bar['high']>=tick(upper,'up'):
                    counts['tplus1_tp']+=1
                    log(day,'entry_day_target_tplus1_no_sale')
        if position is not None:
            for event in by_record.get(key,[]):
                gross=position['qty']*event['cash_per_share']
                entitlements.append(dict(ex_date=event['ex_date'],payment_date=event['cash_payment_date'],gross=gross,
                                         booked=False,paid=False,trade_index=position['trade_index']))
                log(day,'register_close_entitlement',gross=gross,qty=position['qty'])
        if active:
            last_mark=bar['close']
        receivable=sum(e['gross']*.8 for e in entitlements if e['booked'] and not e['paid'])
        inventory=position['qty']*last_mark if position is not None else 0.
        equity=cash+inventory+receivable
        if not entry_disabled and not exited and not entered and position is None and active and str(bar.get('isST',''))=='0' and np.isfinite(comparable_previous):
            if comparable_previous<=lower<bar['close']<upper:
                pending_buy=True
                counts['signals']+=1
                log(day,'close_cross_signal',previous_close_comparable=comparable_previous,close=bar['close'],lower=lower)
        daily.append(dict(symbol=symbol,date=key,cash=cash,inventory_value=inventory,net_receivable=receivable,
                          equity=equity,qty=0 if position is None else position['qty'],
                          lower=lower,upper=upper,stop=None if position is None else position['stop'],
                          account_unknown=account_unknown,held_quote_stale=bool(position is not None and not active)))
        assert cash>=-1e-6,(symbol,day,cash)
        assert math.isclose(equity,cash+inventory+receivable,abs_tol=1e-7)
        previous=bar
    for trade in trades:
        if trade['status']=='closed':
            trade['pnl_after_fees_and_dividend_reserve']=trade['exit_notional']-trade['exit_fee']-trade['entry_notional']-trade['entry_fee']+trade['gross_dividend']-trade['dividend_tax_reserve']
            trade['return_after_fees_and_dividend_reserve']=trade['pnl_after_fees_and_dividend_reserve']/(trade['entry_notional']+trade['entry_fee'])
        else:
            trade['end_mark']=last_mark
            trade['pnl_after_fees_and_dividend_reserve']=trade['qty']*last_mark-trade['entry_notional']-trade['entry_fee']+trade['gross_dividend']-trade['dividend_tax_reserve']
            trade['return_after_fees_and_dividend_reserve']=None
    end=daily[-1] if daily else dict(equity=initial,cash=initial,qty=0,held_quote_stale=False)
    if end['held_quote_stale']:
        account_unknown=True
    conditional_pnl=end['equity']-initial
    assert math.isclose(conditional_pnl,sum(t['pnl_after_fees_and_dividend_reserve'] for t in trades),abs_tol=1e-6),(symbol,conditional_pnl,trades)
    summary=dict(symbol=symbol,historical_name=name,original_lower=initial_lower-.05*width,original_upper=initial_upper+.05*width,
                 contracted_lower=initial_lower,contracted_upper=initial_upper,final_lower=lower,final_upper=upper,
                 initial_cash=initial,end_equity=end['equity'],return_conditional=end['equity']/initial-1,
                 account_unknown=account_unknown,ending_qty=end['qty'],ending_cash=end['cash'],
                 closed_trades=sum(t['status']=='closed' for t in trades),open_trades=sum(t['status']=='open' for t in trades),
                 wins=sum(t['status']=='closed' and t['pnl_after_fees_and_dividend_reserve']>0 for t in trades),**counts,
                 last_signal_unfilled_outside_window=pending_buy)
    return summary,trades,daily,logs
