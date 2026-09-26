import unittest
import pandas as pd
import monthly_A_guard_engine as e
from monthly_A_guard_engine import NavPause

class Guard(unittest.TestCase):
    def test_trigger_and_exact_cooldown(self):
        g=NavPause(.10,2,100.)
        self.assertEqual(g.at_open(0,100.),(False,False))
        self.assertEqual(g.at_open(1,110.),(False,False))
        self.assertEqual(g.at_open(2,98.),(True,True))
        self.assertEqual(g.at_open(3,98.),(True,False))
        self.assertEqual(g.at_open(4,98.),(False,False))
        self.assertEqual(g.peak,98.)

    def test_no_future_equity_argument(self):
        g=NavPause(.1,20,100.)
        self.assertEqual(g.at_open(0,100.),(False,False))
        self.assertEqual(g.at_open(1,89.),(True,True))

    def test_sell_next_session_and_no_cooldown_buy(self):
        dates=pd.date_range('2024-01-02',periods=4,freq='B')
        e.START=dates[0];e.END=dates[-1];e.CALENDAR=dates;e.INITIAL_CASH=100000.
        e.NAV_GUARD=(.06,2);e.GUARD_LOG=[];e.ACTION_MODE='ledger';e.ACTION_LEDGER={}
        e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[];e.SELECTION_TRACE=[];e.STRICT_TARGET=True
        panel=pd.DataFrame([dict(date=d,symbol='A',open=10. if i<2 else 9.,close=10. if i==0 else 9.,preclose=10. if i<2 else 9.,volume=10000000.,tradestatus='1',isST='0') for i,d in enumerate(dates)])
        e.PREPARED={d:q.set_index('symbol') for d,q in panel.groupby('date')}
        ranks={dates[0]:pd.DataFrame(dict(symbol=['A'],downside=[.02]))};exposure={dates[0]:.8}
        curve,trades=e.simulate(ranks,.05,1,1,exposure,1.5,panel)
        self.assertEqual(list(trades[trades.side=='SELL'].date),[dates[2]])
        self.assertEqual(list(trades[trades.side=='BUY'].date),[dates[0]])
        self.assertEqual(set(ranks),{dates[0]});self.assertEqual(set(exposure),{dates[0]})
        self.assertGreaterEqual(curve.cash.min(),0.)

if __name__=='__main__':unittest.main()
