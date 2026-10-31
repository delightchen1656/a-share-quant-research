"""Synthetic adapter checks. Uses temporary ledgers, never the real account."""
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
import pandas as pd

from run_june2020_starts import ARCHIVE, BASE, module
from software_execution import adapted_engine, software_order_parameters, software_take_price, software_stop_price
sys.path.insert(0,str(BASE/'tracker'))
from store import Ledger


class SoftwareExecutionTest(unittest.TestCase):
    def test_protection_quotes_equal_actual_ledger(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger=Ledger(Path(folder)/'test.sqlite3')
            ledger.append('accept',dict(signal_id='s',symbol='600000.SH',name='test',signal_date='2020-01-02',atr=.024,trigger=10.,quantity=1900))
            ledger.append('buy',dict(order_id='s',date='2020-01-03',quantity=1900,price=9.9817,fee=5.69))
            p=ledger.state('2020-01-03')['positions'][0]
            self.assertEqual(p['take'],software_take_price(9.9817,.024))
            self.assertEqual(p['stop'],software_stop_price(9.9817,.024))

    def test_reserve_and_round_lots(self):
        self.assertEqual(software_order_parameters(100000,100000,0,[],10),(20000,1900))
        pending=[SimpleNamespace(quantity=1900,target=10.)]
        budget,qty=software_order_parameters(100000,25000,0,pending,10)
        self.assertEqual(budget,5995)
        self.assertEqual(qty,500)

    def test_gap_down_keeps_order_quantity_and_future_expiry(self):
        core=adapted_engine(module('synthetic_software_engine',ARCHIVE/'research/run_batch.py'))
        start=pd.Timestamp('2020-01-02');end=pd.Timestamp('2020-01-03')
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=[2020]
        signals=pd.DataFrame([dict(date=start,symbol='600000.SH',factor='C04_NEW',close=10.,atr_pct=.024,score=1.)])
        bars=pd.DataFrame([dict(date=start,open=10.,high=10.,low=10.,close=10.,preclose=10.,volume=10000000,tradestatus=1),
                           dict(date=end,open=5.,high=5.1,low=4.9,close=5.,preclose=10.,volume=10000000,tradestatus=1)]).set_index('date')
        result,trades=core.simulate(signals,{'600000.SH':bars},list(pd.bdate_range(start,'2020-03-02')),
            'C04_NEW',0.,30,'test',4.,1.5,keep_trades=True,slots=5,known_action_keys={'600000.SH/2020'})
        self.assertTrue(trades.empty)
        self.assertEqual(result['terminal_positions'][0]['quantity'],1900)
        self.assertEqual(result['terminal_positions'][0]['deadline'],'2020-02-02')
        self.assertEqual(result['open_positions_at_end'],1)

    def test_unfilled_buy_expires_before_nightly_new_orders(self):
        core=adapted_engine(module('synthetic_expiry_engine',ARCHIVE/'research/run_batch.py'))
        start=pd.Timestamp('2020-01-02');end=start+pd.Timedelta(days=7)
        core.EVAL_START=start;core.HARD_MAX_DATE=end;core.LAST_SIGNAL_DATE=end;core.YEARS=[2020]
        signals=pd.DataFrame([dict(date=start,symbol='600000.SH',factor='C04_NEW',close=10.,atr_pct=.024,score=1.)])
        bars=pd.DataFrame([dict(date=d,open=11.,high=11.,low=11.,close=11.,preclose=11.,volume=10000000,tradestatus=1)
                           for d in pd.bdate_range(start,end)]).set_index('date')
        result,_=core.simulate(signals,{'600000.SH':bars},list(pd.bdate_range(start,'2020-03-02')),
            'C04_NEW',0.,30,'test',4.,1.5,slots=5,known_action_keys={'600000.SH/2020'})
        self.assertEqual(result['pending_orders_at_end'],0)
        self.assertEqual(result['terminal_orders'],[])


if __name__=='__main__':unittest.main()
