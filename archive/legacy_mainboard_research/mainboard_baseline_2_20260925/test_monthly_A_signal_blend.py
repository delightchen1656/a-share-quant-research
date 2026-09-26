import unittest
import numpy as np
import pandas as pd
from monthly_A_signal_blend import price_signals,blend_score

class Signals(unittest.TestCase):
    def test_prefix_invariance(self):
        x=pd.Series(np.exp(np.arange(400)*.001),index=pd.bdate_range('2018-01-01',periods=400))
        pd.testing.assert_frame_equal(price_signals(x).iloc[:300],price_signals(x.iloc[:300]))
    def test_skip_recent_month(self):
        x=pd.Series(np.arange(1,401,dtype=float));y=x.copy();y.iloc[-21:]*=2
        self.assertEqual(price_signals(x).mom6.iloc[-1],price_signals(y).mom6.iloc[-1])
        self.assertEqual(price_signals(x).mom12.iloc[-1],price_signals(y).mom12.iloc[-1])
    def test_neutral_missing_signal(self):
        q=pd.DataFrame(dict(amount20=[1,2,3],near_high=[.8,.9,1.],dividend=[1,2,3],downside=[.1,.2,.3],turn20=[1,2,3],mom6=[np.nan]*3))
        base=blend_score(q,False)
        pd.testing.assert_series_equal(blend_score(q,False,'mom6',.3),.7*base.rank(pct=True)+.15)
    def test_original_missing_factor_still_excluded(self):
        q=pd.DataFrame(dict(dividend=[np.nan,2,3],downside=[.1,.2,.3],turn20=[1,2,3],mom6=[.1,.2,.3]))
        self.assertTrue(np.isnan(blend_score(q,False).iloc[0]))
        self.assertTrue(np.isnan(blend_score(q,False,'mom6',.3).iloc[0]))
    def test_refinement_inactive_regime_unchanged(self):
        from monthly_A_signal_refine import score
        q=pd.DataFrame(dict(dividend=[1,2,3],downside=[.1,.2,.3],turn20=[1,2,3],mom12=[.1,.2,.3]))
        pd.testing.assert_series_equal(score(q,False,'mom12_strong',.12),blend_score(q,False))

if __name__=='__main__':unittest.main()
