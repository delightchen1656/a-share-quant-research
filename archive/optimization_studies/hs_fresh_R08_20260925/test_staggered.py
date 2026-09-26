import unittest
import pandas as pd
import numpy as np
from round22_staggered import allocations,schedule,combine_curves,audit_trades,CONFIGS

class StaggeredTests(unittest.TestCase):
    def test_capital_and_fixed_calendar(self):
        cal=pd.bdate_range('2020-01-01','2021-12-31');start=pd.Timestamp('2020-02-13')
        for books in (2,3):
            self.assertAlmostEqual(sum(allocations(books)),100000.,places=8)
            future=[]
            for phase in range(books):
                dates=schedule(cal,start,cal[-1],books,phase)
                self.assertEqual(dates[0],start)
                self.assertTrue(all((d.month-1)%books==phase for d in dates[1:]))
                future.extend(dates[1:])
            self.assertEqual(len(future),len(set(future)))
        self.assertEqual(len(CONFIGS),12)
    def test_dollar_combination_not_average_sharpe(self):
        dates=pd.date_range('2020-01-01',periods=2)
        a=pd.DataFrame(dict(date=dates,equity=[55000.,50000.],cash=[10000.,10000.],stock_value=[45000.,40000.],holdings=[4,4]))
        b=pd.DataFrame(dict(date=dates,equity=[45000.,60000.],cash=[5000.,5000.],stock_value=[40000.,55000.],holdings=[4,4]))
        out=combine_curves([a,b]);np.testing.assert_allclose(out.equity,[100000,110000])
        np.testing.assert_allclose(out.cash,[15000,15000]);self.assertEqual(out.holding_slots.tolist(),[8,8])
    def test_aggregate_volume_and_tplus1_checks(self):
        d=pd.Timestamp('2020-01-02');prepared={d:pd.DataFrame(dict(symbol=['A'],volume=[10000])).set_index('symbol')}
        t=pd.DataFrame(dict(date=[d,d],symbol=['A','A'],quantity=[200,200],side=['BUY','BUY']))
        self.assertEqual(audit_trades(t,prepared),.04)
        t.loc[1,'quantity']=400
        with self.assertRaises(AssertionError):audit_trades(t,prepared)
        t.loc[1,'quantity']=200;t.loc[1,'side']='SELL'
        with self.assertRaises(AssertionError):audit_trades(t,prepared)

if __name__=='__main__':unittest.main()
