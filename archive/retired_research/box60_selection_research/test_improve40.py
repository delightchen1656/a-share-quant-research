import unittest
import numpy as np
import pandas as pd
from improve40_v2 import enrich,ALL_FEATURES,rule_catalog,mask_rule,objective,choose,time_slices
from study import NAMES

class ImprovementChecks(unittest.TestCase):
    def test_features_exclude_label_fields_and_handle_zero_division(self):
        d=pd.DataFrame({k:[1.,0.] for k in NAMES});d['y']=[1,0];a=enrich(d)
        d['y']=[0,1];b=enrich(d)
        pd.testing.assert_frame_equal(a[ALL_FEATURES],b[ALL_FEATURES])
        self.assertFalse(set(ALL_FEATURES)&{'y','peak_gain60','entry_open','label_end','is_leader','year','code'})
        self.assertFalse(np.isinf(a[ALL_FEATURES].to_numpy()).any())
    def test_rule_baseline_and_missing_values(self):
        d=pd.DataFrame({'base_up_volume_share':[.60,.59,np.nan]})
        self.assertEqual(mask_rule(d,rule_catalog()['rule_a0.6']).tolist(),[True,False,False])
    def test_temporal_training_is_label_maturity_not_signal_year_only(self):
        d=pd.DataFrame(dict(year=[2022,2022,2023],label_end=['2022-12-30','2023-02-01','2023-07-01']))
        train,test=time_slices(d,2023);self.assertEqual(train.index.tolist(),[0]);self.assertEqual(test.index.tolist(),[2])
    def test_no_tiny_pick_optimism_and_balanced_recall_constraint(self):
        y=np.array([1]*40+[0]*60);tiny=np.zeros(100,bool);tiny[:2]=True
        self.assertIsNone(objective(y,tiny,True))
        focused=np.zeros(100,bool);focused[:10]=True
        self.assertIsNone(objective(y,focused,False));self.assertIsNotNone(objective(y,focused,True))
    def test_inner_selection_prefers_valid_high_precision_without_test_input(self):
        y=np.array([1]*40+[0]*60)
        baseline=np.zeros(100,bool);baseline[:20]=True;baseline[40:60]=True
        balanced=np.zeros(100,bool);balanced[:18]=True;balanced[40:52]=True
        focus=np.zeros(100,bool);focus[:10]=True
        rows=[]
        for name,picks in [('rule_a0.6',baseline),('rule_better',balanced),('model_focused',focus)]:
            rows += [dict(candidate=name,y=int(a),pick=bool(b)) for a,b in zip(y,picks)]
        d=pd.DataFrame(rows)
        self.assertEqual(choose(d)['candidate'],'rule_better')
        self.assertEqual(choose(d,focused=True)['candidate'],'model_focused')
    def test_no_candidate_fallback_is_original_rule(self):
        d=pd.DataFrame(dict(candidate=['model_x']*20,y=[1]+[0]*19,pick=[True]+[False]*19))
        chosen=choose(d);self.assertTrue(chosen['fallback']);self.assertEqual(chosen['candidate'],'rule_a0.6')
        empty=pd.DataFrame(columns=['candidate','fold','event_id','y','pick'])
        self.assertEqual(choose(empty)['candidate'],'rule_a0.6')

if __name__=='__main__':unittest.main()
