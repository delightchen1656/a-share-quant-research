import unittest
import pandas as pd
from run_june2020_starts import ARCHIVE,module
from baseline_fixed_ioc import fixed_ioc_engine


class FilledSlotsTest(unittest.TestCase):
    def replay(self, specs, prices=None, volume=10000000, hold_days=30):
        core=fixed_ioc_engine(module('filled_slots_fixture',ARCHIVE/'research/run_batch.py'),filled_slots=True)
        dates=list(pd.bdate_range('2020-01-02',periods=8))
        signals=[];bars={}
        for i,(day,trigger_day,score) in enumerate(specs):
            symbol=f'{600000+i:06d}.SH'
            signals.append(dict(date=dates[day],symbol=symbol,factor='C04_NEW',close=10.,atr_pct=.05,score=score))
            rows=[]
            for k,d in enumerate(dates):
                opn=10.2 if k<trigger_day else 9.9
                high,low=opn+.01,opn-.01
                if prices and (i,k) in prices:opn,high,low=prices[i,k]
                rows.append(dict(date=d,open=opn,high=high,low=low,close=10.,preclose=10.,volume=volume,tradestatus=1))
            bars[symbol]=pd.DataFrame(rows).set_index('date')
        core.EVAL_START=dates[0];core.HARD_MAX_DATE=dates[-1];core.LAST_SIGNAL_DATE=dates[-1];core.YEARS=[2020]
        return core.simulate(pd.DataFrame(signals),bars,dates,'C04_NEW',0.,hold_days,'test',4.,1.5,
            keep_trades=True,slots=5,known_action_keys={s+'/2020' for s in bars})

    def test_quantity_has_no_slippage_buffer(self):
        r,_=self.replay([(0,1,1.)])
        self.assertEqual(r['fixed_order_attempts'][0]['requested_quantity'],2000)
        self.assertEqual(r['fixed_order_attempts'][0]['filled_quantity'],2000)

    def test_untriggered_pending_does_not_block_later_signal(self):
        r,_=self.replay([(0,7,1.)]*5+[(1,2,1.)])
        self.assertEqual(r['pending_orders_created'],6)
        self.assertEqual(r['fixed_order_attempts'][0]['symbol'],'600005.SH')

    def test_only_five_positive_fills_and_score_tiebreak(self):
        r,_=self.replay([(0,1,float(i)) for i in range(6)])
        a=r['fixed_order_attempts']
        self.assertEqual([x['symbol'] for x in a],[f'{i:06d}.SH' for i in range(600005,599999,-1)])
        self.assertEqual(sum(x['filled_quantity']>0 for x in a),5)
        self.assertEqual(a[-1]['status'],'no_slot_rejected')
        self.assertEqual(r['peak_occupied_slots_eod'],5)

    def test_open_trigger_precedes_unknown_intraday_trigger(self):
        r,_=self.replay([(0,1,9.),(0,1,1.)],prices={(0,1):(10.1,10.2,9.9)})
        self.assertEqual(r['fixed_order_attempts'][0]['symbol'],'600001.SH')

    def test_partial_fills_occupy_slots_zero_fills_do_not(self):
        r,_=self.replay([(0,1,1.)]*6,volume=50000)
        self.assertEqual(r['open_positions_at_end'],5)
        self.assertTrue(all(x['filled_quantity']==1000 for x in r['fixed_order_attempts'][:5]))
        r,_=self.replay([(0,1,1.)]*6,volume=1000)
        self.assertEqual(r['open_positions_at_end'],0)
        self.assertTrue(all(x['filled_quantity']==0 for x in r['fixed_order_attempts']))
        self.assertFalse(any(x['status']=='no_slot_rejected' for x in r['fixed_order_attempts']))

    def test_sold_slots_not_reused_using_unknown_intraday_future(self):
        specs=[(0,1,1.)]*5+[(1,2,1.)]
        prices={(i,2):(9.9,13.,9.8) for i in range(5)}
        r,t=self.replay(specs,prices=prices)
        self.assertEqual(len(t),5)
        self.assertEqual(r['fixed_order_attempts'][-1]['status'],'no_slot_rejected')


if __name__=='__main__':unittest.main()
