import unittest
import pandas as pd
from prepare_style_history import basket_index

class StyleHistoryTests(unittest.TestCase):
    def test_close_reconstitution_and_prefix(self):
        dates=pd.bdate_range('2020-01-01',periods=4)
        returns=pd.DataFrame({'A':[.9,.1,-1.,0.],'B':[0.,.9,.2,.3]},index=dates)
        sel={dates[0]:['A'],dates[1]:['B']}
        z=basket_index(returns,sel,dates)
        self.assertEqual(z.index_return.iloc[0],0.)
        self.assertAlmostEqual(z.index_return.iloc[1],.1)
        self.assertAlmostEqual(z.index_return.iloc[2],.2)
        pd.testing.assert_frame_equal(z.iloc[:3],basket_index(returns.iloc[:3],sel,dates[:3]))
    def test_terminal_loss_is_not_dropped(self):
        dates=pd.bdate_range('2020-01-01',periods=2)
        r=pd.DataFrame({'A':[0.,-1.],'B':[0.,0.]},index=dates)
        z=basket_index(r,{dates[0]:['A','B']},dates)
        self.assertEqual(z.index_value.iloc[-1],.5)

if __name__=='__main__':unittest.main()
