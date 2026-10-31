import importlib.util,json,tempfile,unittest
from pathlib import Path
import pandas as pd
spec=importlib.util.spec_from_file_location('practice',Path(__file__).with_name('app.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class GameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.g=m.Game(Path(cls.tmp.name));cls.g.load()
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_01_frozen_atr_only(self):
        self.assertTrue(self.g.signals.atr_pct.ge(.025).all())
        self.assertTrue(self.g.signals.groupby('date').size().le(3).all())
    def test_02_known_stop_matches_original_engine(self):
        s=self.g.signals;idx=s.index[s.date.eq(pd.Timestamp('2020-01-02'))&s.symbol.eq('600802.SH')][0]
        case=self.g.case(idx);self.assertEqual(case['reason'],'stop')
        self.assertAlmostEqual(case['ret'],-.04941756051779773,places=12)
        self.assertEqual(case['trade']['entry_date'],'2020-01-03')
    def test_03_no_future_in_question_and_resume(self):
        c=self.g.next('guess');self.assertNotIn('result',c);self.assertNotIn('reason',c)
        self.assertEqual(c['name'],'历史信号')
        self.assertTrue(all(b['time']<=c['day'] for b in c['bars']))
        self.assertEqual(c['id'],self.g.next('guess')['id'])
        r=self.g.answer(c['id'],'stop');self.assertTrue(r['case']['revealed'])
        self.assertEqual(r['stats']['total'],1)
        self.assertEqual(sum(x['total'] for x in r['stats']['counts'].values()),1)
        with self.assertRaises(ValueError):self.g.answer(c['id'],'stop')
    def test_04_skip_and_buy_nav(self):
        c=self.g.next('trade');r=self.g.answer(c['id'],'skip');self.assertEqual(r['stats']['nav'],1.)
        c=self.g.next('trade');r=self.g.answer(c['id'],'buy')
        self.assertAlmostEqual(r['stats']['nav'],1+r['case']['result']['ret'])
        self.assertEqual(len(r['stats']['journal']),2)
        with self.assertRaises(ValueError):self.g.answer(c['id'],'buy')
    def test_05_invalid_mode(self):
        with self.assertRaises(ValueError):self.g.next('anything')
    def test_06_early_stop_does_not_truncate_30_calendar_day_chart(self):
        s=self.g.signals;idx=s.index[s.date.eq(pd.Timestamp('2020-01-02'))&s.symbol.eq('600802.SH')][0]
        case=self.g.case(idx);view=self.g.candles(case,True)
        deadline=pd.Timestamp(case['trade']['entry_date'])+pd.Timedelta(days=30)
        q,_=self.g.bar_cache[case['symbol']]
        expected=q.loc[q.date.between(pd.Timestamp(case['day'])-pd.DateOffset(years=1),deadline)&q.tradestatus.eq(1),'date']
        self.assertEqual([r['time'] for r in view['bars']],[d.date().isoformat() for d in expected])
        self.assertGreater(view['bars'][-1]['time'],case['trade']['exit_date'])
        self.assertEqual(view['levels']['deadline'],deadline.date().isoformat())
        self.assertTrue(view['window_complete'])
        hidden=self.g.candles(case,False)
        self.assertTrue(all(r['time']<=case['day'] for r in hidden['bars']))
        self.assertTrue(all(d.weekday()<5 for d in map(pd.Timestamp,view['axis_sessions'])))
if __name__=='__main__':unittest.main()
