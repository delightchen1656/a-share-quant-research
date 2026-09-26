import json,unittest
import pandas as pd
import round15_historical_dividend as x

class HistoricalDividendTests(unittest.TestCase):
    def test_disclosure_and_completeness(self):
        data=json.loads(x.HOLDINGS.read_text(encoding='utf-8'))
        self.assertEqual(data['published'],'2019-08-27')
        self.assertEqual([r['ordinal'] for r in data['rows']],list(range(1,99)))
        self.assertAlmostEqual(sum(r['value'] for r in data['rows']),1104531453.35,places=2)
        self.assertEqual(len(x.CONFIGS),24)
    def test_carry_order_and_no_future_input(self):
        frame=pd.DataFrame(dict(symbol=['600001.SH','600002.SH','600003.SH'],
            distribution_proxy=[.01,.03,.05],long_risk=[1,2,3],vol60=[.03,.02,.01],downside=[.01]*3))
        cfg=dict(family='carry_long',buffer=2)
        self.assertEqual(x.rank(frame,cfg).symbol.tolist(),['600003.SH','600002.SH'])
        pd.testing.assert_frame_equal(x.rank(frame,cfg).reset_index(drop=True),x.rank(frame.iloc[::-1],cfg).reset_index(drop=True))

if __name__=='__main__':unittest.main()
