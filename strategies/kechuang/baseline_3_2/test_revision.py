import datetime as dt
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pandas as pd
from research_contract import historical_members, stop_labels_before_cutoff, capacity_fill

HERE = Path(__file__).resolve().parent


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.now = dt.datetime(2026, 10, 9, 9, 31)
        self.g = NS(order_locks={}, order_intent={}, early_events={}, submitting=False,
                    seen_fills={}, position_state={}, adjustment_anchor={},
                    daily_buy_value=0., daily_sell_value=0.)
        self.ns = {'g': self.g, 'np': np, 'pd': pd, 'get_datetime': lambda: self.now,
                   'log': NS(info=self.logs.append, warn=self.logs.append)}
        exec(compile((HERE / 'runtime.py').read_text(encoding='utf-8'), 'runtime', 'exec'), self.ns)

    def test_sync_callback_and_duplicate(self):
        e = NS(order_id=10, status='FILLED', filled_amount=200, avg_price=10)
        def order(symbol, weight):
            self.ns['on_order'](None, e)
            return 10
        self.ns['order_target_percent'] = order
        self.ns['_place']('688001.SH', 'BUY', None)
        self.assertEqual(self.g.daily_buy_value, 2000)
        self.assertFalse(self.g.order_locks)
        self.ns['on_order'](None, e)
        self.assertEqual(self.g.daily_buy_value, 2000)

    def test_partial_average_price_cancel(self):
        self.g.order_intent[1] = {'symbol': '688001.SH', 'action': 'BUY'}
        for qty, price, status in [(200, 10, 'PARTIALLY_FILLED'), (300, 11, 'CANCELLED')]:
            self.ns['_process_order']({'id': 1, 'status': status, 'filled': qty, 'price': price})
        self.assertEqual(self.g.daily_buy_value, 3300)
        self.assertEqual(self.g.position_state['688001.SH']['entry'], 11)

    def test_expiry_small_position(self):
        for amount in [200, 399, 400, 1000]:
            state = {'entry': 10., 'half': False, 'entry_date': self.now.date() - dt.timedelta(days=60)}
            self.assertEqual(self.ns['_exit_action'](12.5, state, amount, self.now.date(), 40), ('TIME60', 0))

    def test_adjustment_same_anchor_and_idempotence(self):
        self.g.position_state['x'] = {'entry': 20.}
        self.g.adjustment_anchor['x'] = {'date': '2026-10-07', 'close': 24.}
        frame = pd.DataFrame({'close': [12., 13.]}, index=pd.to_datetime(['2026-10-07', '2026-10-08']))
        self.ns['_adjust_entry']('x', frame)
        self.assertEqual(self.g.position_state['x']['entry'], 10.)
        self.ns['_adjust_entry']('x', frame)
        self.assertEqual(self.g.position_state['x']['entry'], 10.)

    def test_past_excludes_today_and_future(self):
        frame = pd.DataFrame({'close': [1, 999, 999]}, index=pd.to_datetime(['2026-10-08', '2026-10-09', '2026-10-12']))
        self.assertEqual(len(self.ns['_past'](frame, self.now.date())), 1)

    def test_delisted_stock_retained(self):
        meta = pd.DataFrame({'ipoDate': ['2020-01-01', '2027-01-01'], 'outDate': ['2024-01-01', '']})
        self.assertEqual(len(historical_members(meta, '2020-01-01', '2026-01-01')), 1)

    def test_labels_never_read_next_year(self):
        dates = pd.bdate_range('2024-11-01', '2025-02-01')
        frame = pd.DataFrame({'date': dates, 'symbol': 'x', 'open': 10., 'close': 10.})
        first = stop_labels_before_cutoff(frame)
        frame.loc[frame.date >= '2025-01-01', 'open'] = .01
        second = stop_labels_before_cutoff(frame)
        pd.testing.assert_frame_equal(first, second)
        self.assertTrue((first.label_end <= pd.Timestamp('2024-12-31')).all())

    def test_capacity_counterexample(self):
        self.assertEqual(capacity_fill(4990, 1000), 250)
        self.assertEqual(capacity_fill(4990, 1000, used=200), 50)


if __name__ == '__main__':
    unittest.main()
