"""Offline schedule tests; no platform imports, orders, or market-data requests."""
import ast
import calendar
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import unittest

SOURCE = Path(__file__).with_name('supermind_mainboard_baseline_2_start_anchored.py')
TREE = ast.parse(SOURCE.read_text(encoding='utf-8-sig'))
FUNCTIONS = {n.name: n for n in TREE.body if isinstance(n, ast.FunctionDef)}


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 9, 24)
        self.calls = []
        self.answer = {'600000.SH': 0.1}
        self.state = NS(schedule_anchor=None, schedule_quarter=0,
                        next_rebalance_date=None, submitted_date=None,
                        targets=None, rebalance_pending=False)
        self.scope = dict(calendar=calendar, g=self.state,
                          get_datetime=lambda: datetime.combine(self.today, datetime.min.time()),
                          log=NS(info=lambda _: None, warn=lambda _: None),
                          _build_targets=self.build)
        selected = [FUNCTIONS[n] for n in ('_quarter_date', 'before_trading')]
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), 'exec'), self.scope)

    def build(self, context):
        self.calls.append(self.today)
        return self.answer

    def run_day(self, value):
        self.today = date.fromisoformat(value)
        self.scope['before_trading'](None)

    def test_first_session_and_no_duplicate(self):
        self.run_day('2026-09-24')
        self.assertEqual(self.state.schedule_anchor, self.today)
        self.assertEqual(self.state.next_rebalance_date, date(2026, 12, 24))
        self.assertTrue(self.state.rebalance_pending)
        self.assertEqual(self.state.targets, self.answer)
        self.run_day('2026-09-24')
        self.run_day('2026-10-01')
        self.run_day('2026-12-23')
        self.assertEqual(len(self.calls), 1)
        self.run_day('2026-12-24')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.state.next_rebalance_date, date(2027, 3, 24))

    def test_closed_sessions_do_not_shift_anchor(self):
        self.run_day('2026-09-25')
        # Simulate no callback on the due date; next available session is later.
        self.run_day('2026-12-28')
        self.assertEqual(self.state.next_rebalance_date, date(2027, 3, 25))

    def test_month_end_and_leap_year(self):
        q = self.scope['_quarter_date']
        self.assertEqual(q(date(2026, 8, 31), 1), date(2026, 11, 30))
        self.assertEqual(q(date(2026, 8, 31), 2), date(2027, 2, 28))
        self.assertEqual(q(date(2026, 8, 31), 3), date(2027, 5, 31))
        self.assertEqual(q(date(2023, 11, 30), 1), date(2024, 2, 29))

    def test_missing_signal_retries_without_moving_anchor(self):
        self.answer = None
        self.run_day('2026-09-24')
        self.assertFalse(self.state.rebalance_pending)
        self.assertEqual(self.state.next_rebalance_date, self.today)
        self.answer = {'600000.SH': 0.1}
        self.run_day('2026-09-25')
        self.assertTrue(self.state.rebalance_pending)
        self.assertEqual(self.state.next_rebalance_date, date(2026, 12, 24))

    def test_long_gap_only_one_current_signal(self):
        self.run_day('2026-09-24')
        self.run_day('2027-07-01')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.state.next_rebalance_date, date(2027, 9, 24))


def verify_unchanged_rules(original_path):
    original = ast.parse(Path(original_path).read_text(encoding='utf-8-sig'))
    old = {n.name: n for n in original.body if isinstance(n, ast.FunctionDef)}
    unchanged = set(old) - {'init', 'before_trading', '_is_first_session_of_month'}
    for name in unchanged:
        assert ast.dump(old[name]) == ast.dump(FUNCTIONS[name]), name
    def constants(tree):
        return {n.targets[0].id: ast.dump(n.value) for n in tree.body
                if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert constants(original) == constants(TREE), 'strategy constants changed'
    print('Original selection/execution/valuation functions and constants unchanged:', len(unchanged))


if __name__ == '__main__':
    if len(sys.argv) > 1:
        verify_unchanged_rules(sys.argv.pop(1))
    unittest.main()
