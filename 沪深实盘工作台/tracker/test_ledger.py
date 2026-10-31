import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

from store import Ledger
from service import Tracker


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.ledger=Ledger(Path(self.tmp.name)/'ledger.sqlite3')

    def tearDown(self): self.tmp.cleanup()

    def test_actual_fill_anchor_and_old_model_confirmation_requires_review(self):
        oid=self.order()
        self.ledger.append('buy',dict(order_id=oid,date='2026-10-19',quantity=900,price=9.5,fee=5))
        p=self.ledger.state('2026-10-20')['positions'][0]
        self.assertEqual((p['model_base_price'],p['take'],p['stop']),(10.,10.41,9.16))
        self.assertEqual((p['average_price'],p['take_delta'],p['stop_delta']),(9.5,.91,-.34))
        self.assertLess(p['stop_delta_pct'],0)
        self.ledger.append('protection',dict(symbol='600000.SH'))
        p=self.ledger.state('2026-10-20')['positions'][0]
        self.assertFalse(p['protection_needs_review'])
        self.assertTrue(p['protection'])
        self.ledger.append('protection',dict(symbol='600000.SH',take=10.96,stop=9.64,policy='model_trigger_anchor_v1'))
        p=self.ledger.state('2026-10-20')['positions'][0]
        self.assertFalse(p['protection'])
        self.assertTrue(p['protection_needs_review'])
        self.ledger.append('protection',dict(symbol='600000.SH',take=10.41,stop=9.16,policy='actual_fill_anchor_v1'))
        p=self.ledger.state('2026-10-20')['positions'][0]
        self.assertTrue(p['protection'])
        self.assertFalse(p['protection_needs_review'])
        self.ledger.append('buy',dict(order_id=oid,date='2026-10-19',quantity=100,price=9.8,fee=5))
        p=self.ledger.state('2026-10-20')['positions'][0]
        self.assertEqual((p['take'],p['stop']),(10.44,9.19))
        self.assertAlmostEqual(p['average_price'],9.53)
        self.assertEqual((p['take_delta'],p['stop_delta']),(.91,-.34))

    def order(self,id='2026-10-16_600000.SH',symbol='600000.SH'):
        self.ledger.append('accept',dict(signal_id=id,symbol=symbol,name='示例',signal_date='2026-10-16',atr=.024,trigger=10.,quantity=1900))
        return id

    def test_actual_partial_buy_sell_and_replay(self):
        id=self.order()
        self.ledger.append('buy',dict(order_id=id,date='2026-10-19',quantity=900,price=9.98,fee=5))
        s=self.ledger.state('2026-10-19')
        self.assertEqual(s['occupied'],1)
        self.assertAlmostEqual(s['positions'][0]['take'],10.94)
        self.assertEqual(s['positions'][0]['stop'],9.62)
        self.assertFalse(s['positions'][0]['protection'])
        with self.assertRaises(ValueError): self.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-19',quantity=900,price=11,fee=5))
        self.ledger.append('cancel',{'order_id':id})
        self.ledger.append('protection',{'symbol':'600000.SH'})
        self.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-20',quantity=400,price=11,fee=6))
        s=self.ledger.state('2026-10-20')
        self.assertEqual(s['positions'][0]['quantity'],500)
        self.assertEqual(s['deferred'],4394)
        self.assertFalse(s['positions'][0]['protection'])
        self.assertAlmostEqual(self.ledger.state('2026-10-21')['cash']-s['cash'],4394)

    def test_dependent_undo_and_backup(self):
        id=self.order()
        self.ledger.append('buy',dict(order_id=id,date='2026-10-19',quantity=1900,price=10,fee=5))
        with self.assertRaises(ValueError): self.ledger.void(1)
        self.ledger.void(2); self.ledger.void(1)
        self.assertEqual(self.ledger.state()['cash'],100000)
        self.assertTrue(self.ledger.backup().exists())

    def test_restore_preserves_current_copy(self):
        backup=self.ledger.backup()
        self.order()
        preserved=self.ledger.restore(backup.name)
        self.assertTrue(preserved.exists())
        self.assertEqual(self.ledger.state()['occupied'],0)
        self.ledger.restore(preserved.name)
        self.assertEqual(self.ledger.state()['occupied'],1)

    def test_no_cash_or_oversell(self):
        id=self.order()
        with self.assertRaises(ValueError): self.ledger.append('buy',dict(order_id=id,date='2026-10-19',quantity=2000,price=10,fee=5))
        self.assertEqual(self.ledger.state()['cash'],100000)

    def test_unfilled_orders_do_not_reserve_or_debit_cash(self):
        id=self.order()
        s=self.ledger.state()
        self.assertEqual(s['cash'],100000)
        self.assertEqual(s['available'],100000)
        self.assertEqual(s['reserved'],0)
        self.assertEqual(s['free_slots'],4)
        self.ledger.append('buy',dict(order_id=id,date='2026-10-19',quantity=900,price=10.,fee=5))
        s=self.ledger.state('2026-10-19')
        self.assertEqual(s['cash'],90995)
        self.assertEqual(s['available'],90995)
        self.assertEqual(s['all_orders'][id]['quantity'],1900)
        self.ledger.append('cancel',dict(order_id=id))
        self.assertEqual(self.ledger.state('2026-10-19')['cash'],90995)

    def test_edit_cash_is_traced_and_stale_edits_rejected(self):
        t=Tracker(self.tmp.name)
        with patch('service.market.calendar_extended',return_value=['2026-10-19','2026-10-20','2026-10-21']):
            t.action('cash_set',dict(cash=99000,expected_cash=100000,note='核对现金差额'))
            self.assertEqual(t.ledger.state()['cash'],99000)
            event=t.ledger.events()[-1]
            self.assertEqual(event['kind'],'cash_adjust')
            self.assertEqual(event['data']['amount'],-1000)
            self.assertEqual(event['data']['source'],'cash_window')
            self.assertEqual(t.ledger.state()['realized'],0)
            with self.assertRaises(ValueError):t.action('cash_set',dict(cash=98000,expected_cash=100000,note='过期编辑'))
            with self.assertRaises(ValueError):t.action('cash_set',dict(cash=98000,expected_cash=99000,note=''))
            with self.assertRaises(ValueError):t.action('cash_set',dict(cash=-1,expected_cash=99000,note='负余额'))
            self.assertEqual(len(t.ledger.events()),1)

    def test_state_driven_tasks(self):
        t=Tracker(self.tmp.name)
        sessions=['2026-10-16','2026-10-19','2026-10-20','2026-11-18']
        clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=sessions):
            t.info=dict(status='ready',market_date='2026-10-19',signal_filter_policy=__import__('market').SIGNAL_FILTER_POLICY_ID,signals=[dict(id='s1',symbol='600000.SH',name='示例',rank=1,signal_date='2026-10-19',trigger=10.,atr=.03,size_proxy=18.,vol60=.03)])
            self.assertEqual(t.snapshot()['signals'],[])
            t.action('review',dict(cash=100000,equity=100000,attested=True))
            self.assertEqual(len(t.snapshot()['signals']),1)
            t.action('accept',dict(signal_id='s1',quantity=1900))
            self.assertEqual(t.snapshot()['occupied'],1)
            t.info['signals'][0]['atr']=.04
            self.assertEqual(t.snapshot()['signals'][0]['atr'],.03)
            self.assertEqual(t.snapshot()['signals'][0]['quantity'],1900)
            with self.assertRaises(ValueError): t.action('accept',dict(signal_id='s1',quantity=1900))
            self.assertFalse(any(x['type']=='protection' for x in t.snapshot()['tasks']))

    def test_full_slots_still_require_existing_buy_results_and_recheck_after_fill(self):
        t=Tracker(self.tmp.name)
        sessions=['2026-10-16','2026-10-19','2026-10-20','2026-11-18']
        clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=sessions):
            for i in range(5):
                t.ledger.append('accept',dict(signal_id=f's{i}',symbol=f'60000{i}.SH',name=f'股票{i}',signal_date='2026-10-16',atr=.024,trigger=10.,quantity=1900))
            t.info=dict(status='ready',market_date='2026-10-19',signal_filter_policy=__import__('market').SIGNAL_FILTER_POLICY_ID,signals=[dict(id='new',symbol='600010.SH',name='新信号',rank=1,signal_date='2026-10-19',trigger=10.,atr=.03,size_proxy=18.,vol60=.03)])
            self.assertEqual(len(t.snapshot()['buy_result_tasks']),5)
            with self.assertRaises(ValueError):t.action('review',dict(cash=100000,equity=100000,attested=True))
            for order in t.snapshot()['orders']:
                t.action('buy_review',dict(order_id=order['signal_id'],day='2026-10-19',filled_at_review=0,order_event_id=order['event_id'],attested=True))
            t.action('review',dict(cash=100000,equity=100000,attested=True))
            s=t.snapshot()
            self.assertEqual(s['free_slots'],0)
            self.assertFalse(any(x['type']=='signals' for x in s['tasks']))
            with self.assertRaises(ValueError): t.action('accept',dict(signal_id='new',quantity=1900))
            t.action('buy',dict(order_id='s0',date='2026-10-19',quantity=900,price=9.98,fee=5))
            s=t.snapshot()
            self.assertFalse(s['confirmed'])
            self.assertEqual(s['occupied'],5)
            self.assertTrue(any(x['type']=='protection' for x in s['tasks']))
            self.assertTrue(any(x['type']=='cancel' for x in s['tasks']))
            with self.assertRaises(ValueError): t.action('finish',{})


if __name__=='__main__': unittest.main()
