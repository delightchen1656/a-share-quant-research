import unittest,sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from observe_next_open60 import observe

class NextOpenBasisChecks(unittest.TestCase):
    def setUp(self):
        self.dates=pd.bdate_range('2020-01-03',periods=63);n=len(self.dates)
        self.o=np.full(n,10.);self.o[1]=12.;self.h=np.full(n,14.);self.l=np.full(n,9.);self.c=np.full(n,10.)
        self.h[0]=999;self.l[0]=.01;self.h[60]=24;self.l[60]=8;self.h[61]=888;self.l[61]=.02
        self.raw=self.o*10;self.valid=np.ones(n,bool)
    def result(self,t=0):return observe(self.o,self.h,self.l,self.c,self.raw,self.valid,self.dates,t)
    def test_next_session_open_and_same_horizon_not_close(self):
        r=self.result();self.assertEqual(r['entry_open'],12);self.assertEqual(r['entry_raw_open'],120)
        self.assertEqual(r['entry_date'],'2020-01-06');self.assertEqual(r['return_basis'],'next_session_open')
        self.assertAlmostEqual(r['peak_return60'],1.)
        self.assertAlmostEqual(r['max_drop60'],1-8/12)
        self.assertEqual(r['peak_day60'],60);self.assertEqual(r['trough_day60'],60)
        self.assertAlmostEqual(r['adjusted_price_change'],10/12-1)
    def test_entry_day_extremes_included(self):
        self.h[1]=30;self.l[1]=7;r=self.result()
        self.assertEqual(r['peak_day60'],1);self.assertEqual(r['trough_day60'],1)
        self.assertAlmostEqual(r['peak_return60'],1.5)
    def test_missing_next_open_never_rolls_forward(self):
        self.valid[1]=False;r=self.result()
        self.assertIsNone(r['entry_open']);self.assertEqual(r['entry_status'],'次日开盘缺价')
        self.assertIsNone(r['peak_return60']);self.assertIsNone(r['max_drop60'])
        self.assertIsNone(r['adjusted_price_change']);self.assertFalse(r['peak_complete60'])
    def test_latest_signal_waits_for_next_session(self):
        r=self.result(len(self.dates)-1)
        self.assertEqual(r['entry_status'],'待次日行情');self.assertIsNone(r['entry_date']);self.assertIsNone(r['entry_open'])

if __name__=='__main__':unittest.main()
