import unittest
import numpy as np
import pandas as pd
from round08_long_momentum import long_features

class LongMomentumTests(unittest.TestCase):
    def test_prefix_and_latest20_exclusion(self):
        rng=np.random.default_rng(8);idx=pd.bdate_range('2018-01-01',periods=700)
        m=pd.Series(np.exp(np.cumsum(rng.normal(0,.01,700))),index=idx)
        c=pd.Series(np.exp(np.cumsum(rng.normal(0,.02,700))),index=idx)
        pd.testing.assert_frame_equal(long_features(c,m).iloc[:600],long_features(c.iloc[:600],m.iloc[:600]))
        changed=c.copy();changed.iloc[-20:]*=2
        np.testing.assert_allclose(long_features(c,m).iloc[-1],long_features(changed,m).iloc[-1])
    def test_market_copy_has_zero_adjusted_momentum(self):
        rng=np.random.default_rng(81);idx=pd.bdate_range('2018-01-01',periods=700)
        m=pd.Series(np.exp(np.cumsum(rng.normal(0,.01,700))),index=idx)
        z=long_features(m,m).dropna()
        np.testing.assert_allclose(z.market_adjusted,0,atol=1e-10)

if __name__=='__main__':unittest.main()
