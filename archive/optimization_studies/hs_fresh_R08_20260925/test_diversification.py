import unittest
import numpy as np
import pandas as pd
from round07_diversification import past_correlation,diversified_selection

class DiversificationTests(unittest.TestCase):
    def test_future_prices_cannot_change_selection(self):
        rng=np.random.default_rng(123);dates=pd.bdate_range('2019-01-01',periods=400)
        f=pd.DataFrame(rng.normal(size=(400,6)),index=dates,columns=list('ABCDEF'))
        altered=f.copy();altered.loc[dates[300]:]=999
        a=past_correlation(f,dates[300],list(f),250)
        b=past_correlation(altered,dates[300],list(f),250)
        np.testing.assert_array_equal(a,b)
        self.assertEqual(diversified_selection(list(f),a,{'A'},3,2),diversified_selection(list(f),b,{'A'},3,2))
    def test_redundant_stock_is_disfavored(self):
        corr=np.array([[1,.9,0],[.9,1,0],[0,0,1.]])
        self.assertEqual(diversified_selection(list('ABC'),corr,set(),2,2),['A','C'])
    def test_missing_history_is_not_free_diversification(self):
        f=pd.DataFrame({'A':[1.,2.,3.],'B':[np.nan]*3},index=pd.bdate_range('2020-01-01',periods=3))
        a=past_correlation(f,pd.Timestamp('2020-02-01'),list(f),120)
        self.assertEqual(a[0,1],.75)

if __name__=='__main__':unittest.main()
