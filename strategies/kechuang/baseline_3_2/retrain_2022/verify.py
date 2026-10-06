"""Chronology, portable prediction and inherited execution regression checks."""
import ast
import unittest
import numpy as np
import pandas as pd
import pipeline as p
import test_revision

class ExportRuntimeTests(test_revision.RevisionTests):
    def setUp(self):
        super().setUp()
        tree=ast.parse(p.PLATFORM.read_text(encoding='utf-8'))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))],type_ignores=[]),'<new-platform>','exec'),self.ns)

class ChronologyTests(unittest.TestCase):
    def test_labels_and_fit_manifest(self):
        report=p.json.loads((p.OUT/'model_selection_2023.json').read_text(encoding='utf-8'))
        self.assertEqual(len(report),6)
        for r in report:self.assertLessEqual(r['train_max_label_end'],'2022-12-31')
        for cutoff in ['2022-12-31','2023-12-31','2024-12-31',p.END]:
            records=p.json.loads((p.HERE/'snapshots'/cutoff/'manifest.json').read_text())
            for row in records.values():self.assertLessEqual(row['max_date'],cutoff)

    def test_future_prefix_invariance(self):
        frame=pd.read_parquet(p.HERE/'snapshots/2023-12-31/qfq/688001.SH.parquet')
        prefix=frame[frame.date<='2022-12-31'].copy()
        a=p.feature._one(prefix,20,.30)
        changed=frame.copy();mask=changed.date>'2022-12-31'
        for col in ['open','high','low','close','volume','amount','turn']:changed.loc[mask,col]*=17
        b=p.feature._one(changed,20,.30).iloc[:len(prefix)]
        np.testing.assert_allclose(a[p.F],b[p.F],equal_nan=True)
        # Latest qfq scale can depend on later corporate actions. Ratio-only
        # price features must remain invariant under uniform historical scaling.
        scaled=prefix.copy()
        for col in ['open','high','low','close']:scaled[col]*=3.7
        np.testing.assert_allclose(a[p.F],p.feature._one(scaled,20,.30)[p.F],rtol=1e-7,atol=1e-8,equal_nan=True)

    def test_freeze_and_source(self):
        lock=p.json.loads((p.OUT/'frozen.json').read_text(encoding='utf-8'))
        protocol=p.json.loads((p.HERE/'protocol.json').read_text(encoding='utf-8'))
        self.assertEqual(p.sha(p.PLATFORM),lock['platform_sha256'])
        self.assertEqual(p.sha(p.HERE/'event_model.joblib'),lock['event_model_sha256'])
        self.assertEqual(p.sha(p.HERE/'stop_model.joblib'),lock['stop_model_sha256'])
        self.assertEqual(p.sha(p.SOURCE),protocol['source_sha256'])
        self.assertEqual(p.sha(p.BASE/'start_date_study.py'),protocol['local_replay_sha256'])
        self.assertTrue(lock['never_refit_on_validation'])

    def test_portable_export(self):
        result=p.json.loads((p.OUT/'export_validation.json').read_text())
        self.assertLess(max(result['maximum_probability_errors']),1e-10)
        self.assertEqual(result['rows'],5000)

    def test_all_fills(self):
        for stage in ['2020_2022_fit','2024_confirmation','2025_2026_test']:
            folder=p.OUT/stage
            c=pd.read_parquet(folder/'daily_equity.parquet')
            t=pd.read_parquet(folder/'trades.parquet')
            self.assertGreater(c.equity.min(),0);self.assertGreaterEqual(c.cash.min(),-.01)
            self.assertEqual(p.json.loads((folder/'unresolved_actions.json').read_text()),[])
            self.assertTrue(t.qty.between(1,50000).all())
            self.assertTrue(t.loc[t.side.eq('BUY'),'qty'].ge(200).all())
            for _,g in t.groupby(['date','symbol']):
                self.assertFalse(g.side.eq('BUY').any() and g.side.ne('BUY').any())
            for symbol,g in t.groupby('symbol'):
                raw=pd.read_parquet(p.DATA/'raw'/(symbol+'.parquet')).set_index('date')
                for date,h in g.groupby('date'):
                    self.assertLessEqual(h.qty.sum(),int(raw.loc[date,'volume']*.25))
                    self.assertEqual(str(raw.loc[date,'tradestatus']),'1')

if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(ExportRuntimeTests),unittest.defaultTestLoader.loadTestsFromTestCase(ChronologyTests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    p.save(p.OUT/'verification.json',{'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()})
    raise SystemExit(0 if result.wasSuccessful() else 1)
