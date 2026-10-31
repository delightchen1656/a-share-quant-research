import unittest
import pandas as pd
from fixed_sl12_tp20 import simulate

class FixedExits(unittest.TestCase):
    def frame(self):
        f=pd.DataFrame(index=pd.bdate_range('2020-01-01',periods=65))
        for col,v in dict(open=100.,high=105.,low=95.,close=100.,raw_open=100.,raw_high=105.,raw_low=95.,raw_close=100.,preclose=100.,isST='0',active=True,unknown=False).items():f[col]=v
        return f
    def test_stop_and_target(self):
        f=self.frame();f.iloc[2,f.columns.get_loc('low')]=87
        self.assertAlmostEqual(simulate(f,0)['return_pct'],-.12)
        f=self.frame();f.iloc[2,f.columns.get_loc('high')]=121
        self.assertAlmostEqual(simulate(f,0)['return_pct'],.20)
    def test_dual_touch_is_stop_first_but_open_gap_has_priority(self):
        f=self.frame();f.loc[f.index[2],['high','low']]=[130,80]
        s=simulate(f,0);self.assertEqual(s['dual_touch'],1);self.assertAlmostEqual(s['return_pct'],-.12)
        f.loc[f.index[2],'open']=125
        s=simulate(f,0);self.assertEqual(s['reason'],'跳空止盈');self.assertAlmostEqual(s['return_pct'],.25)
    def test_gap_stop_is_not_clipped_to_minus12(self):
        f=self.frame();f.loc[f.index[2],['open','high','low']]=[80,85,75]
        s=simulate(f,0);self.assertAlmostEqual(s['return_pct'],-.20);self.assertTrue(s['worse_than_stop'])
    def test_tplus1_stop_waits_and_buy_day_profit_not_fillable(self):
        f=self.frame();f.loc[f.index[1],'low']=80;f.loc[f.index[2],'open']=90
        s=simulate(f,0);self.assertEqual(s['exit_day'],2);self.assertAlmostEqual(s['return_pct'],-.10)
        f=self.frame();f.loc[f.index[1],'high']=125
        s=simulate(f,0);self.assertTrue(s['buy_day_take']);self.assertEqual(s['exit_day'],61)
    def test_expiry_d61_open(self):
        f=self.frame();f.loc[f.index[60],'close']=102;f.loc[f.index[61],'open']=97
        s=simulate(f,0);self.assertEqual(s['exit_day'],61);self.assertAlmostEqual(s['return_pct'],-.03)
    def test_lower_limit_no_fill_then_pending_open(self):
        f=self.frame();f.loc[f.index[2],['open','high','low','close','raw_open','raw_high','raw_low','raw_close','preclose']]=[81]*8+[90]
        f.loc[f.index[3],'open']=80
        s=simulate(f,0);self.assertEqual(s['blocked_days'],1);self.assertEqual(s['exit_day'],3);self.assertAlmostEqual(s['return_pct'],-.20)
    def test_missing_entry_and_immature_window(self):
        f=self.frame();f.loc[f.index[1],'active']=False
        self.assertEqual(simulate(f,0)['status'],'D1_unavailable')
        self.assertEqual(simulate(self.frame().iloc[:61],0)['status'],'incomplete_D61')

if __name__=='__main__':unittest.main()
