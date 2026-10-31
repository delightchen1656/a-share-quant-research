import inspect
import unittest
import pandas as pd
from run_june2020_starts import ARCHIVE,module
from baseline_fixed_ioc import fixed_ioc_engine


class BaselineFixedIocTest(unittest.TestCase):
    def test_default_restored_to_pending_slots_and_buffered_quantity(self):
        core=module('restored_default_test',ARCHIVE/'research/run_batch.py')
        engine=fixed_ioc_engine(core)
        previous=fixed_ioc_engine(core,manual_expiry_open=True,filled_slots=False)
        self.assertEqual(engine.adapted_source,previous.adapted_source)
        self.assertIn('free_slots = slots - len(pending) - len(holdings)',engine.adapted_source)
        self.assertIn('(1.0 + slip) * 100',engine.adapted_source)
        self.assertIn('if date > h.expiry_session:',engine.adapted_source)
        self.assertNotIn('pending_priority(',engine.adapted_source)

    def test_only_declared_source_changes(self):
        core=module('minimal_source_test',ARCHIVE/'research/run_batch.py')
        engine=fixed_ioc_engine(core);restored=engine.adapted_source
        for before,after in reversed(engine.minimal_replacements):
            self.assertEqual(restored.count(after),1)
            restored=restored.replace(after,before)
        self.assertEqual(restored,inspect.getsource(core.simulate))
        self.assertNotIn('software_order_parameters',engine.adapted_source)
        self.assertIn('budget = max(0.0, equity / slots)',engine.adapted_source)
        self.assertIn('take_price=buy_price * (1.0 + take_mult * atr)',engine.adapted_source)
        self.assertIn('sell_price = max(0.01, base * (1.0 - slip))',engine.adapted_source)

    def replay(self,buyprice,volume=10000000):
        core=fixed_ioc_engine(module('minimal_sim_test',ARCHIVE/'research/run_batch.py'),manual_expiry_open=False,filled_slots=False)
        dates=pd.bdate_range('2020-01-02',periods=4)
        signals=pd.DataFrame([dict(date=dates[0],symbol='600000.SH',factor='C04_NEW',close=10.,atr_pct=.03,score=1.)])
        bars=pd.DataFrame([dict(date=dates[0],open=10.,high=10.,low=10.,close=10.,preclose=10.,volume=10000000,tradestatus=1)]+
            [dict(date=d,open=buyprice,high=buyprice,low=buyprice,close=buyprice,preclose=buyprice,volume=volume,tradestatus=1) for d in dates[1:]]).set_index('date')
        core.EVAL_START=dates[0];core.HARD_MAX_DATE=dates[-1];core.LAST_SIGNAL_DATE=dates[-1];core.YEARS=[2020]
        return core.simulate(signals,{'600000.SH':bars},list(pd.bdate_range(dates[0],'2020-03-31')),
            'C04_NEW',0.,30,'test',4.,1.5,keep_trades=True,slots=5,known_action_keys={'600000.SH/2020'})

    def test_gap_down_keeps_fixed_quantity(self):
        result,t=self.replay(5.)
        self.assertTrue(t.empty)
        self.assertEqual(result['fixed_order_attempts'][0]['requested_quantity'],1900)
        self.assertEqual(result['fixed_order_attempts'][0]['filled_quantity'],1900)

    def test_partial_fill_has_no_retry(self):
        result,_=self.replay(10.,volume=50000)
        self.assertEqual(len(result['fixed_order_attempts']),1)
        self.assertEqual(result['fixed_order_attempts'][0]['filled_quantity'],1000)
        self.assertEqual(result['pending_orders_at_end'],0)

    def test_zero_fill_has_no_retry(self):
        result,_=self.replay(10.,volume=1000)
        self.assertEqual(len(result['fixed_order_attempts']),1)
        self.assertEqual(result['open_positions_at_end'],0)
        self.assertEqual(result['pending_orders_at_end'],0)

    def expiry_replay(self, blocked=False, protection_on_expiry=False, legacy=False):
        core=fixed_ioc_engine(module('manual_expiry_test',ARCHIVE/'research/run_batch.py'),manual_expiry_open=not legacy,filled_slots=False)
        dates=list(pd.to_datetime(['2020-01-01','2020-01-02','2020-01-03','2020-01-06','2020-01-07']))
        signals=pd.DataFrame([dict(date=dates[0],symbol='600000.SH',factor='C04_NEW',close=10.,atr_pct=.03,score=1.)])
        rows=[]
        for i,d in enumerate(dates):
            opn=10. if i<3 else 10.3
            rows.append(dict(date=d,open=opn,high=12. if i>=3 or (i==2 and protection_on_expiry) else 10.1,
                low=9. if i>=3 else 9.9,close=10.,preclose=10.,volume=10000000,tradestatus=0 if blocked and i==3 else 1))
        bars=pd.DataFrame(rows).set_index('date')
        core.EVAL_START=dates[0];core.HARD_MAX_DATE=dates[-1];core.LAST_SIGNAL_DATE=dates[-1];core.YEARS=[2020]
        return core.simulate(signals,{'600000.SH':bars},dates,'C04_NEW',0.,1,'test',4.,1.5,
            keep_trades=True,slots=5,known_action_keys={'600000.SH/2020'})

    def test_expiry_waits_over_weekend_and_uses_open_before_intraday_touch(self):
        _,t=self.expiry_replay()
        self.assertEqual(str(t.iloc[0].exit_date.date()),'2020-01-06')
        self.assertEqual(t.iloc[0].reason,'expiry')
        self.assertAlmostEqual(t.iloc[0].exit_price,10.3*.998)

    def test_suspension_retries_later_open(self):
        _,t=self.expiry_replay(blocked=True)
        self.assertEqual(str(t.iloc[0].exit_date.date()),'2020-01-07')
        self.assertEqual(t.iloc[0].reason,'expiry')

    def test_protection_still_active_on_original_expiry_date(self):
        _,t=self.expiry_replay(protection_on_expiry=True)
        self.assertEqual(str(t.iloc[0].exit_date.date()),'2020-01-03')
        self.assertEqual(t.iloc[0].reason,'take')

    def test_legacy_expiry_close_remains_reproducible(self):
        _,t=self.expiry_replay(legacy=True)
        self.assertEqual(str(t.iloc[0].exit_date.date()),'2020-01-03')
        self.assertAlmostEqual(t.iloc[0].exit_price,10.*.998)


if __name__=='__main__':unittest.main()
