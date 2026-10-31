import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from hushen1 import Desk
from hushen1_performance import build


class DailyReturnsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.desk=Desk(self.root/'account')
        self.days=['2026-10-28','2026-10-29','2026-10-30','2026-11-02']
        self.events=[]
        self.p=patch.object(self.desk,'events',side_effect=lambda:self.events);self.p.start();self.addCleanup(self.p.stop)
    def add(self,kind,date,**data):
        self.events.append(dict(id=len(self.events)+1,kind=kind,voided=False,data=dict(date=date,**data)))
    def quotes(self,days,prices):
        p=self.root/'raw/SZ/000001.SZ.parquet';p.parent.mkdir(parents=True,exist_ok=True)
        pd.DataFrame(dict(date=days,close=prices)).to_parquet(p)
    def run_curve(self,end='2026-11-02'):
        return build(self.desk,self.days,end,self.root,'2026-11-02')['daily']
    def test_fills_fees_closes_and_weekend(self):
        self.add('buy',self.days[1],symbol='000001.SZ',quantity=100,price=10,fee=5)
        self.add('sell',self.days[2],symbol='000001.SZ',quantity=100,price=12,fee=6)
        self.quotes([self.days[1]],[11])
        rows=self.run_curve();self.assertEqual([r['pnl'] for r in rows],[0,95,94,0])
        self.assertEqual(rows[-1]['cumulative_pnl'],189)
        self.assertEqual(len(rows),4);self.assertEqual(len(self.events),2)
    def test_external_flow_reconciliation_and_unknown_classification(self):
        self.add('cash_adjust',self.days[1],amount=1000,note='deposit',flow_type='external')
        self.add('cash_adjust',self.days[2],amount=-5,note='cost',flow_type='reconciliation')
        rows=self.run_curve();self.assertEqual([r['pnl'] for r in rows],[0,0,-5,0])
        self.assertEqual(rows[-1]['cumulative_pnl'],-5)
        self.events[0]['data'].pop('flow_type');self.assertIsNone(self.run_curve()[1]['pnl'])
        self.assertIsNone(self.run_curve()[-1]['net_equity'])
        self.add('classify_cash',self.days[3],event_id=1,flow_type='external')
        self.assertEqual(self.run_curve()[-1]['cumulative_pnl'],-5)
    def test_missing_quote_not_forward_filled_and_late_fill_or_void_recomputes(self):
        self.add('buy',self.days[1],symbol='000001.SZ',quantity=100,price=10,fee=5)
        self.quotes([self.days[1],self.days[3]],[11,12])
        rows=self.run_curve();self.assertIsNone(rows[2]['equity']);self.assertIsNone(rows[3]['pnl'])
        self.assertEqual(rows[3]['cumulative_pnl'],195)
        self.events[0]['voided']=True
        self.assertEqual([r['pnl'] for r in self.run_curve()],[0,0,0,0])
    def test_share_and_cash_arrivals_and_committed_date_boundary(self):
        self.add('buy',self.days[1],symbol='000001.SZ',quantity=100,price=10,fee=5)
        self.add('corporate',self.days[2],symbol='000001.SZ',cash=10,shares=100,note='credited')
        self.quotes(self.days[1:],[10,5,5])
        rows=self.run_curve(self.days[2]);self.assertEqual([r['pnl'] for r in rows],[0,-5,10])
        self.assertEqual(rows[-1]['cumulative_pnl'],5)


if __name__=='__main__':unittest.main()
