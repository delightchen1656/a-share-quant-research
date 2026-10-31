import unittest
import pandas as pd
from replay_hushen2_live_approx import engine


class LiveApproxTest(unittest.TestCase):
    def setUp(self):
        self.calendar=list(pd.bdate_range('2020-01-02','2020-04-30'))
        self.core=engine();self.core.EVAL_START=self.calendar[0];self.core.HARD_MAX_DATE=pd.Timestamp('2020-02-20')
        self.core.LAST_SIGNAL_DATE=self.core.HARD_MAX_DATE;self.core.YEARS=[2020]

    def bar(self,price=10):
        return pd.DataFrame(dict(open=price,high=price+.1,low=price-.1,close=price,preclose=price,volume=1e7,tradestatus=1),index=self.calendar)

    def simulate(self,signals,bars):
        return self.core.simulate(pd.DataFrame(signals),bars,self.calendar,'C04_NEW',0.,30,'x',4.,1.5,keep_trades=True,slots=5)

    def signal(self,symbol='600000.SH',date=None):
        return dict(symbol=symbol,date=date or self.calendar[0],close=10.,atr_pct=.03,score=1.,factor='C04_NEW')

    def test_fill_anchor_rounding_and_next_open_expiry(self):
        r,t=self.simulate([self.signal()],{'600000.SH':self.bar()})
        self.assertEqual(len(t),1)
        tr=t.iloc[0];self.assertEqual(tr.reason,'expiry')
        self.assertEqual(pd.Timestamp(tr.entry_date),pd.Timestamp('2020-01-03'))
        # D0 Jan3 +30 natural days is Sunday Feb2; Friday Jan31 retains position.
        self.assertEqual(pd.Timestamp(tr.exit_date),pd.Timestamp('2020-02-03'))

    def test_pending_has_fixed_quantity_and_cash_upper_bound(self):
        signals=[self.signal(f'60000{i}.SH') for i in range(5)]
        bars={s['symbol']:self.bar() for s in signals}
        r,t=self.simulate(signals,bars)
        self.assertEqual(r['peak_occupied_slots_eod'],5)
        self.assertEqual(len(r['fixed_order_attempts']),5)
        self.assertTrue(all(a['requested_quantity']==1900 for a in r['fixed_order_attempts']))
        self.assertTrue(all(a['filled_quantity']==1900 for a in r['fixed_order_attempts']))

    def test_no_terminal_blackout_or_forced_exit(self):
        r,t=self.simulate([self.signal(date=pd.Timestamp('2020-02-19'))],{'600000.SH':self.bar()})
        self.assertEqual(len(t),0)
        self.assertEqual(r['open_positions_at_end'],1)
        h=r['terminal_positions'][0]
        self.assertEqual(h['take_price'],round(h['entry_price']*1.12,2))
        self.assertEqual(h['stop_price'],round(h['entry_price']*.955,2))
        self.assertGreater(h['expiry_session'],self.core.HARD_MAX_DATE)


if __name__=='__main__':unittest.main()
