"""Isolated settlement/fee checks; no real account, market file or baseline writes."""
from types import SimpleNamespace as NS
import pandas as pd
from compare_hushen1_cash_cost_hushen2 import adapter


class Market:
    outs={}


def main():
    changed=adapter()
    a=changed.Account(pd.Timestamp('2026-10-22'),Market(),initial=11000)
    names=['600000.SH','600001.SH']
    row=NS(open=10.,high=11.,low=9.,close=10.,preclose=10.,volume=1_000_000.,tradestatus=1.,prev_actual=10.,adjust_ratio=1.)
    a.day={s:row for s in names}
    a.bars={s:NS(open=10.,high_limit=11.,low_limit=9.,is_paused=False,is_st=False,volume=1_000_000.) for s in names}
    a.sync()
    assert a.order(names[0],1000,10.02) is not None
    assert a.trades[-1]['transfer']==0 and a.trades[-1]['commission']==5 and a.trades[-1]['price']==10.02
    a.date=pd.Timestamp('2026-10-23') # Friday
    before=a.cash
    assert a.order(names[0],-1000,9.98) is not None
    sale=a.trades[-1]
    assert a.cash==before and abs(sum(v for _,v in a.receivables)-9965.02)<1e-9
    assert sale['stamp']==9.98 and sale['transfer']==0
    assert abs(a.stock.total_value-(a.cash+9965.02))<1e-9
    assert a.order(names[1],100,10.02) is None,'Friday sale proceeds must not fund a Friday purchase'
    a.date=pd.Timestamp('2026-10-26') # Next exchange session, Monday
    a.corporate();a.sync()
    assert a.order(names[1],100,10.02) is not None
    assert a.trades[-1]['qty']%100==0
    old=adapter(unified=False).Account(pd.Timestamp('2026-10-22'),Market(),initial=11000)
    for name in ['COUNT','EXPOSURE','INTERVAL','BUFFER','SMOOTH','MIN_SMOOTH','PARTICIPATION']:
        assert getattr(a.m,name)==getattr(old.m,name),name
    assert (a.m.COUNT,a.m.EXPOSURE,a.m.INTERVAL,a.m.BUFFER,a.m.PARTICIPATION)==(5,.98,20,1.5,.005)
    print('PASSED: .2pct fills,commission min5,fixed sellstamp,no transfer,Friday cash held until Monday,NAV preserves receivable,core selection/rebalance/position/cap settings unchanged')


if __name__=='__main__':main()
