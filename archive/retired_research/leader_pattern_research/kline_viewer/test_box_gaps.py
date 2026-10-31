import unittest,sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from box_gap_scan import describe

class BoxGapChecks(unittest.TestCase):
    def setUp(self):
        self.high=np.full(40,11.);self.low=np.full(40,10.)
        self.valid=np.ones(40,bool);self.dates=pd.bdate_range('2020-01-01',periods=40);self.t=35
    def result(self,raw_high=None,raw_low=None):
        return describe(self.high,self.low,self.high if raw_high is None else raw_high,self.low if raw_low is None else raw_low,self.valid,self.dates,self.t)
    def test_entry_and_signal_excluded_but_recorded(self):
        self.high[20:]=13;self.low[20:]=12
        self.high[35]=15;self.low[35]=14
        result=self.result()
        self.assertEqual(result['gap_count'],0)
        self.assertEqual(result['gap_entry']['direction'],'up')
        self.assertEqual(result['gap_signal']['direction'],'up')
    def test_up_gap_fills_in_base_and_no_future_peeking(self):
        self.high[25:]=13;self.low[25:]=12
        self.low[27]=10
        result=self.result();self.assertEqual(result['gap_up_count'],1)
        self.assertTrue(result['gap_details'][0]['filled_in_base'])
        self.assertEqual(result['gap_details'][0]['fill_date'],self.dates[27].strftime('%Y-%m-%d'))
        self.low[27]=12;self.low[36]=1
        self.assertEqual(self.result()['gap_unfilled_count'],1)
    def test_down_gap_can_fill_on_signal_only(self):
        self.high[25:]=9;self.low[25:]=8;self.high[35]=10
        result=self.result();self.assertEqual(result['gap_down_count'],1)
        self.assertEqual(result['gap_count'],1)
        self.assertFalse(result['gap_details'][0]['filled_in_base'])
        self.assertTrue(result['gap_details'][0]['filled_by_signal'])
    def test_raw_only_discontinuity_not_confirmed(self):
        rh=self.high.copy();rl=self.low.copy();rh[25:]=9;rl[25:]=8
        result=self.result(rh,rl)
        self.assertEqual(result['gap_count'],0)
        self.assertTrue(result['gap_review_details'][0]['raw_only'])
    def test_missing_bar_and_float_noise_not_counted(self):
        self.high[25:]=13;self.low[25:]=11+1e-9
        self.assertEqual(self.result()['gap_count'],0)
        self.low[25:]=12;self.valid[24]=False
        self.assertEqual(self.result()['gap_count'],0)

if __name__=='__main__':unittest.main()
