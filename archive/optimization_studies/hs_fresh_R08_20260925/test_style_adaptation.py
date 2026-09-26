import unittest
import pandas as pd
import numpy as np
from round14_style_adaptation import lagged_scores,rank,CONFIGS

class AdaptationTests(unittest.TestCase):
    def test_current_and_future_returns_cannot_affect_current_score(self):
        rng=np.random.default_rng(14);x=pd.Series(rng.normal(0,.01,400),index=pd.bdate_range('2019-01-01',periods=400))
        changed=x.copy();changed.iloc[300:]=.5
        pd.testing.assert_frame_equal(lagged_scores(x).iloc[:301],lagged_scores(changed).iloc[:301])
    def test_highest_style_and_fixed_control(self):
        f=pd.DataFrame([dict(execute_date=pd.Timestamp('2020-01-02'),style=s,symbol=s+str(i),ordinal=i,downside=.01,momentum126=v) for s,v in [('carry_mid',0.),('defensive_small',1.)] for i in range(3)])
        a=rank(f,dict(family='momentum126_1',buffer=2))
        self.assertTrue(a.symbol.str.startswith('defensive').all())
        b=rank(f,dict(family='fixedcarry',buffer=2))
        self.assertTrue(b.symbol.str.startswith('carry').all())
        self.assertEqual(len(CONFIGS),36)

if __name__=='__main__':unittest.main()
