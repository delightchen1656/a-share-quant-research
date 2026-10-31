import unittest
import numpy as np
import pandas as pd
from study import features,label,CORE,NAMES,metrics,fit_rule,apply_rule

class StudyChecks(unittest.TestCase):
    def frames(self):
        dates=pd.bdate_range('2020-01-01',periods=260)
        q=pd.DataFrame(dict(open=100.,close=101.,high=102.,low=99.),index=dates)
        r=q.copy();r['volume']=1000.;r['amount']=100000.;r['preclose']=100.;r['tradestatus']='1'
        return q,r
    def test_features_do_not_change_when_future_price_or_volume_changes(self):
        q,r=self.frames();a=features(q,r,150)
        q.iloc[151:]=99999.;r.loc[r.index[151:],['open','close','high','low','volume','amount']]=88888
        b=features(q,r,150)
        for k in a:self.assertTrue((np.isnan(a[k]) and np.isnan(b[k])) or a[k]==b[k],k)
    def test_label_excludes_d0_d61_and_threshold_is_strict(self):
        q,r=self.frames();t=150;q.loc[q.index[t],'high']=99999.;q.loc[q.index[t+61],'high']=99999.
        q.loc[q.index[t+60],'high']=160.
        self.assertEqual(label(q,r,t)['y'],0)
        q.loc[q.index[t+60],'high']=160.1
        self.assertEqual(label(q,r,t)['y'],1)
        self.assertEqual(label(q,r,t)['label_end'],str(q.index[t+60].date()))
    def test_incomplete_or_suspended_path_is_not_a_negative(self):
        q,r=self.frames();self.assertEqual(label(q.iloc[:210],r.iloc[:210],150)['label_status'],'boundary_purged')
        r.loc[r.index[152],'tradestatus']='0'
        self.assertEqual(label(q,r,150)['label_status'],'missing_or_suspended_path')
    def test_model_features_are_signal_time_only(self):
        self.assertTrue(set(CORE).issubset(NAMES))
        self.assertFalse(set(CORE)&{'entry_open','y','peak_gain60','peak_date','label_end','year','is_leader','code'})
    def test_rule_fit_and_metrics_account_for_misses(self):
        f=pd.DataFrame({k:np.arange(100,dtype=float) for k in NAMES});f['y']=(f.base_return>70).astype(int)
        rule=fit_rule(f);mask=apply_rule(f,rule);m=metrics(f.y,mask)
        self.assertEqual(m['hits']+m['missed'],29);self.assertEqual(m['selected'],m['hits']+m['false_positives'])
        empty=metrics(f.y,np.zeros(100,dtype=bool));self.assertIsNone(empty['precision']);self.assertEqual(empty['recall'],0)

if __name__=='__main__':unittest.main()
