"""Offline formula + schedule + order smoke tests; does not emulate platform fills."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from datetime import date, datetime
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.modules.setdefault('mindgo_api', types.ModuleType('mindgo_api'))
spec = importlib.util.spec_from_file_location('r08_export', HERE / 'supermind_mainboard_baseline_1.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class R08Tests(unittest.TestCase):
    def test_calendar(self):
        self.assertTrue(m.rebalance_due(date(2020, 2, 17), None))
        self.assertFalse(m.rebalance_due(date(2020, 2, 18), 202002))
        self.assertTrue(m.rebalance_due(date(2020, 3, 2), 202002))
        self.assertFalse(m.rebalance_due(date(2020, 4, 1), 202003))
        self.assertTrue(m.rebalance_due(date(2021, 1, 4), 202012))

    def test_mainboard(self):
        for s in ['600001.SH', '605001.SH', '000001.SZ', '003001.SZ']:
            self.assertTrue(m.ordinary_mainboard(s))
        for s in ['688001.SH', '300001.SZ', '830001.BJ', '900001.SH']:
            self.assertFalse(m.ordinary_mainboard(s))

    def test_past_only(self):
        x = pd.DataFrame({'close': [1, 2, 999]}, index=pd.date_range('2020-01-01', periods=3))
        self.assertEqual(len(m.past_bars(x, date(2020, 1, 3))), 2)

    def test_affordability_retention(self):
        ranked = ['S%d' % i for i in range(60)]
        prices = dict.fromkeys(ranked, 10.)
        prices['S0'] = 1000.
        selected = m.select_affordable(ranked, ['S23', 'S24'], prices, 100000)
        self.assertEqual(selected[0], 'S23')
        self.assertEqual(len(selected), 12)
        self.assertNotIn('S0', selected)
        self.assertNotIn('S24', selected)

    def test_tied_ranks(self):
        f = pd.DataFrame(dict(symbol=['S%02d' % i for i in range(30)],
                              float_cap_proxy=np.arange(30), long_risk=1.,
                              market_adjusted=1., distribution_proxy=0., vol60=.02,
                              ret5=0., turn20=1.))
        ranked = m.rank_candidates(f)
        # rank(pct=True), average ties, floor(percentile*3) includes ranks10..19.
        self.assertEqual(list(ranked.symbol), ['S%02d' % i for i in range(9, 19)])
        self.assertTrue(np.allclose(ranked.score, .52))

    def test_order_smoke(self):
        state = types.SimpleNamespace
        m.g = state(pending_date=date(2020, 1, 2), ranked=['S%d' % i for i in range(60)], holding_order=[])
        m.get_datetime = lambda: datetime(2020, 1, 2, 9, 31)
        m.log = state(info=lambda x: None, warn=lambda x: None)
        account = state(total_value=100000., available_cash=100000.)
        context = state(portfolio=state(positions={}, stock_account=account))
        bars = {s: state(open=10., volume=100000., high_limit=11., low_limit=9., is_paused=False)
                for s in m.g.ranked}
        orders = []
        def order(s, qty):
            orders.append((s, qty))
            account.available_cash -= qty * 10.02 + max(5, qty * 10.02 * .0003)
            return 'mock'
        m.order = order
        m.handle_bar(context, bars)
        self.assertEqual(len(orders), 12)
        self.assertTrue(all(q == 700 for s, q in orders))
        self.assertGreater(account.available_cash, 0)
        m.handle_bar(context, bars)
        self.assertEqual(len(orders), 12)

    def test_local_feature_parity(self):
        self.skipTest('historical multi-gigabyte parity fixture was intentionally removed in the minimal-core cleanup')


if __name__ == '__main__':
    unittest.main(verbosity=2)
