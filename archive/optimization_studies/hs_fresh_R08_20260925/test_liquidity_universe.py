import unittest
import pandas as pd
import research as r
import round08_long_momentum as original
from round13_liquidity_universe import rank,filter_universe,PATH,CONFIGS,OriginalRank

class LiquidityTests(unittest.TestCase):
    def test_50m_control_matches_previous_universe(self):
        f=pd.read_parquet(PATH);old=pd.read_parquet(original.FEATURES)
        for d in sorted(old.execute_date.unique())[::250]:
            a=f[f.execute_date==d];b=old[old.execute_date==d]
            x=filter_universe(a,50).set_index('symbol').float_cap_proxy_group.sort_index()
            y=b.set_index('symbol').float_cap_proxy_group.sort_index()
            pd.testing.assert_series_equal(x,y)
            for signal in ('carry_long','defensive','liquidity'):
                cfg=dict(family=signal+'@50',size='mid',buffer=60)
                got=rank(a,cfg).reset_index(drop=True)
                fn=original.rank if signal=='carry_long' else OriginalRank
                expected=fn(b,dict(cfg,family=signal)).reset_index(drop=True)
                pd.testing.assert_frame_equal(got,expected)
    def test_count(self):self.assertEqual(len(CONFIGS),36)

if __name__=='__main__':unittest.main()
