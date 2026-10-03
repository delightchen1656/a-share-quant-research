import unittest
import pandas as pd
import numpy as np
from prepare import bounded,COLS
from train import features,CUT,HORIZON

class CutoffTests(unittest.TestCase):
    def test_future_poison_does_not_change_snapshot(self):
        a=pd.DataFrame({c:[1.,2.,3.] for c in COLS if c!='date'})
        a['date']=pd.to_datetime(['2024-11-28','2024-11-29','2024-12-02'])
        b=a.copy();b.loc[2,[c for c in COLS if c!='date']]=1e99
        pd.testing.assert_frame_equal(bounded(a),bounded(b))
        self.assertEqual(len(bounded(a)),2)
    def make_data(self):
        dates=pd.bdate_range(end='2024-11-29',periods=400)
        close=10*np.exp(np.cumsum(np.sin(np.arange(400))*.02))
        x=pd.DataFrame(dict(date=dates,open=close,high=close,low=close,close=close,preclose=np.r_[close[0],close[:-1]],volume=1e7,amount=1e8,turn=1.,tradestatus=1.,isST=0.))
        return x,pd.Series(100*np.exp(np.cumsum(np.cos(np.arange(400))*.01)),index=dates)
    def test_outside_boundary_rejected(self):
        x,m=self.make_data();x.loc[len(x)-1,'date']=CUT
        with self.assertRaises(AssertionError):features(x,m)
    def test_label_embargo(self):
        x,m=self.make_data();f,_,_=features(x,m)
        self.assertTrue(f.label_end.tail(HORIZON).isna().all())
        self.assertLess(f.label_end.dropna().max(),CUT)
    def test_future_does_not_change_past_features(self):
        x,m=self.make_data();f,_,_=features(x,m)
        # Changing later within-cutoff prices may alter labels, never earlier signals.
        y=x.copy();y.loc[350:,['open','high','low','close','preclose']]*=7
        g,_,_=features(y,m)
        columns=['distribution_proxy','long_risk','market_adjusted','vol60','ret5','turn20','eligible']
        pd.testing.assert_frame_equal(f.iloc[:350][columns],g.iloc[:350][columns])
if __name__=='__main__':unittest.main()
