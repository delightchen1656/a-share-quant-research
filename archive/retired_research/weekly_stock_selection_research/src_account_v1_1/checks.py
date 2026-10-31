import math
import numpy as np
import pandas as pd
from common import AUDIT,dump,fee,install_development_guard
from execution import plan_buy,fill_buy,price_band
from portfolio import simulate
from account_validation import independent_account


class ToyQuotes:
    def __init__(self,blocked=False,split=False,first_fail=False):
        self.days=pd.to_datetime(['2020-12-31','2021-01-04','2021-01-05','2021-01-06','2021-01-11','2021-01-12'])
        close=[10,10,10.5,10.5,10.5,10.5]
        pre=[10,10,10,10.5,10.5,10.5]
        if blocked:close=[10,10,9,9.5,10,10.5];pre=[10,10,10,9,9.5,10]
        if split:close=[10,10,5.4,5.6,6,6];pre=[10,10,4.95,5.4,5.6,6]
        self.bars=[dict(active=True,st=False,status='1',open=float(c),high=float(c),low=float(c),close=float(c),preclose=float(p),volume=1e7,amount=1e8,pctChg=0.) for c,p in zip(close,pre)]
        self.bars[1]['open']=10.
        self.first_fail=first_fail
    def bar(self,symbol,i):
        if i<0:return dict(active=False,volume=0.)
        bar=self.bars[i].copy()
        if self.first_fail and symbol=='S0' and i==1:
            bar.update(open=11.,high=11.)
        return bar


def main():
    install_development_guard()
    q=ToyQuotes()
    bar=q.bar('S',1)
    order,why=plan_buy(bar,100000,1e7,'2021-01-04')
    assert why is None and order['qty']==9000 and order['limit_price']==10.99
    changed=dict(bar,open=11.,close=2.,high=100.,volume=0.,amount=0.)
    assert plan_buy(changed,100000,1e7,'2021-01-04')[0]==order
    fill,_=fill_buy(order,dict(bar,open=10.5),'2021-01-04')
    assert fill['qty']==9000 and fill['notional']+fill['fee']<=100000
    assert fill_buy(order,dict(bar,open=11.),'2021-01-04')[0] is None
    assert plan_buy(bar,100000,100,'2021-01-04')[0] is None
    assert math.isclose(fee(100000,'sell','2023-08-25'),131.)
    assert math.isclose(fee(100000,'sell','2023-08-28'),81.)
    assert math.isclose(fee(100000,'buy','2022-04-28'),32.)
    assert math.isclose(fee(100000,'buy','2022-04-29'),31.)
    assert price_band(dict(bar,st=True),'2026-07-03')['rate']==.05
    assert price_band(dict(bar,st=True),'2026-07-06')['rate']==.10
    score=pd.DataFrame([dict(method='TEST',symbol='S',monday='2021-01-04',rank=1)])
    plan=pd.DataFrame([dict(signal_date='2020-12-31',monday='2021-01-04',tuesday='2021-01-05',year=2021)])
    result=simulate('TEST',score,q,[],plan=plan)
    expected=1e6+9000*.5-fee(90000,'buy','2021-01-04')-fee(94500,'sell','2021-01-05')
    assert result['complete'] and math.isclose(result['daily'].equity.iloc[-1],expected,abs_tol=1e-7)
    independent_account(result,[],q)
    delayed=simulate('TEST',score,ToyQuotes(blocked=True),[],plan=plan)
    assert delayed['trades'].exit_date.iloc[0]=='2021-01-12'
    assert delayed['transactions'].loc[delayed['transactions'].side.eq('sell'),'date'].tolist()==['2021-01-12']
    independent_account(delayed,[],ToyQuotes(blocked=True))
    event=dict(event_id='S_EVENT',symbol='S',register_date='2021-01-04',ex_date='2021-01-05',pay_date='2021-01-11',listing_date='2021-01-06',cash_ps=.1,bonus_ps=1.,transfer_ps=0.,supported=True,reason='')
    split=simulate('TEST',score,ToyQuotes(split=True),[event],plan=plan)
    t=split['trades'].iloc[0]
    assert split['complete'] and t.entitled_extra_shares==9000 and t.sold_shares==18000 and t.gross_dividend==900
    assert t.exit_date=='2021-01-12'
    assert split['daily'].loc[split['daily'].date.eq('2021-01-05'),'cash_receivable'].iloc[0]==900.
    independent_account(split,[event],ToyQuotes(split=True))
    bad=simulate('TEST',score,ToyQuotes(split=True),[dict(event,supported=False,reason='unsupported')],plan=plan)
    assert not bad['complete']
    many=pd.DataFrame([dict(method='TEST',symbol=f'S{i}',monday='2021-01-04',rank=i+1) for i in range(11)])
    failed=simulate('TEST',many,ToyQuotes(first_fail=True),[],plan=plan)
    buys=failed['transactions'].loc[failed['transactions'].side.eq('buy')]
    assert len(buys)==9 and 'S10' not in set(buys.symbol)
    assert failed['plans'].budget.eq(100000).all() and failed['plans'].qty.eq(9000).all()
    hostile=ToyQuotes()
    hostile.bars[1]['high']=12.
    contradiction=simulate('TEST',score,hostile,[],plan=plan)
    assert not contradiction['complete'] and len(contradiction['transactions'])==2
    dump(AUDIT/'minimum_checks.json',dict(passed=True,preopen_quantity_independent_of_future_prices=True,
        two_phase_budget_reservation_no_replacement=True,old_positions_and_Tuesday_only_delays_retained=True,
        share_and_cash_entitlements_independently_reconciled=True,unsupported_reference_or_band_not_hidden=True,
        fee_history_minimum_lots_capacity_checked=True,date_specific_ST_rates_checked=True,
        synthetic_full_cash_and_inventory_replay_passed=True))
    print('Execution, pre-auction sizing, budget reservation and share/cash accounting checks passed.',flush=True)


if __name__=='__main__':
    main()
