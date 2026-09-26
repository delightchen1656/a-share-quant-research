import unittest
import pandas as pd
import numpy as np
from prepare_earnings_value import add_value

class EarningsValueTests(unittest.TestCase):
    def test_uses_selected_report_not_latest_profit(self):
        f=pd.DataFrame(dict(symbol=['600001.SH']*3,fin_report=pd.to_datetime(['2018-12-31','2019-12-31',None]),float_cap_proxy=[100]*3))
        lookup=pd.DataFrame(dict(symbol=['600001.SH']*3,fin_report=pd.to_datetime(['2018-12-31','2019-12-31','2020-12-31']),annual_profit=[10,-5,900]))
        z=add_value(f,lookup)
        np.testing.assert_allclose(z.earnings_float_proxy.iloc[:2],[.1,-.05])
        self.assertTrue(pd.isna(z.earnings_float_proxy.iloc[2]))
        pd.testing.assert_frame_equal(z,add_value(f,lookup.iloc[:2]))

    def test_rank_universe_and_permutation(self):
        import round18_earnings_value as m
        f=pd.DataFrame(dict(symbol=['600001.SH','600002.SH','600003.SH'],downside=[.01]*3,
            float_cap_proxy_group=[1,1,2],earnings_float_proxy=[.1,.2,.3],vol60=[.01,.02,.03],
            fin_roe=[10,20,30],fin_cash=[1,2,3],fin_margin=[5,10,15],ret20=[.05,.03,.01]))
        self.assertEqual(len(m.CONFIGS),24)
        for cfg in m.CONFIGS:
            c=dict(cfg,buffer=60);a=m.rank(f,c);b=m.rank(f.iloc[::-1],c)
            pd.testing.assert_frame_equal(a.reset_index(drop=True),b.reset_index(drop=True))
            self.assertEqual(len(a),2 if c['size']=='mid' else 1)

if __name__=='__main__':unittest.main()
