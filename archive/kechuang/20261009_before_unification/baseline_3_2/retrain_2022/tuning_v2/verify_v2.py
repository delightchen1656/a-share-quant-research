import ast
import unittest
import tune_stop as t
import test_revision
p=t.p
pd=t.pd

class RuntimeTests(test_revision.RevisionTests):
    def setUp(self):
        super().setUp()
        tree=ast.parse((t.HERE/'supermind_baseline_3_2_tuning_v2_daily.py').read_text(encoding='utf-8'))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))],type_ignores=[]),'<v2>','exec'),self.ns)

class RoundTests(unittest.TestCase):
    def test_selection_boundary(self):
        b=p.json.loads((t.OUT/'training_boundary.json').read_text())
        self.assertLessEqual(b['max_label_end'],'2022-12-31')
        rows=pd.read_csv(t.OUT/'selection_2023.csv')
        self.assertEqual(len(rows),19)
        self.assertTrue(rows.start.eq('2023-01-03').all())
        lock=p.json.loads((t.OUT/'frozen.json').read_text())
        eligible=rows[(rows.fills>=40)&(rows.avg_exposure>=.15)]
        self.assertAlmostEqual(eligible.objective.max(),lock['best']['objective'])
        self.assertFalse(lock['future_used_for_selection'])

    def test_preservation_and_export(self):
        proto=p.json.loads((t.HERE/'protocol.json').read_text())
        for file,digest in proto['preserved'].items():self.assertEqual(p.sha(t.Path(file)),digest)
        lock=p.json.loads((t.OUT/'frozen.json').read_text())
        for file,key in [('event_model.joblib','event_sha256'),('stop_model.joblib','stop_sha256'),('supermind_baseline_3_2_tuning_v2_daily.py','platform_sha256')]:
            self.assertEqual(p.sha(t.HERE/file),lock[key])
        parity=p.json.loads((t.OUT/'export_validation.json').read_text())
        self.assertLess(max(parity['maximum_probability_errors']),1e-10)

    def test_cash_and_fills(self):
        for stage in ['2020_2022','2024','2025_2026']:
            for version in ['v1','v2']:
                folder=t.OUT/(stage+'_'+version)
                c=pd.read_parquet(folder/'daily_equity.parquet');f=pd.read_parquet(folder/'trades.parquet')
                self.assertGreater(c.equity.min(),0);self.assertGreaterEqual(c.cash.min(),-.01)
                self.assertEqual(p.json.loads((folder/'unresolved_actions.json').read_text()),[])
                self.assertTrue(f.qty.between(1,50000).all());self.assertTrue(f.loc[f.side.eq('BUY'),'qty'].ge(200).all())
                for _,g in f.groupby(['date','symbol']):self.assertFalse(g.side.eq('BUY').any() and g.side.ne('BUY').any())
                for symbol,g in f.groupby('symbol'):
                    raw=pd.read_parquet(p.DATA/'raw'/(symbol+'.parquet')).set_index('date')
                    for date,h in g.groupby('date'):
                        self.assertEqual(str(raw.loc[date,'tradestatus']),'1')
                        self.assertLessEqual(h.qty.sum(),int(raw.loc[date,'volume']*.25))

if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests),unittest.defaultTestLoader.loadTestsFromTestCase(RoundTests)])
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    p.save(t.OUT/'verification.json',{'tests':r.testsRun,'passed':r.wasSuccessful(),'errors':len(r.errors),'failures':len(r.failures)})
    raise SystemExit(0 if r.wasSuccessful() else 1)
