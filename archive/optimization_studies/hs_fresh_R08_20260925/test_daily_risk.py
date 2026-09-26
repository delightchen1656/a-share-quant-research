import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import research as r
import execution_daily_overlay as new
from round19_daily_risk import exposures,CONFIGS

class DailyRiskTests(unittest.TestCase):
    def test_prefix_and_current_future_exclusion(self):
        rng=np.random.default_rng(9);dates=pd.bdate_range('2018-01-01',periods=500)
        close=pd.Series(np.exp(np.cumsum(rng.normal(0,.015,500))),index=dates)
        changed=close.copy();changed.iloc[400:]*=2
        for mode in ('trend60','trend120','dd60','dd120'):
            a=exposures(close,mode)
            pd.testing.assert_series_equal(a.iloc[:401],exposures(changed,mode).iloc[:401])
            pd.testing.assert_series_equal(a.iloc[:400],exposures(close.iloc[:400],mode))
            self.assertTrue(a.isin([.65,.95]).all())
        self.assertEqual(len(CONFIGS),12)
    def test_engine_off_identical_and_resize_only_old_symbols(self):
        dates=pd.bdate_range('2020-01-02',periods=4)
        prepared={d:pd.DataFrame([dict(symbol=s,date=d,open=p,close=p,preclose=p,volume=1e7,tradestatus='1',isST='0')
            for s,p in [('A',10.),('B',20.),('C',5.)]]).set_index('symbol') for d in dates}
        ranks={dates[0]:pd.DataFrame(dict(symbol=['A','B','C'],downside=[1.,1.,1.]))}
        results=[]
        for engine,enabled in ((r.e,False),(new,False),(new,True)):
            changes=dict(CALENDAR=dates,START=dates[0],END=dates[-1],INITIAL_CASH=100000.,PREPARED=prepared,
                ACTION_MODE='ledger',ACTION_LEDGER={},RECEIVABLES=[],LOCKED_BONUS=[],UNRESOLVED_ACTIONS=[],
                DELISTINGS={},DELISTING_EVENTS=[],SELECTION_TRACE=[],SELECTOR=None,SELECTOR_CONTEXT=None,STRICT_TARGET=True)
            extra=dict(resize_targets={dates[1]:.65,dates[2]:.95}) if enabled else {}
            with patch.multiple(engine,**changes):results.append(engine.simulate(ranks,.05,2,4,.95,1.5,min_adjustment=0,**extra))
        for i in (0,1):pd.testing.assert_frame_equal(results[0][i],results[1][i])
        curve,trades=results[2]
        self.assertEqual(set(trades.symbol),{'A','B'})
        self.assertTrue((trades[trades.date==dates[1]].side=='SELL').all())
        self.assertTrue((trades[trades.date==dates[2]].side=='BUY').all())
        self.assertTrue((curve.cash>=0).all())
        self.assertTrue((trades.quantity%100==0).all())
        self.assertLess((curve.stock_value/curve.equity).iloc[1],.66)
        self.assertGreater((curve.stock_value/curve.equity).iloc[2],.90)

if __name__=='__main__':unittest.main()
