import unittest,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from find_base_volume_bullish_v2 import detect

class BoxVolumeBoundaryChecks(unittest.TestCase):
    def sample(self,multiple):
        c=np.r_[np.linspace(12,10,21),np.full(15,10.),10.2]
        o=c.copy();o[-1]=10
        h=np.maximum(o,c)+.02;l=np.minimum(o,c)-.02
        v=np.r_[np.full(21,100.),np.full(15,150.),150*multiple]
        return c,h,l,v,np.ones(37,bool),o,c
    def test_inclusive_12_boundary_and_excludes_signal_from_mean(self):
        for multiple,want in [(1.1999,False),(1.2,True),(1.5,True),(2.,True)]:
            row=detect(*self.sample(multiple),min_volume_multiple=1.2).iloc[-1]
            self.assertEqual(bool(row.selected),want)
            self.assertEqual(row.base_mean_volume,150)
            self.assertAlmostEqual(row.volume_multiple,multiple)
    def test_threshold_changes_only_signal_volume_gate(self):
        args=self.sample(1.5)
        new=detect(*args,min_volume_multiple=1.2);old=detect(*args,min_volume_multiple=2)
        self.assertTrue(bool(new.selected.iloc[-1]));self.assertFalse(bool(old.selected.iloc[-1]))
        __import__('pandas').testing.assert_frame_equal(new.drop(columns='selected'),old.drop(columns='selected'))
        args=list(self.sample(1.5));args[4][-2]=False
        self.assertFalse(bool(detect(*args,min_volume_multiple=1.2).selected.iloc[-1]))

if __name__=='__main__':unittest.main()
