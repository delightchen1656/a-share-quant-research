import ast
import calendar
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

HERE = Path(__file__).resolve().parent
TREE = ast.parse((HERE/'supermind_mainboard_baseline_2_monthly_next_session.py').read_text(encoding='utf-8'))
FUN = {n.name:n for n in TREE.body if isinstance(n,ast.FunctionDef)}


class Tests(unittest.TestCase):
    def setUp(self):
        self.today=date(2026,9,24)
        self.calls=[]
        self.answer={'600000.SH':.1}
        self.g=NS(strategy_start_date=self.today,schedule_anchor=None,schedule_month=0,
                  next_rebalance_date=None,submitted_date=None,targets=None,rebalance_pending=False)
        self.scope=dict(calendar=calendar,g=self.g,
            get_datetime=lambda:datetime.combine(self.today,datetime.min.time()),
            _build_targets=self.build, log=NS(info=lambda _:None,warn=lambda _:None))
        exec(compile(ast.Module(body=[FUN[n] for n in ('_month_date','before_trading')],type_ignores=[]),'monthly','exec'),self.scope)

    def build(self,ctx):
        self.calls.append(self.today)
        return self.answer

    def day(self,s):
        self.today=date.fromisoformat(s)
        self.scope['before_trading'](None)

    def test_skip_start_and_entry_next_session(self):
        self.day('2026-09-24')
        self.assertEqual(self.calls,[])
        self.day('2026-09-25')
        self.assertEqual(self.g.schedule_anchor,self.today)
        self.assertEqual(self.g.next_rebalance_date,date(2026,10,25))
        self.day('2026-09-25')
        self.day('2026-10-23')
        self.assertEqual(len(self.calls),1)
        self.day('2026-10-26')
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.g.next_rebalance_date,date(2026,11,25))

    def test_no_weekend_calendar_assumption(self):
        self.g.strategy_start_date=date(2026,9,25)
        self.day('2026-09-28')
        self.assertEqual(self.g.schedule_anchor,self.today)

    def test_month_end_leap_and_year(self):
        fn=self.scope['_month_date']
        self.assertEqual(fn(date(2026,1,31),1),date(2026,2,28))
        self.assertEqual(fn(date(2026,1,31),2),date(2026,3,31))
        self.assertEqual(fn(date(2023,12,31),2),date(2024,2,29))

    def test_failed_signal_retries_and_keeps_anchor(self):
        self.answer=None
        self.day('2026-09-25')
        self.assertFalse(self.g.rebalance_pending)
        self.answer={'600000.SH':.1}
        self.day('2026-09-28')
        self.assertTrue(self.g.rebalance_pending)
        self.assertEqual(self.g.next_rebalance_date,date(2026,10,25))

    def test_only_schedule_functions_changed(self):
        old=ast.parse((HERE/'supermind_mainboard_baseline_2_start_anchored.py').read_text(encoding='utf-8'))
        for n in old.body:
            if isinstance(n,ast.FunctionDef) and n.name not in ('init','before_trading','_quarter_date'):
                self.assertEqual(ast.dump(n),ast.dump(FUN[n.name]),n.name)
        constants=lambda t:{n.targets[0].id:ast.dump(n.value) for n in t.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name)}
        self.assertEqual(constants(old),constants(TREE))
        self.assertIn('strategy_start_date',ast.unparse(FUN['init']))


if __name__=='__main__':unittest.main()
