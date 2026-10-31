import unittest
from sse_data import reversals,history


class SSERegimesTest(unittest.TestCase):
    def bars(self,values):return [dict(date='2020-01-'+str(i+1).zfill(2),close=v) for i,v in enumerate(values)]
    def test_exact10percent_confirmation_and_separate_pivot(self):
        r=reversals(self.bars([100,110,120,108]))
        self.assertEqual([(e['mode'],e['pivot'],e['confirmed']) for e in r],
            [('bull','2020-01-01','2020-01-02'),('bear','2020-01-03','2020-01-04')])
    def test_later_prices_do_not_rewrite_existing_confirmations(self):
        bars=self.bars([100,110,120,115,108,100,109,110,120])
        full=reversals(bars)
        for i in range(1,len(bars)+1):
            self.assertEqual(reversals(bars[:i]),[e for e in full if e['confirmed']<=bars[i-1]['date']])
        self.assertEqual(len(reversals(self.bars([100,110,115]))),1)
    def test_invalid_close_rejected_and_export_contract(self):
        with self.assertRaises(ValueError):reversals(self.bars([100,float('nan')]))
        d=history();self.assertEqual(d['code'],'000001.SH');self.assertEqual(d['threshold'],.10)
        self.assertEqual(len({p['stats']['id'] for p in d['phases'] if p['stats']}),18)
        self.assertTrue(d['phases'][-1]['unfinished'])
    def test_visual_validation_is_separate_and_never_future_enabled(self):
        d=history();visual=d['visual_validation']
        self.assertEqual(d['default_method'],'visual_validation')
        self.assertFalse(visual['future_trading_use']);self.assertFalse(visual['future_parameter_selection_use'])
        self.assertFalse(visual['automatic_extension']);self.assertEqual(len(visual['phases']),20)
        self.assertTrue(all(p['confirmed'] is None for p in visual['phases']))
        bars={b[0]:b for b in d['bars']}
        for p in visual['phases']:
            candle=bars[p['start']]
            self.assertEqual(p['marker_price'],candle[3] if p['state']=='bull' else candle[2])


if __name__=='__main__':unittest.main()
