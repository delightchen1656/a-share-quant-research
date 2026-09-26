import ast
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime
import unittest
import numpy as np

HERE=Path(__file__).resolve().parent
SOURCE=(HERE/'supermind_mainboard_baseline_2_monthly_A.py').read_text(encoding='utf-8')
TREE=ast.parse(SOURCE)
FUN={n.name:n for n in TREE.body if isinstance(n,ast.FunctionDef)}

class Tests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,9,24,9,0);self.calls=[];self.orders=[]
        self.g=NS(last_month_key=None,targets=None,rebalance_pending=False,submitted_date=None)
        self.scope=dict(g=self.g,np=np,TARGET_COUNT=6,TARGET_EXPOSURE=.8,MAX_SINGLE_MULTIPLE=1.5,
            RISK_WEIGHT_POWER=.5,MIN_ADJUSTMENT=3000.,get_datetime=lambda:self.now,
            _build_targets=lambda ctx:self.build(),log=NS(info=lambda x:None),
            _trade_state=lambda s,b:(True,False,False),order_target_percent=lambda s,w:self.orders.append((s,w)))
        names=('_is_first_session_of_month','before_trading','_risk_weights','handle_bar')
        exec(compile(ast.Module(body=[FUN[n] for n in names],type_ignores=[]),'strategy-test','exec'),self.scope)

    def build(self):
        self.calls.append(self.now.date());return {'600000.SH':.1}

    def day(self,s):
        self.now=datetime.fromisoformat(s+'T09:00:00');self.scope['before_trading'](None)

    def test_immediate_midmonth_entry(self):
        self.day('2026-09-24');self.assertTrue(self.g.rebalance_pending);self.assertEqual(len(self.calls),1)
        self.day('2026-09-25');self.assertEqual(len(self.calls),1)

    def test_month_holiday_not_anchor(self):
        self.day('2026-09-24');self.day('2026-10-09');self.day('2026-10-26')
        self.assertEqual(len(self.calls),2)
        self.day('2026-11-02');self.assertEqual(len(self.calls),3)

    def test_year_transition(self):
        self.day('2026-12-31');self.day('2027-01-04');self.assertEqual(len(self.calls),2)

    def test_same_day_dedup(self):
        self.day('2026-09-24');self.day('2026-09-24');self.assertEqual(len(self.calls),1)

    def test_weights_power(self):
        names=list('abcdef');down=dict(zip(names,[.020,.022,.024,.026,.028,.030]))
        actual=self.scope['_risk_weights'](names,down)
        inv=np.array([down[s]**-.5 for s in names]);expected=inv/inv.sum()
        np.testing.assert_allclose(actual,expected)
        self.assertAlmostEqual(sum(actual)*.8,.8)

    def test_weight_cap(self):
        names=list('abcdef');down=dict(zip(names,[.002,.02,.03,.04,.05,.06]))
        weights=self.scope['_risk_weights'](names,down)
        self.assertLessEqual(max(weights),.25+1e-8);self.assertAlmostEqual(sum(weights),1.)

    def test_once_only_submission(self):
        self.day('2026-09-24')
        context=NS(portfolio=NS(positions={},stock_account=NS(total_value=100000)))
        bars={'600000.SH':NS(open=10.)}
        self.scope['handle_bar'](context,bars);self.scope['handle_bar'](context,bars)
        self.assertEqual(self.orders,[('600000.SH',.1)])
        self.assertFalse(self.g.rebalance_pending)

    def test_locked_up_not_bought(self):
        self.day('2026-09-24');self.scope['_trade_state']=lambda s,b:(True,True,False)
        self.scope['handle_bar'](NS(portfolio=NS(positions={},stock_account=NS(total_value=100000))),{'600000.SH':NS(open=10.)})
        self.assertEqual(self.orders,[])

    def test_original_universe_and_factors_unchanged(self):
        tree=ast.parse((HERE/'supermind_mainboard_baseline_2_pending1.py').read_text(encoding='utf-8'))
        funcs={n.name:n for n in tree.body if isinstance(n,ast.FunctionDef)}
        for name in ('_load_universe','_is_ordinary_mainboard_a','_rank01','_dividend_quality','_features','_rank_candidates','_group_features','_trade_state'):
            self.assertEqual(ast.dump(FUN[name]),ast.dump(funcs[name]))
        def universe(t):
            return next(n.value.value for n in t.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='_MAINBOARD_UNIVERSE_B64')
        self.assertEqual(universe(tree),universe(TREE))
        self.assertEqual(next(n.value.value for n in TREE.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='TARGET_COUNT'),6)

if __name__=='__main__':unittest.main()
