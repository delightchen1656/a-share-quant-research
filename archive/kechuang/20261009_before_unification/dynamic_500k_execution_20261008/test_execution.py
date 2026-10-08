from pathlib import Path
from types import SimpleNamespace as N
from datetime import datetime
import ast,json,unittest
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent

class TestExecution(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,8,9,31);self.calls=[];self.logs=[]
        g=N()
        self.ns={'g':g,'np':np,'pd':pd,'get_datetime':lambda:self.now,'log':N(info=self.logs.append,warn=self.logs.append)}
        exec((HERE/'runtime_patch.py').read_text(encoding='utf-8'),self.ns)
        def init(c):
            g.position_state={};g.order_intent={};g.order_locks={};g.submitted_action={};g.daily_buy_value=0.;g.daily_sell_value=0.
        self.ns['_legacy_init']=init
        self.ns['_legacy_before_trading']=lambda c:self.calls.append('prepare')
        self.ns['_legacy_handle_bar']=lambda c,b:self.calls.append('execute')
        self.context=N(portfolio=N(positions={},stock_account=N(available_cash=500000,total_value=500000)))
        self.ns['init'](self.context);g.cash_budget=500000
        self.g=g
    def place(self,events=None):
        def order(s,t):
            for status,qty,price in events or []:
                self.ns['on_order'](self.context,N(order_id='1',status=status,filled_amount=qty,avg_price=price))
            return '1'
        self.ns['order_target_percent']=order
        return self.ns['_safe_place']('688001.SH',.1,'BUY',.7,50250)
    def event(self,status,qty,price):self.ns['on_order'](self.context,N(order_id='1',status=status,filled_amount=qty,avg_price=price))
    def test_sync_filled(self):
        self.place([('FILLED',200,100)])
        self.assertEqual(self.g.daily_buy_value,20000);self.assertFalse(self.g.order_intent);self.assertFalse(self.g.order_locks)
    def test_notional_difference_duplicate_stale(self):
        self.place();self.event('PARTIALLY_FILLED',100,100);self.event('FILLED',200,110)
        self.event('FILLED',200,110);self.event('PARTIALLY_FILLED',100,100)
        self.assertEqual(self.g.daily_buy_value,22000);self.assertFalse(self.g.session_blocked)
    def test_partial_cancel(self):
        self.place();self.event('PARTIALLY_CANCELLED',100,100)
        self.assertFalse(self.g.order_intent);self.assertEqual(self.g.daily_buy_value,10000)
    def test_duplicate_day(self):
        self.ns['before_trading'](self.context);self.ns['before_trading'](self.context)
        self.ns['handle_bar'](self.context,{});self.ns['handle_bar'](self.context,{})
        self.assertEqual(self.calls,['prepare','execute'])
    def test_next_day_unresolved(self):
        self.place();self.now=datetime(2026,10,9,9)
        self.ns['before_trading'](self.context)
        self.assertTrue(self.g.session_blocked);self.assertTrue(self.g.order_intent)
    def test_unknown_status(self):
        self.place();self.event('987',0,0);self.assertTrue(self.g.session_blocked)
    def test_platform_enum_pending_cancel(self):
        self.place();self.event('ORDER_STATUS.PENDING_NEW',0,0)
        self.event('ORDER_STATUS.PENDING_CANCEL',100,100)
        self.assertTrue(self.g.order_intent);self.assertFalse(self.g.session_blocked)
        self.event('ORDER_STATUS.CANCELLED',100,100)
        self.assertFalse(self.g.order_intent)
    def test_query_recovers_missing_callback(self):
        self.place()
        self.ns['get_order']=lambda oid:N(order_id=oid,status='ORDER_STATUS.FILLED',filled_amount=200,avg_price=100)
        self.ns['_poll_orders'](self.context)
        self.assertEqual(self.g.daily_buy_value,20000);self.assertFalse(self.g.order_intent)
    def test_late_fill(self):
        self.place();self.event('CANCELLED',0,0);self.event('FILLED',200,100)
        self.assertTrue(self.g.session_blocked)
    def test_transport_exception(self):
        def fail(s,t):raise RuntimeError('network')
        self.ns['order_target_percent']=fail
        self.ns['_safe_place']('x',.1,'BUY',.7,50250)
        self.assertTrue(self.g.session_blocked);self.assertIn('x',self.g.order_locks)
    def test_cash(self):
        self.g.cash_budget=100;self.assertIsNone(self.place());self.assertFalse(self.g.order_intent)
    def test_restart_holdings(self):
        self.context.portfolio.positions={'x':N(amount=200)};self.ns['init'](self.context)
        self.assertTrue(self.g.session_blocked)
    def test_model_and_feature_parity(self):
        old=ast.parse((HERE/'uploaded_source.py').read_text(encoding='utf-8-sig'))
        new=ast.parse((HERE/'supermind_3_legacy_dynamic_500k_execution_v1.py').read_text(encoding='utf-8'))
        for name in ['_last_features','_batch_probabilities','_load_model','_load_stop_model','_live_trade_state']:
            a=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(a),ast.dump(b))

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestExecution))
    (HERE/'verification.json').write_text(json.dumps({'tests':result.testsRun,'passed':result.wasSuccessful(),'failures':len(result.failures),'errors':len(result.errors),'platform_tested':False},indent=2),encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
