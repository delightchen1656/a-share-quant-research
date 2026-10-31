import unittest,json,tempfile,copy,hashlib,sys
from pathlib import Path
import numpy as np
import pandas as pd
import app
from direction_service import DirectionService,DirectionError,score_mask
from direction_features import features,enrich
from replay_engine import ReplayService

class DirectionChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store=app.Store();cls.payload=cls.store.direction_signals()
    def test_standard_preserved_and_direction2_is_subset(self):
        rows=self.payload['signals'];selected=[r for r in rows if r['direction2']]
        self.assertEqual(len(rows),1440);self.assertGreater(len(selected),19)
        self.assertEqual(sum(r['date']<='2024-12-31' for r in selected),19)
        self.assertTrue(all(r['is_leader'] for r in selected))
        self.assertEqual(self.payload['directions']['historical_mismatch'],0)
    def test_future_extremes_do_not_determine_direction2(self):
        rows=copy.deepcopy(self.store.signals()['signals'])
        for r in rows:r.update(peak_return60=-999.,max_drop60=999.,peak_complete60=False)
        selected,_=DirectionService().annotate(self.store,rows)
        self.assertEqual(set(selected),{r['id'] for r in self.payload['signals'] if r['direction2']})
    def test_signal_transform_cannot_read_future(self):
        dates=pd.bdate_range('2020-01-01',periods=240)
        q=pd.DataFrame(dict(open=100.,high=102.,low=98.,close=101.),index=dates)
        r=q.copy();r['volume']=1000.;r['amount']=10000.;r['preclose']=100.
        a=enrich(pd.DataFrame([features(q,r,150)]))
        q.iloc[151:]=999.;r.loc[r.index[151]:,['volume','amount','open','close']]=888.
        b=enrich(pd.DataFrame([features(q,r,150)]));pd.testing.assert_frame_equal(a,b)
    def test_empty_full_pool_is_not_silently_replaced_by_best_effort(self):
        self.assertFalse(score_mask({},pd.DataFrame(index=range(5)),dict(abstain=True)).any())
    def test_bad_manifest_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'MANIFEST.json').write_text('{}',encoding='utf-8')
            pointer=root/'CURRENT.json';pointer.write_text(json.dumps(dict(path=d,manifest_sha256='bad')),encoding='utf-8')
            with self.assertRaises(DirectionError):DirectionService(pointer).package()
    def test_replay_uses_only_selected_direction_and_ignores_old_tags(self):
        with tempfile.TemporaryDirectory() as d:
            service=ReplayService(d)
            one=service.candidates(self.store,dict(scope='all',direction='1'))
            two=service.candidates(self.store,dict(scope='all',direction='2'))
            self.assertTrue(set(r['id'] for r in two['rows']).issubset(set(r['id'] for r in one['rows'])))
            old=service.candidates(self.store,dict(scope='all',direction='1',tag='exclude',gap='down'))
            self.assertEqual(old['rows'],one['rows'])
            self.assertTrue(all(r['direction']=='2' for r in two['rows']))
    def test_old_tag_controls_removed_sorting_retained(self):
        web=Path(app.HERE)/'web';main=(web/'index.html').read_text(encoding='utf-8');sim=(web/'replay.html').read_text(encoding='utf-8')
        for old in ['id="gap-filter"','id="quality-filter"','保留标签','排除标签']:self.assertNotIn(old,main)
        self.assertIn('id="direction-select"',main)
        for text in ['原K线','方向1.1 标准箱体','方向1.2 5%触及筛选']:self.assertIn(text,main)
        self.assertIn('id="time-sort"',main);self.assertIn('id="outcome-sort"',main)
        self.assertIn('id="direction"',sim);self.assertNotIn('id="tag"',sim);self.assertNotIn('id="gap"',sim)

if __name__=='__main__':unittest.main()
