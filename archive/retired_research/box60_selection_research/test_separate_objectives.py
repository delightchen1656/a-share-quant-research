import unittest
import numpy as np
import pandas as pd
from study_separate_risk30_precision90 import choose_independent

class IndependentObjectiveChecks(unittest.TestCase):
    def rows(self):
        y=np.array([1]*80+[0]*20);drop=np.zeros(100,int);drop[70:80]=1
        masks={'risk_all':np.ones(100,bool),'risk_low':np.arange(100)<50,
            'hit_qualified':np.arange(100)<40,'hit_tiny':np.arange(100)<3}
        return pd.DataFrame([dict(candidate=key,y=int(a),drop30=int(b),pick=bool(p)) for key,mask in masks.items() for a,b,p in zip(y,drop,mask)])
    def test_risk_objective_ignores_touch5_labels(self):
        d=self.rows();a=choose_independent(d,'risk30');d['y']=1-d.y
        b=choose_independent(d,'risk30');self.assertEqual(a['candidate'],'risk_low');self.assertEqual(a['candidate'],b['candidate'])
    def test_hit90_objective_ignores_risk30_labels(self):
        d=self.rows();a=choose_independent(d,'precision90');d['drop30']=1
        b=choose_independent(d,'precision90');self.assertEqual(a['candidate'],'hit_qualified');self.assertEqual(a['candidate'],b['candidate'])
    def test_no_qualified90_abstains_not_fake_goal(self):
        d=self.rows();d['y']=np.tile([1,1,1,1,0],len(d)//5)
        a=choose_independent(d,'precision90');self.assertEqual(a['candidate'],'abstain');self.assertFalse(a['goal_met'])
    def test_tiny_perfect_subset_not_accepted(self):
        d=self.rows();self.assertNotEqual(choose_independent(d,'precision90')['candidate'],'hit_tiny')

if __name__=='__main__':unittest.main()
