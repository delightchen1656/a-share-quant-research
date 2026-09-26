import unittest
import pandas as pd
import numpy as np
from round03 import calendar_dates
from round04 import adjustment_features

class NewRounds(unittest.TestCase):
    def test_common_calendar_after_entry(self):
        cal=pd.bdate_range('2020-01-01','2020-12-31')
        a=calendar_dates(cal,pd.Timestamp('2020-01-02'),cal[-1],'biweekly')
        b=calendar_dates(cal,pd.Timestamp('2020-01-08'),cal[-1],'biweekly')
        self.assertEqual([d for d in a if d>pd.Timestamp('2020-01-08')],b[1:])
    def test_adjustment_prefix_invariance(self):
        frame=pd.DataFrame(dict(close=np.arange(1,1001),preclose=np.arange(1,1001)),index=pd.bdate_range('2018-01-01',periods=1000))
        pd.testing.assert_frame_equal(adjustment_features(frame).iloc[:800],adjustment_features(frame.iloc[:800]))
    def test_labels_have_maturity_and_terminal_loss(self):
        from prepare_learning import labels
        cal=pd.bdate_range('2020-01-01',periods=10);close=pd.Series(10.,index=cal)
        z=labels(close,cal,5,cal[4])
        self.assertEqual(z.target5.iloc[0],-1.)
        self.assertEqual(z.label_end5.iloc[0],cal[5])
        self.assertTrue(z.label_end5.iloc[-1]!=z.label_end5.iloc[-1])

if __name__=='__main__':unittest.main()
