import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import research as r

class Fresh(unittest.TestCase):
    def test_past_only(self):
        p=pd.Series(np.exp(np.arange(300)*.001),index=pd.bdate_range('2018-01-01',periods=300))
        pd.testing.assert_frame_equal(r.derive_prices(p).iloc[:200],r.derive_prices(p.iloc[:200]))
    def test_exposure_actual(self):
        c=pd.DataFrame(dict(stock_value=[0,60,70],equity=[100]*3))
        z=r.exposure(c);self.assertAlmostEqual(z['mean_exposure'],1.3/3);self.assertEqual(z['flat_streak'],1)
    def test_all_configs_unique(self):
        self.assertEqual(len(r.CONFIGS),48)
        self.assertEqual(len({(c['family'],c['size'],c['interval']) for c in r.CONFIGS}),48)
        self.assertTrue(all(c['exposure']>.5 for c in r.CONFIGS))
    def test_delisting_is_not_survivor_filter_or_phantom_sale(self):
        e=r.e;dates=pd.bdate_range('2020-01-02',periods=3);symbol='600001.SH'
        prepared={d:pd.DataFrame([dict(symbol=symbol,date=d,open=10.,close=10.,preclose=10.,volume=1e7,tradestatus='1',isST='0')]).set_index('symbol') for d in dates}
        changes=dict(CALENDAR=dates,START=dates[0],END=dates[-1],INITIAL_CASH=100000.,PREPARED=prepared,ACTION_MODE='ledger',ACTION_LEDGER={},RECEIVABLES=[],LOCKED_BONUS=[],UNRESOLVED_ACTIONS=[],DELISTINGS={symbol:dates[1]},DELISTING_EVENTS=[],SELECTION_TRACE=[],SELECTOR=None,STRICT_TARGET=True)
        with patch.multiple(e,**changes):
            curve,trades=e.simulate({dates[0]:pd.DataFrame(dict(symbol=[symbol],downside=[1.]))},.05,1,1,.9,1.5,min_adjustment=0)
            self.assertGreater(curve.stock_value.iloc[0],0)
            self.assertEqual(curve.stock_value.iloc[1],0)
            self.assertEqual(len(e.DELISTING_EVENTS),1)
            self.assertEqual(list(trades.side),['BUY'])
            self.assertLess(curve.equity.iloc[1],20000)
    def test_goal_cannot_pass_only_good_full_period(self):
        import validate
        def row(year):return dict(start=str(year)+'-01-02',annualized=.15,sharpe=1.1,mean_exposure=.8,flat_streak=0,total_return=.3,drawdown=-.2,unresolved_actions=0)
        full=row(2020);long=[row(y) for y in range(2020,2025)];rolling=[row(2023)]
        neighbor={'test':r.summarize(rolling)}
        self.assertTrue(validate.gates(full,long,rolling,rolling,neighbor)['passed'])
        long[-1]['sharpe']=.5
        self.assertFalse(validate.gates(full,long,rolling,rolling,neighbor)['passed'])
        long[-1]['sharpe']=1.1;full['mean_exposure']=.5
        self.assertFalse(validate.gates(full,long,rolling,rolling,neighbor)['passed'])

if __name__=='__main__':unittest.main()
