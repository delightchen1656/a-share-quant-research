import unittest
import pandas as pd
from round10_cluster_rotation import rank,CONFIGS

class RotationTests(unittest.TestCase):
    def test_interleaving_and_input_order_invariance(self):
        rows=[dict(symbol='%d_%02d'%(g,i),execute_date=pd.Timestamp('2020-01-02'),cluster8=g,mom=g/10,near_high=g/10,ret20=g/100,vol60=.01+i/1000,distribution_proxy=i/100,long_risk=i/10,downside=.01,float_cap_proxy_group=1) for g in range(4) for i in range(25)]
        f=pd.DataFrame(rows);cfg=dict(family='8_strong',size='all',buffer=12)
        a=rank(f,cfg);b=rank(f.sample(frac=1,random_state=1),cfg)
        self.assertEqual(a.symbol.tolist(),b.symbol.tolist())
        self.assertEqual(a.symbol.str[0].value_counts().to_dict(),{'3':4,'2':4,'1':4})
        f.loc[0,'execute_date']=pd.Timestamp('2020-01-03')
        with self.assertRaises(AssertionError):rank(f,cfg)
    def test_finite_predefined_search(self):
        self.assertEqual(len(CONFIGS),48)
        self.assertTrue(all(c['affordable'] and c['exposure']==.85 for c in CONFIGS))

if __name__=='__main__':unittest.main()
