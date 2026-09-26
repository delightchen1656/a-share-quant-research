"""Synthetic regression tests for the optional sell-only risk extension."""
import unittest
from unittest.mock import patch
import pandas as pd
import execution_engine as bt

class RiskTests(unittest.TestCase):
    def run_case(self, limits=None, blocked=False):
        dates=pd.bdate_range('2021-01-04',periods=3)
        ranks={d:pd.DataFrame({'symbol':['A','B'],'downside':[.01,.01]}) for d in dates}
        rows=[]
        for d in dates:
            for s in ('A','B'):
                rows.append(dict(date=d,symbol=s,open=90 if blocked and d==dates[1] else 100,
                    close=100,preclose=100,volume=1000000,tradestatus='1',isST='0'))
        with patch.object(bt,'INITIAL_CASH',100000.),patch.object(bt,'trading_calendar',return_value=dates):
            return bt.simulate(ranks,.05,2,2,.8,1.5,pd.DataFrame(rows),min_adjustment=3000,risk_only_limits=limits)

    def test_empty_limits_preserve_default(self):
        a,b=self.run_case();c,d=self.run_case({})
        pd.testing.assert_frame_equal(a,c);pd.testing.assert_frame_equal(b,d)

    def test_reduce_without_recovery_buys(self):
        dates=pd.bdate_range('2021-01-04',periods=3)
        curve,trades=self.run_case({dates[1]:.4,dates[2]:.8})
        risk=trades[trades.date>=dates[1]]
        self.assertTrue(len(risk)>0)
        self.assertTrue((risk.side=='SELL').all())
        self.assertFalse((risk.date==dates[2]).any())
        self.assertTrue((curve.cash>=0).all())

    def test_no_trim_when_below_limit(self):
        dates=pd.bdate_range('2021-01-04',periods=3)
        _,trades=self.run_case({dates[1]:.9,dates[2]:.9})
        self.assertFalse((trades.date>dates[0]).any())

    def test_limit_down_blocks_risk_sale(self):
        dates=pd.bdate_range('2021-01-04',periods=3)
        _,trades=self.run_case({dates[1]:.4,dates[2]:.8},blocked=True)
        self.assertFalse((trades.date==dates[1]).any())

if __name__=='__main__':unittest.main()
