import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from hushen1 import Desk


class Hushen1DeskTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.desk=Desk(Path(self.temp.name))
        self.performance=patch.object(self.desk,'performance',return_value={'daily':[],'curve':[]})
        self.performance.start();self.addCleanup(self.performance.stop)
        self.calendar=patch('hushen1.market.calendar_extended',return_value=['2026-10-28','2026-10-29','2026-10-30','2026-11-02'])
        self.calendar.start()
        self.clock=patch('hushen1.now',return_value=datetime(2026,10,30,19,tzinfo=ZoneInfo('Asia/Shanghai')))
        self.clock.start()
        self.sig=dict(asof='2026-10-28',valid_for='2026-10-29',ranks=['000001.SZ','000002.SZ','000003.SZ','000004.SZ','000005.SZ','000006.SZ'],
            quotes={f'{i:06d}.SZ':dict(name=str(i),close=10.,volume20=100000.,is_st=False,paused=False) for i in range(1,7)})
        self.signal=patch.object(self.desk,'signal',return_value=self.sig);self.signal.start()
    def tearDown(self):
        self.signal.stop();self.clock.stop();self.calendar.stop();self.temp.cleanup()
    def fill(self,kind,date='2026-10-29',**kw):
        d=dict(symbol='000001.SZ',date=date,quantity=100,price=10,fee=5,reference='')
        d.update(kw);return self.desk.action(kind,d)
    def test_initial_account_and_does_not_infer_fills(self):
        s=self.desk.snapshot()
        self.assertEqual(s['cash'],10000)
        self.assertEqual(s['equity'],10000)
        self.assertEqual(s['positions'],[])
        self.assertEqual(len(s['plan']['selected']),5)
        self.assertEqual(len(s['events']),0)
    def test_start_boundary_and_t_plus_one(self):
        with self.assertRaises(ValueError):self.fill('buy',date='2026-10-28')
        self.fill('buy')
        with self.assertRaisesRegex(ValueError,'T\+1'):self.fill('sell')
        self.fill('sell',date='2026-10-30')
        self.assertEqual(self.desk.account()['cash'],9990)
        self.assertEqual(self.desk.account()['positions'],[])
    def test_insufficient_cash_duplicate_and_void_atomicity(self):
        with self.assertRaises(ValueError):self.fill('buy',quantity=1100)
        self.assertEqual(self.desk.events(),[])
        self.fill('buy',reference='fill-1')
        with self.assertRaisesRegex(ValueError,'编号'):self.fill('buy',reference='fill-1')
        self.fill('sell',date='2026-10-30')
        with self.assertRaises(ValueError):self.desk.action('void',{'id':1})
        self.assertFalse(self.desk.events()[0]['voided'])
    def test_independent_ledgers_and_opening_plan_freeze(self):
        other=Desk(Path(self.temp.name)/'other')
        self.fill('buy')
        self.assertEqual(other.account()['cash'],10000)
        prices={s:10 for s in self.sig['ranks']}
        self.desk.action('plan',{'date':'2026-10-29','prices':prices})
        with self.assertRaisesRegex(ValueError,'已冻结'):self.desk.action('plan',{'date':'2026-10-29','prices':prices})
        self.assertEqual(self.desk.account()['cash'],8995)
    def test_integer_lots_and_affordability(self):
        with self.assertRaises(ValueError):self.fill('buy',quantity=10)
        self.sig['quotes']['000001.SZ']['close']=30
        p=self.desk.plan(self.desk.account(),self.sig)
        self.assertNotIn('000001.SZ',p['selected'])
        self.assertEqual(len(p['selected']),5)
        self.assertTrue(all(r['target']%100==0 for r in p['rows']))
    def test_targets_stay_frozen_after_partial_fills_and_cash_is_not_spent_by_plan(self):
        prices={s:10 for s in self.sig['ranks']}
        self.desk.action('plan',{'date':'2026-10-29','prices':prices})
        before=self.desk.snapshot()['plan']['targets']
        self.assertEqual(self.desk.account()['cash'],10000)
        self.fill('buy',quantity=100,price=11)
        after=self.desk.snapshot()['plan']['targets']
        self.assertEqual(before,after)
        self.assertEqual(self.desk.account()['cash'],8895)
    def test_price_only_preview_and_confirm_do_not_add_slippage_or_fake_fills(self):
        d=dict(date='2026-10-29',revision=0,fills=[dict(symbol='000001.SZ',price=10)])
        p=self.desk.action('batch_preview',d)
        self.assertEqual(self.desk.events(),[])
        self.assertEqual(p['rows'][0]['quantity'],100)
        self.assertEqual(p['rows'][0]['amount'],1000)
        self.assertEqual(p['rows'][0]['fee'],5)
        with self.assertRaises(ValueError):self.desk.action('batch_fill',dict(d,signature=p['signature']))
        self.desk.action('batch_fill',dict(d,signature=p['signature'],attested=True))
        self.assertEqual(self.desk.account()['cash'],8995)
        self.assertEqual(len(self.desk.events()),2)
        self.assertEqual(self.desk.events()[1]['data']['fee_source'],'estimated_policy')
        with self.assertRaises(ValueError):self.desk.action('batch_fill',dict(d,signature=p['signature'],attested=True))
        self.assertEqual(len(self.desk.events()),2)
    def test_price_only_partial_override_and_atomic_validation(self):
        self.sig['quotes']['000001.SZ']['close']=5
        d=dict(date='2026-10-29',revision=0,fills=[dict(symbol='000001.SZ',price=5,quantity=100,fee=1)])
        p=self.desk.action('batch_preview',d)
        self.assertEqual(p['rows'][0]['quantity'],100)
        self.assertFalse(p['rows'][0]['fee_estimated'])
        with self.assertRaises(ValueError):self.desk.action('batch_fill',dict(d,signature='stale',attested=True))
        self.assertEqual(self.desk.events(),[])
        bad=dict(d,fills=d['fills']+[dict(symbol='999999.SZ',price=5)])
        with self.assertRaises(ValueError):self.desk.action('batch_preview',bad)
        self.assertEqual(self.desk.events(),[])
        self.desk.action('batch_fill',dict(d,signature=p['signature'],attested=True))
        self.assertEqual(self.desk.account()['cash'],9499)


if __name__=='__main__':unittest.main()
