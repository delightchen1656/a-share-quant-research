import unittest
import numpy as np
import pandas as pd
from round11_high_floor import risk_exposures,MODES,CONFIGS

class HighFloorTests(unittest.TestCase):
    def test_past_only_and_high_floor(self):
        rng=np.random.default_rng(331);s=pd.Series(np.exp(np.cumsum(rng.normal(0,.02,600))),index=pd.bdate_range('2018-01-01',periods=600))
        altered=s.copy();altered.iloc[400:]*=3
        for mode in MODES:
            a=risk_exposures(s,mode);b=risk_exposures(altered,mode)
            pd.testing.assert_series_equal(a.iloc[:401],b.iloc[:401])
            pd.testing.assert_series_equal(a.iloc[:400],risk_exposures(s.iloc[:400],mode))
            self.assertGreaterEqual(a.min(),.60);self.assertLessEqual(a.max(),.95)
    def test_controls(self):
        s=pd.Series(np.arange(1.,201.))
        self.assertTrue((risk_exposures(s,'fixed85')==.85).all())
        self.assertEqual(risk_exposures(s,'trend65').iloc[-1],.95)
        self.assertEqual(len(CONFIGS),24)

if __name__=='__main__':unittest.main()
