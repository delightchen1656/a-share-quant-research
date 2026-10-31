import unittest
import numpy as np
import pandas as pd
from run_exit_study import simulate,prepare_frame,limit_down

class ExitMechanics(unittest.TestCase):
    def frame(self,changes=None,halt=None,unknown=None):
        dates=pd.bdate_range('2020-01-01',periods=85);n=len(dates)
        q=pd.DataFrame(dict(date=dates,open=np.full(n,100.),high=np.full(n,101.),low=np.full(n,99.),close=np.full(n,100.)))
        for i,row in (changes or {}).items():q.loc[i,['open','high','low','close']]=row
        r=q.copy();r['preclose']=r.close.ffill().shift().fillna(100);r['isST']='0';r['tradestatus']='1';r['volume']=1000.
        if halt is not None:r.loc[halt,'tradestatus']='0';r.loc[halt,'volume']=0
        if unknown is not None:r.loc[unknown,'volume']=0
        return prepare_frame(r,q,dates)
    def test_no_same_day_peak_lookahead_and_70_percent_profit_math(self):
        f=self.frame({21:[100,130,99,125],22:[124,125,120,121]})
        result=simulate(f,20,95,'fixed5','profit70')
        self.assertEqual(result['exit_day'],2)
        self.assertAlmostEqual(result['exit_price'],121)
        self.assertAlmostEqual(result['exit_return'],.21)
        self.assertAlmostEqual(result['benchmark_gain60'],.30)
    def test_gap_below_stop_uses_worse_open_not_protection_line(self):
        f=self.frame({21:[100,130,99,125],22:[110,115,105,112]})
        result=simulate(f,20,95,'fixed5','profit70')
        self.assertEqual(result['exit_reason'],'gap_stop');self.assertEqual(result['exit_price'],110)
    def test_consecutive_locked_limits_are_not_filled(self):
        f=self.frame({21:[90,90,90,90],22:[81,81,81,81],23:[82,84,80,83]})
        result=simulate(f,20,95,'fixed5','none')
        self.assertEqual(result['blocked_days'],2);self.assertEqual(result['blocked_at_limit'],2)
        self.assertEqual(result['exit_day'],3);self.assertEqual(result['exit_price'],82)
        self.assertAlmostEqual(result['exit_return'],-.18);self.assertTrue(result['stop_overshoot'])
    def test_close_ma_signal_exits_next_open(self):
        f=self.frame({21:[100,120,99,110],22:[107,108,98,99],23:[105,106,104,105]})
        result=simulate(f,20,95,'fixed5','ma5')
        self.assertEqual(result['exit_day'],3);self.assertEqual(result['exit_price'],105)
        self.assertEqual(result['exit_reason'],'close_ma5_next_open')
    def test_halt_not_filled_and_unknown_data_not_hidden(self):
        f=self.frame({21:[90,90,90,90],23:[82,84,80,83]},halt=22)
        result=simulate(f,20,95,'fixed5','none')
        self.assertEqual(result['exit_day'],3)
        self.assertEqual(simulate(self.frame(unknown=22),20,95,'fixed5','none')['status'],'unknown_quote')
    def test_locked_terminal_is_unresolved_not_a_sale(self):
        result=simulate(self.frame({80:[90,90,90,90]}),20,95,'fixed5','none')
        self.assertEqual(result['status'],'unresolved');self.assertIsNone(result['exit_return'])
        self.assertAlmostEqual(result['mark_return'],-.10)
    def test_historical_limit_rounding(self):
        self.assertEqual(limit_down(10.05,'0'),9.05)
        self.assertEqual(limit_down(10.1,'1'),9.60)

if __name__=='__main__':unittest.main(verbosity=2)
