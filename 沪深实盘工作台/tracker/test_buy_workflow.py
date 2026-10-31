import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from service import Tracker
import market

SESSIONS=['2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23','2026-10-26','2026-10-27','2026-11-18','2026-11-19','2026-11-20']

class BuyWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.t=Tracker(self.tmp.name)
        self.clock=datetime(2026,10,20,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.stack=ExitStack()
        self.stack.enter_context(patch('service.now',side_effect=lambda:self.clock))
        self.stack.enter_context(patch('store.now',side_effect=lambda:self.clock))
        self.stack.enter_context(patch('service.market.calendar_extended',return_value=SESSIONS))
        self.stack.enter_context(patch('service.market.raw_marks',return_value={}))
        self.t.info=dict(status='ready',market_date='2026-10-20',signal_filter_policy=market.SIGNAL_FILTER_POLICY_ID,
            signals=[dict(id='next',symbol='600010.SH',name='新推荐',rank=1,signal_date='2026-10-20',trigger=10.,atr=.03)])
    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def order(self,signal_date='2026-10-19',id='old',symbol='600000.SH'):
        self.t.ledger.append('accept',dict(signal_id=id,symbol=symbol,name='旧买单',signal_date=signal_date,atr=.03,trigger=10.,quantity=700))
    def skip(self,id='old',**change):
        s=self.t.snapshot();o=s['all_orders'][id]
        d=dict(order_id=id,day=s['buy_review_session'],filled_at_review=o['filled'],order_event_id=o['event_id'],attested=True);d.update(change)
        return self.t.action('buy_review',d)
    def buy(self,quantity=700):
        return self.t.action('buy',dict(order_id='old',date='2026-10-20',quantity=quantity,price=9.98,fee=5))
    def test_no_order_and_tonight_new_order_do_not_require_premature_check(self):
        self.assertEqual(self.t.snapshot()['buy_result_tasks'],[])
        self.order('2026-10-20')
        self.assertEqual(self.t.snapshot()['buy_result_tasks'],[])
    def test_existing_order_blocks_review_accept_finish_and_hides_signals(self):
        self.order();self.t.ledger.confirm('2026-10-20',100000,100000)
        s=self.t.snapshot();self.assertEqual(s['tasks'][0]['type'],'buy_result');self.assertFalse(s['confirmed']);self.assertEqual(s['signals'],[])
        self.assertTrue(next(x for x in s['tasks'] if x['type']=='review')['blocked'])
        for kind,d in [('review',dict(cash=100000,equity=100000,attested=True)),('accept',dict(signal_id='next',quantity=700)),('finish',{})]:
            with self.assertRaises(ValueError):self.t.action(kind,d)
    def test_skip_preserves_financials_order_and_slot_then_allows_review(self):
        self.order();before=self.t.snapshot();s=self.skip()
        self.assertEqual(s['cash'],before['cash']);self.assertEqual(s['positions'],[]);self.assertEqual(s['free_slots'],4)
        self.assertEqual(s['orders'][0]['quantity'],700);self.assertEqual(s['orders'][0]['expiry'],before['orders'][0]['expiry'])
        self.assertEqual(s['buy_result_tasks'],[]);self.assertFalse(s['confirmed']);self.assertEqual(s['signals'],[])
        with self.assertRaises(ValueError):self.skip()
        s=self.t.action('review',dict(cash=100000,equity=100000,attested=True))
        self.assertTrue(s['confirmed']);self.assertEqual(len(s['signals']),1)
    def test_full_fill_updates_cash_position_and_clears_order_gate_immediately(self):
        self.order();s=self.buy()
        self.assertEqual(s['orders'],[]);self.assertEqual(s['buy_result_tasks'],[]);self.assertEqual(s['occupied'],1)
        self.assertEqual(s['cash'],93009);self.assertEqual(s['positions'][0]['quantity'],700)
        self.assertTrue(any(t['type']=='protection' for t in s['tasks']));self.assertFalse(s['confirmed'])
    def test_partial_fill_requires_explicit_remainder_resolution(self):
        self.order();s=self.buy(200)
        self.assertEqual(s['orders'][0]['filled'],200);self.assertEqual(s['buy_result_tasks'][0]['type'],'cancel')
        with self.assertRaises(ValueError):self.skip()
        with self.assertRaises(ValueError):self.t.action('review',dict(cash=s['cash'],equity=s['equity'],attested=True))
        s=self.t.action('cancel',dict(order_id='old'))
        self.assertEqual(s['buy_result_tasks'],[]);self.assertEqual(s['positions'][0]['quantity'],200);self.assertEqual(s['occupied'],1)
    def test_daily_check_reappears_after_next_trading_session_not_premarket(self):
        self.order();self.skip();self.clock=datetime(2026,10,21,8,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(self.t.snapshot()['buy_result_tasks'],[])
        self.clock=datetime(2026,10,21,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(len(self.t.snapshot()['buy_result_tasks']),1)
    def test_weekend_uses_last_completed_trading_session(self):
        self.order('2026-10-22');self.clock=datetime(2026,10,25,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(self.t.snapshot()['buy_review_session'],'2026-10-23');self.skip()
        self.clock=datetime(2026,10,26,8,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(self.t.snapshot()['buy_result_tasks'],[])
        self.clock=datetime(2026,10,26,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(len(self.t.snapshot()['buy_result_tasks']),1)

    def test_weekend_daytime_review_and_buy_check_share_friday_cycle(self):
        self.order('2026-10-22')
        self.clock=datetime(2026,10,24,14,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(self.t.cycle(),'2026-10-23')
        self.skip()
        with patch.object(self.t,'update'):
            self.t.action('review',dict(cash=100000,equity=100000,expected_cash=100000,expected_revision=2,attested=True))
        self.assertTrue(self.t.snapshot()['confirmed'])
        for y,m,d,h in [(2026,10,25,14),(2026,10,26,8)]:
            self.clock=datetime(y,m,d,h,tzinfo=ZoneInfo('Asia/Shanghai'))
            self.assertEqual(self.t.cycle(),'2026-10-23')
            self.assertTrue(self.t.snapshot()['confirmed'])
            self.assertFalse(self.t.snapshot()['buy_result_tasks'])

    def test_formal_calendar_holiday_allowed_and_trading_day_boundaries(self):
        sessions=['2026-09-30','2026-10-09']
        with patch('service.market.calendar_extended',return_value=sessions):
            self.clock=datetime(2026,10,1,14,tzinfo=ZoneInfo('Asia/Shanghai'))
            self.assertTrue(self.t.review_window_open(self.clock))
            self.assertEqual(self.t.cycle(),'2026-09-30')
            for hour,minute,allowed in [(9,29,True),(9,30,False),(18,59,False),(19,0,True)]:
                self.clock=datetime(2026,10,9,hour,minute,tzinfo=ZoneInfo('Asia/Shanghai'))
                self.assertEqual(self.t.review_window_open(self.clock),allowed)
    def test_expired_order_cannot_be_skipped_as_still_live(self):
        self.order('2026-10-19');self.clock=datetime(2026,10,26,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.assertEqual(self.t.snapshot()['buy_result_tasks'][0]['type'],'cancel')
        with self.assertRaises(ValueError):self.skip()
    def test_wrong_date_stale_quantity_no_attestation_and_midday_skip_rejected(self):
        self.order()
        for d in [dict(day='2026-10-21'),dict(filled_at_review=100),dict(order_event_id=999),dict(attested=False)]:
            with self.assertRaises(ValueError):self.skip(**d)
        self.clock=datetime(2026,10,20,12,tzinfo=ZoneInfo('Asia/Shanghai'))
        with self.assertRaises(ValueError):self.skip()
        self.assertEqual(self.buy()['positions'][0]['quantity'],700)
    def test_void_check_reopens_gate_and_order_dependency_is_protected(self):
        self.order();self.skip()
        with self.assertRaises(ValueError):self.t.ledger.void(1)
        self.t.action('void',dict(event_id=2));self.assertEqual(len(self.t.snapshot()['buy_result_tasks']),1)
    def test_update_stops_before_model_prediction_even_with_old_cash_confirmation(self):
        self.order();self.t.ledger.confirm('2026-10-20',100000,100000)
        with patch('service.market.refresh_calendar'),patch('service.market.health',return_value=dict(market_date='2026-10-20',audit='fixture',sessions=SESSIONS)),patch('service.market.predict') as predict:
            self.t.update(background=False)
        self.assertEqual(self.t.info['status'],'awaiting_buy_results');self.assertEqual(self.t.info['signals'],[]);predict.assert_not_called()

if __name__=='__main__':unittest.main()
