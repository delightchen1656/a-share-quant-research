import ast
import unittest
import search as s
import test_revision
p=s.p
pd=s.pd
np=s.np

class RuntimeTests(test_revision.RevisionTests):
    def setUp(self):
        super().setUp()
        tree=ast.parse((s.HERE/'supermind_baseline_3_2_search1000_daily.py').read_text(encoding='utf-8'))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))],type_ignores=[]),'<1000-winner>','exec'),self.ns)

class SearchTests(unittest.TestCase):
    def test_exact_grid_and_ranking(self):
        configurations=p.json.loads((s.HERE/'candidates.json').read_text())
        r=pd.read_csv(s.OUT/'all_1000_results.csv')
        self.assertEqual(len(configurations),1000);self.assertEqual(len(r),1000);self.assertEqual(r.id.nunique(),1000)
        for c in configurations:
            row=r.loc[r.id.eq(c['id'])].iloc[0]
            for key,value in c.items():self.assertEqual(row[key],value)
        self.assertTrue(r.start.eq('2023-01-03').all());self.assertTrue(r.end.eq('2023-12-31').all())
        eligible=r[(r.fills>=40)&(r.avg_exposure>=.15)].sort_values(['objective','sharpe_rf0','cagr','id'],ascending=[False,False,False,True])
        lock=p.json.loads((s.OUT/'frozen.json').read_text())
        self.assertEqual(int(eligible.iloc[0].id),int(lock['best']['id']))

    def test_fit_cutoff_and_old_sources(self):
        records=p.json.loads((s.OUT/'training_boundaries.json').read_text())
        self.assertEqual(len(records),15)
        for r in records:self.assertLessEqual(r['max_label_end'],'2022-12-31')
        pr=p.json.loads((s.HERE/'protocol.json').read_text())
        for file,digest in pr['source_hashes'].items():self.assertEqual(p.sha(s.Path(file)),digest)
        for date,digest in pr['snapshots'].items():self.assertEqual(p.sha(s.PARENT/'snapshots'/date/'manifest.json'),digest)

    def test_frozen_export(self):
        lock=p.json.loads((s.OUT/'frozen.json').read_text())
        for file,key in [('supermind_baseline_3_2_search1000_daily.py','platform_sha256'),('event_model.joblib','event_sha256'),('stop_model.joblib','stop_sha256')]:
            self.assertEqual(p.sha(s.HERE/file),lock[key])
        report=p.json.loads((s.OUT/'export_validation.json').read_text())
        self.assertEqual(report['rows'],5000);self.assertLess(max(report['maximum_probability_errors']),1e-10)

    def test_cached_engine_parity(self):
        r=pd.read_csv(s.OUT/'all_1000_results.csv')
        for ident in [1,114,1000]:
            slow=pd.read_csv(s.OUT/('parity_'+str(ident))/'start_date_results.csv').iloc[0]
            fast=r.loc[r.id.eq(ident)].iloc[0]
            for col in ['final_asset','cagr','max_drawdown','sharpe_rf0','avg_exposure','fills']:
                self.assertTrue(np.isclose(slow[col],fast[col],rtol=1e-10,atol=1e-8,equal_nan=True))

    def test_fills(self):
        for stage in ['2020_2022','2023','2024','2025_2026']:
            for kind in ['v2','winner']:
                folder=s.OUT/(stage+'_'+kind)
                c=pd.read_parquet(folder/'daily_equity.parquet');f=pd.read_parquet(folder/'trades.parquet')
                self.assertGreater(c.equity.min(),0);self.assertGreaterEqual(c.cash.min(),-.01)
                self.assertTrue(f.qty.between(1,50000).all());self.assertTrue(f.loc[f.side.eq('BUY'),'qty'].ge(200).all())
                self.assertEqual(p.json.loads((folder/'unresolved_actions.json').read_text()),[])
                for _,g in f.groupby(['date','symbol']):self.assertFalse(g.side.eq('BUY').any() and g.side.ne('BUY').any())
                for symbol,g in f.groupby('symbol'):
                    raw=pd.read_parquet(p.DATA/'raw'/(symbol+'.parquet')).set_index('date')
                    for date,h in g.groupby('date'):
                        self.assertEqual(str(raw.loc[date,'tradestatus']),'1');self.assertLessEqual(h.qty.sum(),int(raw.loc[date,'volume']*.25))

if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests),unittest.defaultTestLoader.loadTestsFromTestCase(SearchTests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    p.save(s.OUT/'verification.json',{'tests':result.testsRun,'passed':result.wasSuccessful(),'errors':len(result.errors),'failures':len(result.failures)})
    raise SystemExit(0 if result.wasSuccessful() else 1)
