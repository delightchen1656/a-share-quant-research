"""Economic checks of the idealized baseline and preserved historical matching."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as N
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine as e


class Market:
    outs={}
    def __init__(self):
        self.dates=pd.bdate_range('2026-01-01',periods=25)
        self.data={}
        for d in self.dates:
            # Flat at the price limit and tiny volume: old matching cannot
            # fill, while the explicit idealized policy must fill full size.
            self.data[d]={f'60000{i}.SH':N(open=10.,high=10.,low=10.,close=10.,preclose=10/1.1,
                volume=1.,amount=10.,turn=1.,tradestatus=1.,isST=0.,volume20=1.,prev_actual=10/1.1,adjust_ratio=1.) for i in range(1,7)}
    def __getitem__(self,day):return self.data[day]


class Open003Test(unittest.TestCase):
    def account(self,scenario='open_003_guaranteed',cash=10000):
        m=Market();a=e.Account(m.dates[1],m,scenario,cash)
        return a,m
    def ranks(self,m):return {str(d.date()):[f'60000{i}.SH' for i in range(1,7)] for d in m.dates}
    def test_first_entry_full_targets_even_at_limits_and_with_tiny_volume(self):
        a,m=self.account();a.step(m.dates[1],1,m.dates[0],self.ranks(m))
        self.assertEqual(len(a.trades),5)
        self.assertTrue(all(t['qty']==100 and t['price']==10.03 for t in a.trades))
        self.assertAlmostEqual(a.cash,4960.)
        self.assertEqual(a.fees,25.)
        self.assertTrue(all(a.holdings[s]['qty']==q for s,q in a.m.g.alpha_targets.items()))
    def test_rebalance_sells_before_buys_and_reuses_cash_with_stamp(self):
        a,m=self.account(cash=5200);ranks=self.ranks(m)
        a.step(m.dates[1],1,m.dates[0],ranks)
        last=m.dates[21];ranks[str(m.dates[20].date())]=[f'60000{i}.SH' for i in range(2,7)]
        for row in m.data[last].values():row.open=11.;row.high=11.;row.low=11.;row.close=11.;row.preclose=10.
        a.step(last,21,m.dates[20],ranks)
        fills=[t for t in a.trades if t['date']==last]
        self.assertEqual(fills[0]['symbol'],'600001.SH');self.assertEqual(fills[0]['qty'],-100)
        self.assertEqual(fills[0]['price'],10.97);self.assertEqual(fills[0]['stamp'],1.10)
        self.assertEqual(fills[-1]['symbol'],'600006.SH');self.assertEqual(fills[-1]['price'],11.03)
        self.assertEqual(a.receivables,[]);self.assertGreaterEqual(a.cash,0)
    def test_old_mode_keeps_limit_and_volume_rejections(self):
        a,m=self.account('strict_daily_limits');a.step(m.dates[1],1,m.dates[0],self.ranks(m))
        self.assertEqual(a.trades,[])
    def test_no_fabricated_open_no_negative_cash_and_t1(self):
        a,m=self.account();a.step(m.dates[1],1,m.dates[0],self.ranks(m))
        with self.assertRaises(AssertionError):a.order('600001.SH',-100)
        with self.assertRaises(ValueError):a.order('600006.SH',100000)
        a.day['600006.SH'].open=0
        with self.assertRaises(ValueError):a.order('600006.SH',100)


if __name__=='__main__':unittest.main()
