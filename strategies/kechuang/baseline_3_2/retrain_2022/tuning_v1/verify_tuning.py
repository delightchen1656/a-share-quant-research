import ast
import unittest
import tune as t
import pandas as pd
import test_revision

p=t.p
class RuntimeTests(test_revision.RevisionTests):
    def setUp(self):
        super().setUp()
        tree=ast.parse((t.HERE/'supermind_baseline_3_2_tuned_daily.py').read_text(encoding='utf-8'))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))],type_ignores=[]),'<tuned>','exec'),self.ns)

class TuningTests(unittest.TestCase):
    def test_bounded_search_and_freeze(self):
        r=pd.read_csv(t.OUT/'selection_2023.csv')
        self.assertEqual(len(r),19)
        self.assertTrue(r.start.eq('2023-01-03').all())
        lock=p.json.loads((t.OUT/'frozen.json').read_text(encoding='utf-8'))
        self.assertEqual(p.sha(t.HERE/'supermind_baseline_3_2_tuned_daily.py'),lock['platform_sha256'])
        self.assertEqual(p.sha(t.HERE/'event_model.joblib'),lock['event_sha256'])
        self.assertEqual(p.sha(t.HERE/'stop_model.joblib'),lock['stop_sha256'])
        eligible=r[(r.fills>=40)&(r.avg_exposure>=.15)]
        self.assertAlmostEqual(eligible.objective.max(),lock['best']['objective'])
        self.assertFalse(lock['future_used_for_selection'])

    def test_original_and_export(self):
        proto=p.json.loads((t.HERE/'protocol.json').read_text(encoding='utf-8'))
        self.assertEqual(p.sha(t.OLD/'supermind_baseline_3_2_retrained_daily.py'),proto['old_platform_sha256'])
        report=p.json.loads((t.OUT/'export_validation.json').read_text())
        self.assertLess(max(report['maximum_probability_errors']),1e-10)
        for name in ['event_model.joblib','stop_model.joblib']:
            model=p.joblib.load(t.HERE/name)
            self.assertEqual(model['training_end'],'2022-12-31')

    def test_replay_constraints(self):
        for stage in ['2020_2022','2024','2025_2026']:
            for kind in ['control','candidate']:
                folder=t.OUT/(stage+'_'+kind)
                c=pd.read_parquet(folder/'daily_equity.parquet')
                f=pd.read_parquet(folder/'trades.parquet')
                self.assertGreater(c.equity.min(),0);self.assertGreaterEqual(c.cash.min(),-.01)
                self.assertTrue(f.qty.between(1,50000).all())
                self.assertTrue(f.loc[f.side.eq('BUY'),'qty'].ge(200).all())
                self.assertEqual(p.json.loads((folder/'unresolved_actions.json').read_text()),[])
                for _,g in f.groupby(['date','symbol']):
                    self.assertFalse(g.side.eq('BUY').any() and g.side.ne('BUY').any())

if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests),unittest.defaultTestLoader.loadTestsFromTestCase(TuningTests)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    p.save(t.OUT/'verification.json',{'tests':r.testsRun,'passed':r.wasSuccessful(),'errors':len(r.errors),'failures':len(r.failures)})
    raise SystemExit(0 if r.wasSuccessful() else 1)
