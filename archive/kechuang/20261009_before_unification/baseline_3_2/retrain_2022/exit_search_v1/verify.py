import ast,datetime,unittest
import run as r
import test_revision
p=r.p;pd=r.pd;np=r.np

class RuntimeTests(test_revision.RevisionTests):
    def setUp(self):
        super().setUp()
        tree=ast.parse((r.HERE/'supermind_baseline_3_2_exit_optimized_daily.py').read_text(encoding='utf-8'))
        exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n,(ast.Assign,ast.FunctionDef))],type_ignores=[]),'<exit-version>','exec'),self.ns)

    def test_expiry_small_position(self):
        rule=p.json.loads((r.OUT/'frozen.json').read_text())['rule']
        for amount in [200,399,400,1000]:
            state={'entry':10.,'half':False,'entry_date':self.now.date()-datetime.timedelta(days=rule['hard_days'])}
            self.assertEqual(self.ns['_exit_action'](11.5,state,amount,self.now.date(),rule['hard_days']),('TIME60',0))

class StudyTests(unittest.TestCase):
    def test_ranking_and_hashes(self):
        table=pd.read_csv(r.OUT/'all_81_results.csv');self.assertEqual(len(table),81)
        eligible=table[(table.fills>=40)&(table.avg_exposure>=.15)].sort_values(['objective','sharpe_rf0','id'],ascending=[False,False,True])
        lock=p.json.loads((r.OUT/'frozen.json').read_text());self.assertEqual(eligible.iloc[0].id,lock['best']['id'])
        for name,key in [('supermind_baseline_3_2_exit_optimized_daily.py','platform_sha256'),('event_model.joblib','event_sha256'),('stop_model.joblib','stop_sha256')]:self.assertEqual(p.sha(r.HERE/name),lock[key])
        protocol=p.json.loads((r.HERE/'protocol.json').read_text())
        for file,digest in protocol['source_hashes'].items():self.assertEqual(p.sha(r.Path(file)),digest)

    def test_exit_export(self):
        rule=p.json.loads((r.OUT/'frozen.json').read_text())['rule'];local=r.exit_function(rule)
        exported=p.namespace((r.HERE/'supermind_baseline_3_2_exit_optimized_daily.py').read_text(encoding='utf-8'))['_exit_action']
        today=datetime.date(2023,12,1)
        for age in [0,1,19,20,29,30,39,40,59,60,79,80]:
            for gain in [-.11,-.071,-.051,-.049,0,.09,.11,.179,.181,.241,.341,.61]:
                for qty in [199,200,399,400,1000]:
                    for half in [False,True]:
                        state={'entry':10.,'half':half,'entry_date':today-datetime.timedelta(days=age)}
                        self.assertEqual(local(10*(1+gain),state,qty,today,age),exported(10*(1+gain),state,qty,today,age))
        parity=p.json.loads((r.OUT/'export_validation.json').read_text());self.assertLess(max(parity['maximum_probability_errors']),1e-10)

    def test_fixed_model_predictions(self):
        ds,_,_=p.dataset(r.ROOT/'snapshots/2023-12-31','2023-01-01','2023-12-31');x=ds.sample(1000,random_state=42)
        for name in ['event_model.joblib','stop_model.joblib']:
            a=p.joblib.load(r.OLD/name)['model'];b=p.joblib.load(r.HERE/name)['model']
            np.testing.assert_array_equal(a.predict_proba(x[p.F]),b.predict_proba(x[p.F]))

    def test_execution(self):
        for stage in ['2020_2022','2023','2024','2025_2026']:
            folder=r.OUT/(stage+'_exit_v1');curve=pd.read_parquet(folder/'daily_equity.parquet');trades=pd.read_parquet(folder/'trades.parquet')
            self.assertGreaterEqual(curve.cash.min(),-.01);self.assertGreater(curve.equity.min(),0)
            self.assertTrue(trades.qty.between(1,50000).all());self.assertTrue(trades.loc[trades.side.eq('BUY'),'qty'].ge(200).all())
            for _,g in trades.groupby(['date','symbol']):self.assertFalse(g.side.eq('BUY').any() and g.side.ne('BUY').any())
            self.assertEqual(p.json.loads((folder/'unresolved_actions.json').read_text()),[])

if __name__=='__main__':
    suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(RuntimeTests),unittest.defaultTestLoader.loadTestsFromTestCase(StudyTests)])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    p.save(r.OUT/'verification.json',{'tests':result.testsRun,'passed':result.wasSuccessful(),'errors':len(result.errors),'failures':len(result.failures)})
    raise SystemExit(0 if result.wasSuccessful() else 1)
