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

    def test_state_driven_tasks(self):
        t=Tracker(self.tmp.name)
        sessions=['2026-10-16','2026-10-19','2026-10-20','2026-11-18']
        clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=sessions):
            t.info=dict(status='ready',market_date='2026-10-19',signals=[dict(id='s1',symbol='600000.SH',name='示例',rank=1,signal_date='2026-10-19',trigger=10.,atr=.024)])
            self.assertEqual(t.snapshot()['signals'],[])
            t.action('review',dict(cash=100000,equity=100000,attested=True))
            self.assertEqual(len(t.snapshot()['signals']),1)
            t.action('accept',dict(signal_id='s1',quantity=1900))
            self.assertEqual(t.snapshot()['occupied'],1)
            with self.assertRaises(ValueError): t.action('accept',dict(signal_id='s1',quantity=1900))
            self.assertFalse(any(x['type']=='protection' for x in t.snapshot()['tasks']))

    def test_full_slots_hide_buy_tasks_and_recheck_after_fill(self):
        t=Tracker(self.tmp.name)
        sessions=['2026-10-16','2026-10-19','2026-10-20','2026-11-18']
        clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=sessions):
            for i in range(5):
                t.ledger.append('accept',dict(signal_id=f's{i}',symbol=f'60000{i}.SH',name=f'股票{i}',signal_date='2026-10-16',atr=.024,trigger=10.,quantity=1900))
            t.info=dict(status='ready',market_date='2026-10-19',signals=[dict(id='new',symbol='600010.SH',name='新信号',rank=1,signal_date='2026-10-19',trigger=10.,atr=.024)])
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
