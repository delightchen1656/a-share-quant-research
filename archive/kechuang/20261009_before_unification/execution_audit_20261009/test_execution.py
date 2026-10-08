from pathlib import Path
import importlib.util,ast,unittest,json
HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('reference_tests',HERE.parent/'dynamic_500k_execution_20261008/test_execution.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.HERE=HERE
class TestFixed(module.TestExecution):
    def setUp(self):
        super().setUp()
        self.ns['COST_SCENARIOS']={'neutral':.004};self.ns['COST_SCENARIO']='neutral'
    def place(self,events=None):
        def order(s,t):
            for status,qty,price in events or []:self.event(status,qty,price)
            return '1'
        self.ns['order_target']=order
        return self.ns['_safe_place']('688001.SH',200,'BUY',.7,50250)
    def test_transport_exception(self):
        def fail(s,t):raise RuntimeError('network')
        self.ns['order_target']=fail
        self.ns['_safe_place']('x',200,'BUY',.7,50250)
        self.assertTrue(self.g.session_blocked)
    def test_model_and_feature_parity(self):
        old=ast.parse((HERE.parent/'supermind_baseline_3_1_high_attack_adaptive_expiry_daily.py').read_text(encoding='utf-8-sig'))
        new=ast.parse((HERE/'supermind_3_1_fixed_500k_execution_v1.py').read_text(encoding='utf-8'))
        for name in ['_last_features','_batch_probabilities','_load_model','_load_stop_model','_live_trade_state']:
            a=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==name)
            b=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==name)
            self.assertEqual(ast.dump(a),ast.dump(b))
    def test_expensive_stock_skipped(self):self.assertEqual(self.ns['_buy_size'](500000,300,500000),(0,0.))
    def test_insufficient_cash_minimum(self):self.assertEqual(self.ns['_buy_size'](500000,15,1650),(0,0.))
    def test_sizing_cash_reserve(self):
        q,r=self.ns['_buy_size'](500000,100,20100)
        self.assertGreaterEqual(q,200);self.assertLessEqual(r,20100);self.assertLessEqual(q*100,50000)
    def test_entry_date_recorded(self):
        self.place([('FILLED',200,100)])
        self.assertEqual(self.g.entry_dates['688001.SH'],self.now.date())
    def test_exit_priority_source(self):
        text=(HERE/'supermind_3_1_fixed_500k_execution_v1.py').read_text(encoding='utf-8')
        self.assertIn('_submit(symbol, 0, "STOP")\n            continue',text)
        self.assertIn('_submit(symbol, target, "TPHALF")\n                continue',text)
        self.assertIn('if symbol not in g.order_locks:\n            # Match',text)
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TestFixed))
    (HERE/'verification.json').write_text(json.dumps({'tests':result.testsRun,'passed':result.wasSuccessful(),'platform_tested':False},indent=2),encoding='utf-8')
    raise SystemExit(not result.wasSuccessful())
