import unittest
import pandas as pd
import research as r
import round08_long_momentum as original
from round12_core_neighborhood import rank,WEIGHTS,CONFIGS

class CoreTests(unittest.TestCase):
    def test_control_exactly_matches_original(self):
        f=pd.read_parquet(original.FEATURES)
        for d in sorted(f.execute_date.unique())[::250]:
            x=f[f.execute_date==d]
            a=rank(x,dict(family='mix433',buffer=60))
            b=original.rank(x,dict(family='carry_long',size='mid',buffer=60))
            pd.testing.assert_frame_equal(a,b)
    def test_limited_grid(self):
        self.assertEqual(len(CONFIGS),15)
        self.assertTrue(all(abs(sum(x)-1)<1e-12 for x in WEIGHTS.values()))

if __name__=='__main__':unittest.main()
