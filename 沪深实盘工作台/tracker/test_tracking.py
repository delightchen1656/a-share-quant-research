import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
from performance import tracking,daily_final_curve
from store import Ledger, REVIEW_POLICY
from service import Tracker


class TrackingTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.ledger=Ledger(self.root/'ledger.sqlite3')
        self.sessions=['2026-10-19','2026-10-20','2026-10-21','2026-10-22']

    def tearDown(self):self.tmp.cleanup()

    def test_atomic_cash_overwrite_and_stale_revision(self):
        self.ledger.review_cash('2026-10-21',101000,101000,100000,0,'external','入金')
        self.assertEqual(self.ledger.state()['cash'],101000)
        self.assertEqual(self.ledger.confirmation('2026-10-21')['policy'],REVIEW_POLICY)
        self.assertEqual(self.ledger.events()[0]['data']['flow_type'],'external')
        with self.assertRaises(ValueError):self.ledger.review_cash('2026-10-21',100000,100000,101000,0,'reconciliation','旧窗口')
        self.assertEqual(self.ledger.state()['cash'],101000)
        self.assertEqual(len(self.ledger.events()),1)

    def test_invalid_cash_review_does_not_partially_write(self):
        with self.assertRaises(ValueError):self.ledger.review_cash('2026-10-21',0,100000,100000,0,'invalid','')
        self.assertEqual(self.ledger.events(),[])
        self.assertIsNone(self.ledger.confirmation('2026-10-21'))

    def test_deposit_is_not_profit_and_difference_is(self):
        self.ledger.append('cash_adjust',dict(date='2026-10-19',amount=5000,flow_type='external',note='入金'))
        self.ledger.observe('deposit','2026-10-19','cash_adjust',105000,105000)
        self.ledger.append('cash_adjust',dict(date='2026-10-20',amount=-10,flow_type='reconciliation',note='费用差额'))
        self.ledger.observe('fee','2026-10-20','cash_set',104990,104990)
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertEqual([d['pnl'] for d in result['daily']],[0,-10,0])
        self.assertEqual([d['net_equity'] for d in result['curve']],[100000,99990])

    def test_unclassified_legacy_adjustment_is_not_fabricated_profit(self):
        self.ledger.append('cash_adjust',dict(date='2026-10-19',amount=-90000,note='旧记录'))
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertIsNone(result['daily'][0]['pnl'])
        self.assertEqual(result['daily'][0]['status'],'unclassified_cash')
        self.assertEqual(len(result['unknown_cash_adjustments']),1)
        self.ledger.append('classify_cash',dict(event_id=1,flow_type='external'))
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertEqual(result['daily'][0]['pnl'],0)
        self.assertEqual(self.ledger.state()['cash'],10000)

    def test_daily_mark_to_market_actual_fees_and_missing_prices(self):
        self.ledger.append('accept',dict(signal_id='s',symbol='600000.SH',name='测试',signal_date='2026-10-16',atr=.03,trigger=10,quantity=100))
        self.ledger.append('buy',dict(order_id='s',date='2026-10-19',quantity=100,price=10,fee=5))
        (self.root/'raw/SH').mkdir(parents=True)
        pd.DataFrame(dict(date=pd.to_datetime(['2026-10-19','2026-10-20']),close=[10,11])).to_parquet(self.root/'raw/SH/600000.SH.parquet')
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertEqual([d['pnl'] for d in result['daily']],[-5,100,None])
        self.assertEqual(result['daily'][-1]['status'],'missing_price')
        self.ledger.confirm('2026-10-21',98995,100095)
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertIsNone(result['daily'][-1]['pnl'])

    def test_observation_keys_idempotent(self):
        self.ledger.observe('quote:x','2026-10-21','market_close',100000,100000)
        self.ledger.observe('quote:x','2026-10-21','market_close',100000,100000)
        self.assertEqual(len(tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')['curve']),1)

    def test_daily_curve_keeps_latest_time_then_id(self):
        points=[dict(id=1,day='2026-10-21',at='2026-10-21T21:00:00+08:00',equity=101),
                dict(id=2,day='2026-10-21',at='2026-10-21T20:00:00+08:00',equity=102),
                dict(id=3,day='2026-10-21',at='2026-10-21T21:00:00+08:00',equity=103),
                dict(id=4,day='2026-10-20',at='2026-10-21T01:00:00+08:00',equity=99)]
        self.assertEqual([(p['day'],p['equity']) for p in daily_final_curve(points)],[('2026-10-20',99),('2026-10-21',103)])
        self.assertEqual(len(points),4)

    def test_curve_only_trading_days_preserves_weekend_and_holiday_sources(self):
        sessions=['2026-09-30','2026-10-09']
        for day in ['2026-09-30','2026-10-01','2026-10-03','2026-10-09']:
            self.ledger.observe(day,day,'review',100000,100000)
        result=tracking(self.ledger,sessions,'2026-10-09',self.root,'2026-10-09')
        self.assertEqual([p['day'] for p in result['curve']],sessions)
        with self.ledger.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM account_observations').fetchone()[0],4)
        self.assertEqual(daily_final_curve(result['curve'],[]),[])

    def test_daily_curve_does_not_delete_observations_or_fallback_from_latest_unknown(self):
        self.ledger.observe('early','2026-10-21','market_close',100000,100000)
        self.ledger.append('cash_adjust',dict(date='2026-10-21',amount=100,flow_type='unknown',note='待分类'))
        self.ledger.observe('late','2026-10-21','review',100100,100100)
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertEqual(len(result['curve']),1)
        self.assertEqual(result['curve'][0]['equity'],100100)
        self.assertIsNone(result['curve'][0]['net_equity'])
        with self.ledger.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM account_observations').fetchone()[0],2)

    def test_real_opening_basis_replaces_test_capital_without_fake_profit(self):
        with self.ledger.connect() as db:
            for key,value in dict(initial_cash=5679.96,performance_min_revision=2,pnl_baseline_date='2026-10-19').items():
                db.execute('INSERT INTO account_settings VALUES(?,?)',(key,json.dumps(value)))
        self.ledger.observe('test_setup','2026-10-18','legacy_review',5679.96,5679.96)
        self.ledger.append('cash_adjust',dict(date='2026-10-19',amount=1470.29,flow_type='reconciliation',note='真实值'))
        self.assertEqual(self.ledger.state()['cash'],7150.25)
        self.ledger.append('cash_adjust',dict(date='2026-10-20',amount=-5,flow_type='reconciliation',note='实际费用'))
        self.ledger.observe('real','2026-10-20','cash_adjust',7145.25,7145.25)
        result=tracking(self.ledger,self.sessions,'2026-10-21',self.root,'2026-10-22')
        self.assertEqual(len(result['curve']),1)
        self.assertIsNone(result['daily'][0]['pnl'])
        self.assertEqual(result['daily'][0]['status'],'opening_baseline')
        self.assertEqual(result['daily'][1]['pnl'],-5)

    def test_old_finished_marker_never_bypasses_new_cash_review(self):
        tracker=Tracker(self.root)
        (self.root/'finished_2026-10-21.json').write_text('{}')
        clock=datetime(2026,10,21,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=self.sessions):
            self.assertFalse(tracker.snapshot()['finished'])

    def test_1900_close_updates_without_cash_review_but_1830_does_not(self):
        tracker=Tracker(self.root)
        tracker.info=dict(status='waiting',market_date='2026-10-20',settlement_date='2026-10-20',signals=[])
        h=dict(market_date='2026-10-21',audit='test',sessions=self.sessions)
        with patch('service.market.refresh_calendar'),patch('service.market.calendar_extended',return_value=self.sessions),patch('service.market.health',return_value=h),patch('service.market.predict') as predict:
            with patch('service.now',return_value=datetime(2026,10,21,18,30,tzinfo=ZoneInfo('Asia/Shanghai'))):
                tracker.update(background=False)
                self.assertEqual(tracker.info['settlement_date'],'2026-10-20')
            with patch('service.now',return_value=datetime(2026,10,21,19,0,tzinfo=ZoneInfo('Asia/Shanghai'))):
                tracker.update(background=False)
                self.assertEqual(tracker.info['settlement_date'],'2026-10-21')
                self.assertEqual(tracker.snapshot()['performance']['asof'],'2026-10-21')
                self.assertFalse(tracker.snapshot()['confirmed'])
                self.assertEqual(tracker.info['status'],'awaiting_review')
                self.assertEqual(len(tracker.snapshot()['account_curve']),1)
            predict.assert_not_called()

    def test_daytime_reopen_settles_committed_previous_session(self):
        tracker=Tracker(self.root)
        tracker.info=dict(status='waiting',market_date='2026-10-20',settlement_date='2026-10-20',signals=[])
        h=dict(market_date='2026-10-22',audit='test',sessions=self.sessions)
        clock=datetime(2026,10,24,14,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.refresh_calendar'),patch('service.market.calendar_extended',return_value=self.sessions),patch('service.market.health',return_value=h),patch('service.market.predict') as predict:
            tracker.update(background=False)
        self.assertEqual(tracker.info['settlement_date'],'2026-10-22')
        self.assertEqual(tracker.info['status'],'awaiting_review')
        predict.assert_not_called()

    def test_close_never_presents_previous_close_as_today(self):
        tracker=Tracker(self.root)
        tracker.info=dict(status='waiting',market_date='2026-10-20',settlement_date='2026-10-20',signals=[])
        tracker.ledger.append('accept',dict(signal_id='s',symbol='600000.SH',signal_date='2026-10-16',atr=.03,trigger=10.,quantity=100))
        tracker.ledger.append('buy',dict(order_id='s',date='2026-10-19',quantity=100,price=10,fee=5))
        h=dict(market_date='2026-10-21',audit='test',sessions=self.sessions)
        clock=datetime(2026,10,21,19,tzinfo=ZoneInfo('Asia/Shanghai'))
        with patch('service.now',return_value=clock),patch('service.market.refresh_calendar'),patch('service.market.health',return_value=h),patch('service.market.raw_marks',return_value={'600000.SH':dict(date='2026-10-20',price=10)}):
            tracker.update(background=False)
        self.assertEqual(tracker.info['status'],'blocked')
        self.assertEqual(tracker.info['settlement_date'],'2026-10-20')
        self.assertIn('缺少当日原始收盘价',tracker.info['message'])

    def test_review_overwrites_then_auto_updates_and_blocks_after_cash_change(self):
        tracker=Tracker(self.root)
        clock=datetime(2026,10,21,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        tracker.info=dict(status='ready',market_date='2026-10-21',signal_filter_policy=__import__('market').SIGNAL_FILTER_POLICY_ID,signals=[])
        with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=self.sessions),patch.object(tracker,'update') as update:
            result=tracker.action('review',dict(cash=99990,equity=99990,expected_cash=100000,expected_revision=0,flow_type='reconciliation',attested=True))
            self.assertTrue(result['confirmed']);self.assertEqual(result['cash'],99990)
            update.assert_called_once_with(background=True)
            result=tracker.action('cash_adjust',dict(amount=1000,note='入金',flow_type='external'))
            self.assertFalse(result['confirmed']);self.assertEqual(result['signals'],[])
            self.assertEqual(result['tasks'][0]['type'],'review')
            self.assertEqual(len(result['account_curve']),1)
            with tracker.ledger.connect() as db:
                self.assertGreaterEqual(db.execute('SELECT COUNT(*) FROM account_observations').fetchone()[0],2)


if __name__=='__main__':unittest.main()
