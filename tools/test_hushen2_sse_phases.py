import unittest
import pandas as pd
from replay_hushen2_sse_phases import zigzag_phases


class SSEPhaseTest(unittest.TestCase):
    def series(self,values):return pd.Series(values,index=pd.bdate_range('2019-01-02',periods=len(values)))
    def test_peak_boundary_uses_later_confirmation(self):
        s=self.series([100,110,120,115,108]);p=zigzag_phases(s)
        self.assertEqual(p[0]['direction'],'up')
        self.assertEqual(p[0]['end'],s.index[2])
        self.assertEqual(p[0]['confirmed_at'],s.index[4])
        self.assertFalse(p[-1]['complete'])

    def test_trough_boundary_and_threshold_are_asymmetric_ratios(self):
        s=self.series([120,108,100,109,110]);p=zigzag_phases(s)
        self.assertEqual(p[0]['direction'],'down')
        self.assertEqual(p[0]['end'],s.index[2])
        self.assertEqual(p[0]['confirmed_at'],s.index[4])
        self.assertEqual(p[-1]['direction'],'up')

    def test_subthreshold_changes_do_not_create_new_completed_phase(self):
        s=self.series([100,110,120,119,115,109]);p=zigzag_phases(s)
        self.assertEqual(len(p),1)
        self.assertFalse(p[0]['complete'])

    def test_flat_series_has_no_direction(self):
        self.assertEqual(zigzag_phases(self.series([100,100,100])),[])


if __name__=='__main__':unittest.main()
