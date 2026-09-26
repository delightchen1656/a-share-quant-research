import unittest
import numpy as np
import pandas as pd
from prepare_clusters import fit_clusters

class ClusterTests(unittest.TestCase):
    def test_future_returns_do_not_change_past_memberships(self):
        rng=np.random.default_rng(31);idx=pd.bdate_range('2019-01-01',periods=250)
        f=pd.DataFrame(rng.normal(0,.01,(250,40)),index=idx,columns=['S%02d'%i for i in range(40)])
        changed=f.copy();changed.loc[idx[180]:]=rng.normal(5,1,(70,40))
        a,aa=fit_clusters(f,idx[180],list(f),8)
        b,bb=fit_clusters(changed,idx[180],list(f),8)
        pd.testing.assert_series_equal(a,b)
        self.assertLess(pd.Timestamp(aa['max_input_date']),idx[180])
        self.assertEqual(aa,bb)

if __name__=='__main__':unittest.main()
