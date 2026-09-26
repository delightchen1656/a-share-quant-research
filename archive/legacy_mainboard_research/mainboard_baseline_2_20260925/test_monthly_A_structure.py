import unittest
import numpy as np
import pandas as pd
import monthly_A_structure_engine as e

class Selection(unittest.TestCase):
    def run_case(self,strict):
        e.START=pd.Timestamp('2024-01-02');e.END=pd.Timestamp('2024-01-03');e.INITIAL_CASH=100000.
        e.CALENDAR=pd.DatetimeIndex([e.START,e.END]);e.ACTION_MODE='ledger';e.ACTION_LEDGER={};e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[]
        e.STRICT_TARGET=strict;e.SELECTION_TRACE=[]
        rows=[dict(date=d,symbol=s,open=10.,close=10.,preclose=10.,volume=10000000.,tradestatus='1',isST='0') for d in e.CALENDAR for s in 'ABCDEFG']
        panel=pd.DataFrame(rows);e.PREPARED={d:q.set_index('symbol') for d,q in panel.groupby('date')}
        ranks={e.START:pd.DataFrame(dict(symbol=list('ABCDEFG'),downside=.02)),e.END:pd.DataFrame(dict(symbol=list('GABCDEF'),downside=.02))}
        curve,trades=e.simulate(ranks,.05,6,24,.8,1.5,panel,min_adjustment=3000)
        return e.SELECTION_TRACE,curve

    def test_legacy_edge_preserved_for_control(self):
        trace,_=self.run_case(False);self.assertEqual(len(trace[-1]['selected']),7)

    def test_strict_target_does_not_add_seventh(self):
        trace,curve=self.run_case(True)
        self.assertEqual(len(trace[-1]['selected']),6)
        self.assertNotIn('G',trace[-1]['selected'])
        self.assertGreaterEqual(curve.cash.min(),0)

if __name__=='__main__':unittest.main()
