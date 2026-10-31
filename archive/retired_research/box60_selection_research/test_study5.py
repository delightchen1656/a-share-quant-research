import unittest
import numpy as np
import pandas as pd
from study5_precision80 import relabel5,choose5,PROFILES

class FivePercentChecks(unittest.TestCase):
    def frames(self):
        dates=pd.bdate_range('2020-01-01',periods=260)
        q=pd.DataFrame(dict(open=100.,high=104.,low=95.,close=100.),index=dates)
        r=q.copy();r['volume']=100.;r['tradestatus']='1'
        return q,r
    def test_inclusive5_and_only_d1_to_d60(self):
        q,r=self.frames();t=150;q.loc[q.index[t],'high']=99999.;q.loc[q.index[t+61],'high']=99999.
        self.assertEqual(relabel5(q,r,t)['y'],0)
        q.loc[q.index[t+60],'high']=105.
        result=relabel5(q,r,t);self.assertEqual(result['y'],1);self.assertEqual(result['first_touch_day'],60)
    def test_buy_day_only_hit_not_sellable(self):
        q,r=self.frames();q.loc[q.index[151],'high']=105.
        result=relabel5(q,r,150);self.assertEqual(result['y'],1);self.assertEqual(result['sellable_y'],0);self.assertTrue(result['d1_only_hit'])
    def test_incomplete_not_false_label(self):
        q,r=self.frames();result=relabel5(q.iloc[:210],r.iloc[:210],150)
        self.assertEqual(result['label_status'],'boundary_purged');self.assertNotIn('y',result)
    def test_target_selection_maximizes_coverage_not_tiny_perfect_pick(self):
        y=np.array([1]*80+[0]*20);rows=[]
        picks={'rule_all':np.ones(100,bool),'rule_tiny':np.arange(100)<3,'rule_narrow':np.arange(100)<40}
        for name,mask in picks.items():rows += [dict(candidate=name,y=int(a),pick=bool(b)) for a,b in zip(y,mask)]
        self.assertEqual(choose5(pd.DataFrame(rows),'precision80')['candidate'],'rule_all')
        self.assertEqual(choose5(pd.DataFrame(rows),'precision85')['candidate'],'rule_narrow')
    def test_no_validation_does_not_claim80(self):
        decision=choose5(pd.DataFrame(columns=['candidate','y','pick']),'precision80')
        self.assertTrue(decision['fallback']);self.assertFalse(decision['inner_target_met'])
    def test_profile_floors_are_not_zero(self):
        self.assertGreaterEqual(PROFILES['precision80']['coverage'],.3)
        self.assertGreaterEqual(PROFILES['precision80']['recall'],.5)

if __name__=='__main__':unittest.main()
