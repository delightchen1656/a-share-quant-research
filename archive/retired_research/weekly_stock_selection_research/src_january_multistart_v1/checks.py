"""Event-state and independent ledger checks for the daily proxy exit."""
import math
import pandas as pd
from common import AUDIT,dump,fee,install_development_guard
from execution import plan_buy,fill_buy
from daily_exit import daily_sell
from portfolio import simulate
from account_validation import independent_account

def bar(o=10,h=10,l=10,c=10,pre=10):
    return dict(active=True,st=False,status='1',open=o,high=h,low=l,close=c,
                preclose=pre,volume=1e7,amount=1e8,pctChg=0.)

class ToyQuotes:
    def __init__(self,bars=None):
        self.days=pd.to_datetime(['2020-12-31','2021-01-04','2021-01-05','2021-01-06','2021-01-11','2021-01-12'])
        self.bars=bars or [bar(),bar(),bar(c=10.5,h=10.5),bar(o=10.5,h=10.5,l=10.5,c=10.5,pre=10.5),
                          bar(o=10.5,h=10.5,l=10.5,c=10.5,pre=10.5),bar(o=10.5,h=10.5,l=10.5,c=10.5,pre=10.5)]
    def bar(self,symbol,i):
        return self.bars[i].copy() if i>=0 else dict(active=False,volume=0.)

def main():
    install_development_guard()
    monday='2021-01-04';tuesday='2021-01-05'
    order,_=plan_buy(bar(),1e5,1e7,monday)
    hostile=bar(o=99,h=100,l=1,c=2);hostile.update(volume=0,amount=0)
    assert order==plan_buy(hostile,1e5,1e7,monday)[0]
    assert order['qty']==9000 and fill_buy(order,bar(),monday)[0]['qty']==9000
    f,_,s=daily_sell(bar(l=9,h=10,c=9.7),100,monday,tuesday)
    assert f['price']==9 and s['emergency'] and not f['ambiguous_order']
    f,_,_=daily_sell(bar(l=9,h=10,c=9),100,monday,tuesday)
    assert f['price']==9 and f['ambiguous_order']
    f,_,_=daily_sell(bar(o=9,l=9,h=9.5,c=9),100,monday,tuesday)
    assert f and not f['ambiguous_order'] # Open already touched; later high proves reopening.
    f,reason,s=daily_sell(bar(o=9,h=9,l=9,c=9),100,monday,tuesday)
    assert f is None and reason=='full_session_limit_lock' and s['emergency']
    f,_,_=daily_sell(bar(o=9.4,h=9.5,l=9.2,c=9.5,pre=9),100,monday,'2021-01-06',True,True)
    assert f['price']==8.1 and f['outside_daily_range']
    assert daily_sell(bar(),100,monday,'2021-01-06')[0] is None
    assert daily_sell(bar(l=9),100,tuesday,tuesday)[1]=='Tplus1'
    assert daily_sell(bar(),0,monday,tuesday)[1]=='no_listed_shares'
    assert daily_sell(dict(bar(),active=False,status='0'),100,monday,tuesday)[0] is None
    assert daily_sell(bar(l=8),100,monday,tuesday)[1]=='unknown_or_contradictory_exit_band'
    score=pd.DataFrame([dict(method='TEST',symbol='SYNTH_A',monday=monday,rank=1)])
    plan=pd.DataFrame([dict(signal_date='2020-12-31',monday=monday,tuesday=tuesday,year=2021)])
    q=ToyQuotes()
    result=simulate('TEST',score,q,[],plan=plan,initial_cash=1e6)
    assert result['complete']
    independent_account(result,[],q)
    locked=ToyQuotes([bar(),bar(),bar(o=9,h=9,l=9,c=9),bar(o=9.5,h=9.5,l=9.5,c=9.5,pre=9),
                     bar(pre=9.5),bar()])
    result=simulate('TEST',score,locked,[],plan=plan,initial_cash=1e6)
    tx=result['transactions'].query("side == 'sell'")
    assert tx.date.tolist()==['2021-01-06'] and tx.price.tolist()==[8.1]
    assert result['complete'];independent_account(result,[],locked)
    # Split rights cannot be sold before listing; economic/reference terms differ.
    q=ToyQuotes([bar(),bar(),bar(o=7.1,h=7.1,l=7.1,c=7.1,pre=(10-.08)/1.4),
                 bar(o=7.2,h=7.2,l=7.2,c=7.2,pre=7.1),bar(o=7.2,h=7.2,l=7.2,c=7.2,pre=7.2),
                 bar(o=7.2,h=7.2,l=7.2,c=7.2,pre=7.2)])
    event=dict(event_id='SYNTH_A_EVENT',symbol='SYNTH_A',register_date=monday,ex_date=tuesday,
        pay_date='2021-01-11',listing_date='2021-01-06',cash_ps=.1,bonus_ps=.2,transfer_ps=.3,
        economic_cash_per_share=.1,economic_bonus_shares_per_share=.2,economic_transfer_shares_per_share=.3,
        quote_reference_cash_per_share=.08,quote_reference_share_multiplier=1.4,supported=True,reason='')
    result=simulate('TEST',score,q,[event],plan=plan,initial_cash=1e6)
    trade=result['trades'].iloc[0]
    assert result['complete'] and trade.entitled_extra_shares==4500 and trade.gross_dividend==900
    assert result['transactions'].query("side == 'sell'").date.tolist()==[tuesday,'2021-01-06']
    expected=9000*7.1+4500*7.2+900-90000-fee(90000,'buy',monday)-fee(63900,'sell',tuesday)-fee(32400,'sell','2021-01-06')
    assert math.isclose(trade.pnl,expected,abs_tol=1e-7)
    independent_account(result,[event],q)
    # A blocked position frees no Monday entry slot, even if it exits that day.
    q=ToyQuotes([bar(),bar(),bar(o=9,h=9,l=9,c=9),bar(o=8.1,h=8.1,l=8.1,c=8.1,pre=9),
                 bar(o=8,h=8,l=8,c=8,pre=8.1),bar(o=8,h=8,l=8,c=8,pre=8)])
    score2=pd.DataFrame([dict(method='TEST',symbol=f'SYNTH_{j}',monday=monday,rank=j+1) for j in range(10)]+
                       [dict(method='TEST',symbol=f'NEW_{j}',monday='2021-01-11',rank=j+1) for j in range(10)])
    result=simulate('TEST',score2,q,[],plan=plan,initial_cash=1e6)
    assert result['complete'] and len(result['plans'])==10
    assert result['transactions'].query("side == 'buy'").date.eq(monday).all()
    assert result['transactions'].query("side == 'sell'").date.eq('2021-01-11').all()
    independent_account(result,[],q)
    dump(AUDIT/'minimum_checks.json',dict(passed=True,
        unchanged_preopen_sizing=True,Tuesday_touch_reopen_floor_and_order_ambiguity=True,
        Wednesday_and_Monday_retries=True,lock_missing_Tplus1_and_no_listed_constraints=True,
        all_lots_assumed_sellable_no_volume_cap=True,no_same_auction_proceeds_or_slot_reuse=True,
        separate_economic_reference_terms_and_pending_listing=True,independent_cash_share_replays=True))
    print('Daily exit state and independent accounting checks passed.',flush=True)

if __name__=='__main__':main()
