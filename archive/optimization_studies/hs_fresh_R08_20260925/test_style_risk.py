import unittest
import numpy as np
import pandas as pd
from round20_style_risk import reference_prices,CONFIGS
from round19_daily_risk import exposures

class StyleRiskTests(unittest.TestCase):
    def test_reference_and_signal_prefix(self):
        rng=np.random.default_rng(11);dates=pd.bdate_range('2019-01-01',periods=500)
        a=pd.Series(np.exp(np.cumsum(rng.normal(0,.01,500))),index=dates)
        b=pd.Series(np.exp(np.cumsum(rng.normal(0,.015,500))),index=dates)
        refs=reference_prices(a,b);prefix=reference_prices(a.iloc[:400],b.iloc[:400])
        changed=a.copy();changed.iloc[400:]*=2
        for key in refs:
            pd.testing.assert_series_equal(refs[key].iloc[:400],prefix[key])
            for mode in ('trend60','trend120'):
                pd.testing.assert_series_equal(exposures(refs[key],mode).iloc[:401],
                    exposures(reference_prices(changed,b)[key],mode).iloc[:401])
        self.assertEqual(len(CONFIGS),8)

if __name__=='__main__':unittest.main()
