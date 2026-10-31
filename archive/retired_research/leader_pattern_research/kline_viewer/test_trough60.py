import sys,unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compute_trough60 import trough

class Trough60Checks(unittest.TestCase):
    def setUp(self):
        self.dates=pd.bdate_range('2020-01-01',periods=63)
        self.low=np.full(63,10.);self.valid=np.ones(63,bool)

    def test_signal_day_and_d61_excluded_d60_included_earliest_tie(self):
        self.low[0]=.01;self.low[60]=7;self.low[61]=.02
        result=trough(self.low,self.valid,self.dates,0,10)
        self.assertAlmostEqual(result['max_drop60'],.3)
        self.assertEqual(result['trough_day60'],60)
        self.low[1]=7
        self.assertEqual(trough(self.low,self.valid,self.dates,0,10)['trough_day60'],1)

    def test_no_drop_below_reference_is_zero_not_positive_gain(self):
        self.low[:]=11
        result=trough(self.low,self.valid,self.dates,0,10)
        self.assertEqual(result['max_drop60'],0)
        self.assertAlmostEqual(result['trough_return60'],.1)

    def test_missing_and_unfinished_do_not_report_full_extreme(self):
        self.valid[15]=False
        missing=trough(self.low,self.valid,self.dates,0,10)
        self.assertEqual(missing['trough_status60'],'观察期缺价')
        self.assertEqual(missing['trough_observed_days60'],59)
        self.assertIsNone(missing['max_drop60'])
        result=trough(self.low,np.ones(63,bool),self.dates,4,10)
        self.assertEqual(result['trough_status60'],'未满60日')
        self.assertIsNone(result['max_drop60'])

if __name__=='__main__':unittest.main()
