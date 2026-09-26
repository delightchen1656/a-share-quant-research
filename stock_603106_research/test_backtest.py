"""Boundary tests for the execution ledger, independent of actual research results."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import backtest as bt


class ExecutionTests(unittest.TestCase):
    @patch.object(bt, 'events', return_value=[])
    def test_minimum_calendar_month_leap_year(self, _):
        dates = pd.bdate_range('2024-01-30', '2024-03-04')
        raw = pd.DataFrame(dict(open=10., high=10., low=10., close=10., preclose=10.,
                                volume=1_000_000, tradestatus=1), index=dates)
        target = pd.Series(0, index=dates)
        target.iloc[0] = 1
        _, trades, blocked, _ = bt.simulate(raw, target, 'test', start='2024-01-31', min_hold_months=1)
        self.assertEqual(trades.date.iloc[0], pd.Timestamp('2024-01-31'))
        self.assertEqual(trades.date.iloc[1], pd.Timestamp('2024-02-29'))
        self.assertTrue(blocked.reason.eq('minimum_calendar_month_holding').all())

    def bars(self):
        dates = pd.to_datetime(['2021-12-31', '2022-01-04', '2022-01-05', '2022-01-06', '2022-01-07'])
        return pd.DataFrame(dict(open=10., high=10., low=10., close=10., preclose=10.,
                                 volume=1_000_000, tradestatus=1), index=dates)

    @patch.object(bt, 'events', return_value=[])
    def test_next_day_and_roundtrip_cash(self, _):
        raw = self.bars()
        target = pd.Series([0, 1, 0, 0, 0], index=raw.index)
        curve, trades, _, _ = bt.simulate(raw, target, 'test', slippage=0)
        self.assertEqual(list(trades.side), ['BUY', 'SELL'])
        self.assertEqual(trades.date.iloc[0], raw.index[2])
        self.assertEqual(trades.date.iloc[1], raw.index[3])
        self.assertEqual(trades.shares.iloc[0] % 100, 0)
        self.assertAlmostEqual(curve.equity.iloc[-1], bt.INITIAL - trades.fee.sum())

    @patch.object(bt, 'events', return_value=[])
    def test_limit_and_suspension_delay(self, _):
        raw = self.bars()
        raw.loc[raw.index[1], ['open', 'high', 'low', 'close']] = 11.
        raw.loc[raw.index[2], 'tradestatus'] = 0
        target = pd.Series(1, index=raw.index)
        _, trades, blocked, _ = bt.simulate(raw, target, 'test', slippage=0)
        self.assertEqual(len(blocked), 2)
        self.assertEqual(trades.date.iloc[0], raw.index[3])

    @patch.object(bt, 'events', return_value=[])
    def test_lower_limit_blocks_sale(self, _):
        raw = self.bars()
        raw.loc[raw.index[2], ['open', 'high', 'low', 'close']] = 9.
        target = pd.Series([1, 0, 0, 0, 0], index=raw.index)
        _, trades, blocked, _ = bt.simulate(raw, target, 'test', slippage=0)
        self.assertEqual(blocked.side.iloc[0], 'SELL')
        self.assertEqual(trades.date.iloc[-1], raw.index[3])

    def test_dividend_receivable_and_payment(self):
        raw = self.bars()
        raw.loc[raw.index[2]:, ['open', 'high', 'low', 'close', 'preclose']] = 9.9
        action = dict(record=raw.index[1], ex=raw.index[2], pay=raw.index[3], listed=raw.index[2],
                      cash=.1, bonus=0, entitled=0)
        with patch.object(bt, 'events', return_value=[action]):
            curve, trades, _, actions = bt.simulate(raw, pd.Series(1, index=raw.index), 'test', slippage=0)
        qty = trades.shares.iloc[0]
        self.assertAlmostEqual(actions.net_dividend.iloc[0], qty * .1 * .8)
        self.assertAlmostEqual(curve.equity.iloc[1] - curve.equity.iloc[0], -qty * .1 * .2)
        self.assertAlmostEqual(curve.equity.iloc[2], curve.equity.iloc[1])
        self.assertAlmostEqual(curve.cash.iloc[2] - curve.cash.iloc[1], qty * .1 * .8)

    def test_share_bonus_unavailable_until_listing(self):
        raw = self.bars()
        raw.loc[raw.index[2]:, ['open', 'high', 'low', 'close', 'preclose']] = 5.
        action = dict(record=raw.index[1], ex=raw.index[2], pay=raw.index[2], listed=raw.index[3],
                      cash=0, bonus=1, entitled=0)
        target = pd.Series([1, 0, 0, 0, 0], index=raw.index)
        with patch.object(bt, 'events', return_value=[action]):
            curve, trades, _, _ = bt.simulate(raw, target, 'test', slippage=0)
        self.assertEqual(list(trades.side), ['BUY', 'SELL', 'SELL'])
        self.assertEqual(trades.shares.iloc[1], trades.shares.iloc[0])
        self.assertEqual(trades.shares.iloc[2], trades.shares.iloc[0])
        self.assertAlmostEqual(curve.equity.iloc[-1], bt.INITIAL - trades.fee.sum())


if __name__ == '__main__':
    unittest.main()
