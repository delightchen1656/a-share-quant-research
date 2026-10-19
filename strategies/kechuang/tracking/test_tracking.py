"""Synthetic execution checks; no future market data and no production writes."""
import inspect, tempfile, unittest
from pathlib import Path
import pandas as pd
import run as tracker

class ExecutionTests(unittest.TestCase):
    def replay(self, opens):
        dates=pd.date_range('2000-01-03',periods=len(opens))
        frame=pd.DataFrame({'open':opens,'close':opens,'preclose':[10.]*len(opens),
            'prev_actual':[10.]*len(opens),'adjust_ratio':[1.]*len(opens),
            'volume':[1000000]*len(opens),'tradestatus':['1']*len(opens)},index=dates)
        src=inspect.getsource(tracker.engine.run_starts).replace('years=(END-start).days/365.25','years=max(1,(END-start).days)/365.25')
        env=dict(tracker.engine.__dict__);env.update(END=dates[-1],CASH=500000.)
        exec(src,env)
        return env['run_starts'](({'_exit_action':tracker.engine.old_exit},[{'max_positions':14}],dates,
            {'688001.SH':frame},{dates[0]:['688001.SH']},pd.DataFrame({'outDate':['']},index=['688001.SH']),set()),{},str(dates[1].date()))
    def test_single_session_and_t1(self):
        result,curve,trades,_=self.replay([10.,10.])
        self.assertEqual(list(trades.side),['BUY'])
        self.assertGreaterEqual(trades.iloc[0]['qty'],200)
        self.assertEqual(result['start'],'2000-01-04')
    def test_limit_up_no_buy(self):
        result,curve,trades,_=self.replay([10.,12.])
        self.assertTrue(trades.empty)
        self.assertEqual(result['final_asset'],500000.)
    def test_later_stop(self):
        result,curve,trades,_=self.replay([10.,10.,9.])
        self.assertEqual(list(trades.side),['BUY','STOP'])
    def test_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'event.json'
            tracker.write(path,{'x':1},True)
            tracker.write(path,{'x':1},True)
            with self.assertRaises(ValueError):tracker.write(path,{'x':2},True)

if __name__=='__main__':unittest.main()
