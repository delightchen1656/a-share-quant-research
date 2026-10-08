import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd

PATH = Path(__file__).with_name("local_backtest.py")
sys.path.insert(0, str(PATH.parent))
SPEC = importlib.util.spec_from_file_location("local_backtest", PATH)
BT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = BT
SPEC.loader.exec_module(BT)


def bar(**changes):
    values = dict(open=10.0, high=10.5, low=9.5, preclose=10.0,
                  volume=100000, tradestatus=1, isST=0)
    values.update(changes)
    return pd.Series(values)


class ExecutionRulesTest(unittest.TestCase):
    def test_t_plus_one(self):
        a = BT.Account()
        d = pd.Timestamp("2025-01-02")
        self.assertGreater(a.buy(d, 1000, bar()), 0)
        self.assertEqual(a.sell(d, 1000, bar()), 0)
        self.assertGreater(a.sell(d + pd.Timedelta(days=1), 1000, bar()), 0)

    def test_price_limits_block_direction(self):
        d = pd.Timestamp("2025-01-02")
        a = BT.Account()
        self.assertEqual(a.buy(d, 1000, bar(open=11.0, high=11.0)), 0)
        self.assertGreater(a.buy(d, 1000, bar()), 0)
        self.assertEqual(a.sell(d + pd.Timedelta(days=1), 1000,
                                bar(open=9.0, low=9.0)), 0)

    def test_lot_cash_and_capacity(self):
        d = pd.Timestamp("2025-01-02")
        a = BT.Account()
        filled = a.buy(d, 999999, bar(volume=10000))
        self.assertEqual(filled, 500)
        self.assertEqual(filled % 100, 0)
        self.assertGreaterEqual(a.cash, 0)

    def test_suspension_blocks_order(self):
        a = BT.Account()
        self.assertEqual(a.buy(pd.Timestamp("2025-01-02"), 1000,
                               bar(tradestatus=0, volume=0)), 0)

    def test_dividend_tax_by_holding_period(self):
        a = BT.Account()
        buy = pd.Timestamp("2025-01-02")
        a.buy(buy, 1000, bar())
        a.dividend(pd.Timestamp("2025-01-10"), pd.Timestamp("2025-01-10"), 0.5)
        a.sell(pd.Timestamp("2025-01-20"), 1000, bar())
        self.assertEqual(a.trades[-1]["dividend_tax"], 100.0)


if __name__ == "__main__":
    unittest.main()
