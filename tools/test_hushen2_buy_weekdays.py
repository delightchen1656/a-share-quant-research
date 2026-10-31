"""Entry gate regression: all days reproduce baseline, no days only expire."""
import pickle,unittest
import pandas as pd
from research_hushen2_buy_weekdays import make_engine,CASES


class WeekdayGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (CASES/'INPUT_PACK.pkl').open('rb') as f:cls.p=pickle.load(f)

    def replay(self,allowed):
        p=self.p;core=make_engine(allowed);start=pd.Timestamp('2020-01-02');end=pd.Timestamp('2020-12-31')
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end-pd.Timedelta(days=37);core.YEARS=[2020]
        curve=[];gaps=set()
        r,t=core.simulate(p['signals'].loc[p['signals'].date.between(start,core.LAST_SIGNAL_DATE)],
            p['bars'],[d for d in p['calendar'] if d<=end],'C04_NEW',0.,30,'take4.00_stop1.50',4.,1.5,
            keep_trades=True,actions=p['actions'],known_action_keys=p['known'],coverage_sink=gaps,
            delist_dates=p['delists'],slots=5,equity_curve_sink=curve)
        self.assertFalse(gaps)
        return r,t,pd.DataFrame(curve)

    def test_all_weekdays_exactly_reproduce_baseline(self):
        r,t,c=self.replay(None);rr,tt,cc=self.replay(tuple(range(7)))
        pd.testing.assert_frame_equal(t,tt);pd.testing.assert_frame_equal(c,cc)
        self.assertEqual(r['fixed_order_attempts'],rr['fixed_order_attempts'])

    def test_no_weekdays_keeps_orders_until_original_expiry(self):
        r,t,c=self.replay(())
        self.assertEqual(r['filled_orders'],0);self.assertTrue(t.empty)
        self.assertEqual(r['pending_orders_created'],r['expired_entry_orders'])
        self.assertEqual(r['pending_orders_at_end'],0)
        self.assertTrue(c.equity.eq(100000).all())


if __name__=='__main__':unittest.main()
