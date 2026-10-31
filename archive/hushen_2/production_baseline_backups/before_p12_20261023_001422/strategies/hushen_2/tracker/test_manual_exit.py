import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from service import Tracker

SESSIONS=['2026-09-15','2026-09-16','2026-10-15','2026-10-16','2026-10-19','2026-10-20','2026-11-18']


class ManualExitTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.tracker=Tracker(self.tmp.name)
        l=self.tracker.ledger
        l.append('accept',dict(signal_id='old',symbol='600000.SH',name='测试持仓',signal_date='2026-09-15',atr=.024,trigger=10.,quantity=1900))
        l.append('buy',dict(order_id='old',date='2026-09-16',quantity=1900,price=10.,fee=5.7))
        l.append('protection',dict(symbol='600000.SH'))
        self.tracker.info=dict(status='ready',market_date='2026-10-16',message='test',signals=[])

    def tearDown(self):self.tmp.cleanup()

    def snapshot(self,date):
        clock=datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('store.now',return_value=clock),patch('service.market.calendar_extended',return_value=SESSIONS),patch('service.market.raw_marks',return_value={}):
            return self.tracker.snapshot()

    def test_not_early_and_weekend_uses_verified_session(self):
        self.assertEqual(self.snapshot('2026-10-15T20:00')['manual_exit_alerts'],[])
        s=self.snapshot('2026-10-16T20:00')
        self.assertEqual(s['manual_exit_alerts'][0]['manual_exit_date'],'2026-10-19')
        self.assertEqual(s['manual_exit_alerts'][0]['status'],'upcoming')
        self.assertFalse(next(t for t in s['tasks'] if t['type']=='manual_exit')['blocks_finish'])

    def test_premarket_today_and_overdue(self):
        self.assertEqual(self.snapshot('2026-10-19T09:15')['manual_exit_alerts'][0]['status'],'today')
        self.assertEqual(self.snapshot('2026-10-20T20:00')['manual_exit_alerts'][0]['status'],'overdue')

    def test_repeated_read_never_changes_ledger_or_slot(self):
        before=self.tracker.ledger.events()
        a=self.snapshot('2026-10-16T20:00');b=self.snapshot('2026-10-19T09:15')
        self.assertEqual(before,self.tracker.ledger.events())
        self.assertEqual(a['occupied'],b['occupied'])
        self.assertEqual(a['positions'][0]['quantity'],1900)

    def test_partial_sell_continues_full_sell_removes(self):
        self.tracker.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-19',quantity=900,price=10.,fee=5.))
        s=self.snapshot('2026-10-19T20:00')
        self.assertEqual(s['manual_exit_alerts'][0]['quantity'],1000)
        self.assertEqual(s['occupied'],1)
        self.tracker.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-20',quantity=1000,price=10.,fee=5.))
        self.assertEqual(self.snapshot('2026-10-20T20:00')['manual_exit_alerts'],[])

    def test_old_expiry_confirmation_cannot_hide_reminder(self):
        self.tracker.ledger.append('expiry_order',dict(symbol='600000.SH'))
        self.assertEqual(len(self.snapshot('2026-10-16T20:00')['manual_exit_alerts']),1)

    def test_missing_calendar_blocks_false_exit_date(self):
        clock=datetime(2026,10,16,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=SESSIONS[:4]),patch('service.market.raw_marks',return_value={}):
            s=self.tracker.snapshot()
        self.assertEqual(s['manual_exit_alerts'],[])
        self.assertTrue(any(t['id']=='calendar_600000.SH' for t in s['tasks']))

    def test_after_open_task_remains_blocking_until_actual_record(self):
        s=self.snapshot('2026-10-19T20:00')
        self.assertTrue(next(t for t in s['tasks'] if t['type']=='manual_exit')['blocks_finish'])

    def test_legacy_scheduled_order_confirmation_is_rejected(self):
        clock=datetime(2026,10,16,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        before=self.tracker.ledger.events()
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=SESSIONS),patch('service.market.raw_marks',return_value={}):
            with self.assertRaisesRegex(ValueError,'手动卖出'):
                self.tracker.action('expiry_order',dict(symbol='600000.SH'))
        self.assertEqual(before,self.tracker.ledger.events())


if __name__=='__main__':unittest.main()
