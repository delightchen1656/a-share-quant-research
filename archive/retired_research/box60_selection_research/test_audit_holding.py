import unittest
import pandas as pd
from audit_holding_grid import simulate,eligibility,selection_features,summarize,HORIZONS

class HoldingGridChecks(unittest.TestCase):
    def frame(self):
        return pd.DataFrame(dict(open=100.,high=110.,low=90.,close=100.,valid=True),index=pd.bdate_range('2025-01-01',periods=130))
    def test_forced_sale_is_n_plus_one_open_not_n_close(self):
        f=self.frame();f.loc[f.index[21],'open']=115;f.loc[f.index[20],'close']=80
        r=simulate(f,0,20);self.assertEqual(r['reason'],'forced_open');self.assertEqual(r['exit_day'],21);self.assertAlmostEqual(r['return_pct'],.15)
    def test_target_at_last_holding_day_prevents_forced_sale(self):
        f=self.frame();f.loc[f.index[20],'high']=140
        r=simulate(f,0,20);self.assertEqual(r['reason'],'take_profit_touch');self.assertEqual(r['exit_day'],20);self.assertEqual(r['return_pct'],.4)
    def test_buy_day_target_untradeable_and_exit_day_high_not_used(self):
        f=self.frame();f.loc[f.index[1],'high']=150;f.loc[f.index[21],'high']=200
        r=simulate(f,0,20);self.assertTrue(r['d1_hit_not_sellable']);self.assertEqual(r['reason'],'forced_open')
    def test_gap_take_uses_open(self):
        f=self.frame();f.loc[f.index[2],'open']=150
        r=simulate(f,0,20);self.assertEqual(r['reason'],'take_profit_gap');self.assertAlmostEqual(r['return_pct'],.5)
    def test_signal_filter_does_not_read_future_volume_or_prices(self):
        r=self.frame();r['volume']=100.;r['close']=101.
        a=selection_features(r,40);r.loc[r.index[41]:,['volume','open','close']]=99999
        self.assertEqual(selection_features(r,40),a)
    def test_maturity_and_missing_are_separate(self):
        f=self.frame().iloc[:91];self.assertEqual(eligibility(f,0,90),'not_mature')
        f=self.frame();f.loc[f.index[45],'valid']=False
        self.assertEqual(eligibility(f,0,90),'missing_or_suspended_quote');self.assertEqual(eligibility(f,0,20),'eligible')
    def test_counts_reconcile_and_profit_hits_monotonic(self):
        f=self.frame();f.loc[f.index[35],'high']=150
        results=[simulate(f,0,n) for n in HORIZONS]
        hits=[r['reason'].startswith('take_profit') for r in results];self.assertEqual(hits,sorted(hits))
        s=summarize(pd.DataFrame(results));self.assertEqual(s['take_profit_n']+s['forced_n'],len(HORIZONS))
        self.assertAlmostEqual(s['all_mean'],(s['take_profit_n']*s['take_profit_mean']+s['forced_n']*s['forced_mean'])/s['n'])

if __name__=='__main__':unittest.main()
