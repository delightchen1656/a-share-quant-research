"""IOC execution semantics on synthetic bars, no actual account access."""
import unittest
import pandas as pd
from run_june2020_starts import ARCHIVE, module
from broker_execution import broker_engine


class BrokerExecutionTest(unittest.TestCase):
    def replay(self, prices, signal_price=10.,atr=.03,quote=None):
        engine=broker_engine(module('synthetic_ioc_engine',ARCHIVE/'research/run_batch.py'))
        if quote:engine.software_order_parameters=lambda *args:quote
        dates=pd.bdate_range('2020-01-02',periods=len(prices))
        rows=[]
        for date,p in zip(dates,prices):
            rows.append(dict(date=date,open=p.get('open',10.),high=p.get('high',10.),low=p.get('low',10.),
                close=p.get('close',10.),preclose=p.get('preclose',10.),volume=p.get('volume',10000000),tradestatus=1))
        bars=pd.DataFrame(rows).set_index('date')
        signals=pd.DataFrame([dict(date=dates[0],symbol='600000.SH',factor='C04_NEW',close=signal_price,atr_pct=atr,score=1.)])
        engine.EVAL_START=dates[0];engine.HARD_MAX_DATE=dates[-1];engine.LAST_SIGNAL_DATE=dates[-1];engine.YEARS=[2020]
        return engine.simulate(signals,{'600000.SH':bars},list(pd.bdate_range(dates[0],'2020-03-31')),
            'C04_NEW',0.,30,'test',4.,1.5,keep_trades=True,slots=5,known_action_keys={'600000.SH/2020'})

    def test_gap_down_never_increases_fixed_quantity(self):
        result,_=self.replay([{},dict(open=5.,high=5.1,low=4.9,close=5.)])
        self.assertEqual(result['terminal_positions'][0]['quantity'],1900)
        self.assertEqual(result['ioc_attempts'][0]['requested_quantity'],1900)

    def test_zero_fill_cancels_order_without_daily_retry(self):
        result,_=self.replay([{},dict(volume=1000),{}])
        self.assertEqual(result['open_positions_at_end'],0)
        self.assertEqual(result['pending_orders_at_end'],0)
        self.assertEqual(len(result['ioc_attempts']),1)
        self.assertEqual(result['ioc_attempts'][0]['filled_quantity'],0)

    def test_partial_buy_cancels_remainder(self):
        result,_=self.replay([{},dict(volume=50000),{}])
        self.assertEqual(result['terminal_positions'][0]['quantity'],1000)
        self.assertEqual(result['pending_orders_at_end'],0)
        self.assertEqual(result['ioc_attempts'][0]['status'],'partial_remainder_cancelled')

    def test_one_price_limit_up_does_not_assume_fill(self):
        result,_=self.replay([{},dict(open=11.,high=11.,low=11.,close=11.)],signal_price=12.)
        self.assertEqual(result['open_positions_at_end'],0)
        self.assertEqual(result['ioc_attempts'][0]['status'],'one_price_limit_up_no_fill')

    def test_partial_sell_preserves_remaining_position_and_cost(self):
        result,t=self.replay([{}, {},dict(open=12.,high=12.,low=11.5,close=12.,volume=20000),dict(open=12.,high=12.,low=11.5,close=12.,preclose=12.)])
        self.assertEqual(t.shares.tolist(),[400,1500])
        self.assertEqual(result['open_positions_at_end'],0)
        self.assertAlmostEqual(t.entry_notional.sum(),19000)
        self.assertAlmostEqual(t.entry_cost.sum(),19005.7)
        self.assertAlmostEqual(result['final_equity']-100000,t.pnl.sum())

    def test_double_touch_keeps_conservative_stop_first(self):
        _,t=self.replay([{}, {},dict(high=12.,low=9.)])
        self.assertEqual(t.reason.tolist(),['stop'])

    def test_insufficient_cash_rejects_instead_of_resizing(self):
        result,_=self.replay([{},{}],quote=(200000,20000))
        self.assertEqual(result['open_positions_at_end'],0)
        self.assertEqual(result['pending_orders_at_end'],0)
        self.assertEqual(result['ioc_attempts'][0]['status'],'insufficient_cash_rejected')

    def test_limit_down_sell_keeps_unsold_shares(self):
        result,t=self.replay([{}, {},dict(open=9.,high=9.,low=9.,close=9.)])
        self.assertTrue(t.empty)
        self.assertEqual(result['terminal_positions'][0]['quantity'],1900)
        self.assertEqual(result['ioc_attempts'][-1]['status'],'one_price_limit_down_no_fill')


if __name__=='__main__':unittest.main()
