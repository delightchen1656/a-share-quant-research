import unittest
import pandas as pd
from monthly_A_invested_sharpe import select_diversified,exposure_stats,longest

class Invested(unittest.TestCase):
    def setUp(self):
        self.ranks=pd.DataFrame(dict(symbol=list('ABC')))
        self.corr=pd.DataFrame([[1,1,0],[1,1,0],[0,0,1]],index=list('ABC'),columns=list('ABC'))

    def test_zero_penalty_keeps_alpha_order(self):
        self.assertEqual(select_diversified(self.ranks,{},2,self.corr,0,0),['A','B'])

    def test_correlation_penalty_changes_second_choice(self):
        self.assertEqual(select_diversified(self.ranks,{},2,self.corr,1,0),['A','C'])

    def test_exposure_counts_real_stock_value(self):
        curve=pd.DataFrame(dict(equity=[100.,100.,100.,100.],stock_value=[90.,0.,0.,80.]))
        z=exposure_stats(curve)
        self.assertEqual(z['flat_days'],2);self.assertEqual(z['max_flat_streak'],2)
        self.assertAlmostEqual(z['mean_exposure'],.425)
        self.assertEqual(longest([True,False,True,True]),2)

if __name__=='__main__':unittest.main()
