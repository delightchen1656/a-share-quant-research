import unittest
import numpy as np
import pandas as pd
from portfolio_open_v1 import Account,fees,cents
from run_exit_study import prepare_frame

class PortfolioChecks(unittest.TestCase):
    def market(self,changes=None,raw_override=None,q_override=None,periods=9):
        dates=pd.bdate_range('2019-01-02',periods=periods)
        r=pd.DataFrame(dict(date=dates,open=np.full(periods,10.),high=np.full(periods,10.1),low=np.full(periods,9.9),close=np.full(periods,10.)))
        for i,values in (changes or {}).items():r.loc[i,['open','high','low','close']]=values
        r['preclose']=r.close.shift().fillna(10);r['volume']=100000.;r['tradestatus']='1';r['isST']='0'
        for i,values in (raw_override or {}).items():
            for col,value in values.items():r.loc[i,col]=value
        q=r.copy()
        for i,values in (q_override or {}).items():
            for col,value in values.items():q.loc[i,col]=value
        return dates,prepare_frame(r,q,dates)
    def events(self,dates,items):
        return pd.DataFrame([dict(code=code,event_id=code+'_'+str(i),name=code,signal_date=str(dates[i].date())) for code,i in items])
    def account(self,dates,items,frames,actions=None):
        covered={(code,2019) for code in frames}
        return Account(dates,self.events(dates,items),frames,actions or [],covered).run(end=str(dates[-1].date()))
    def test_half_equity_two_slots_and_same_code(self):
        dates,f=self.market();frames={c:f.copy() for c in ['000001','000002','000003']}
        a=self.account(dates,[('000002',0),('000001',0),('000003',0),('000001',1)],frames)
        buys=[t for t in a.trades if t['side']=='buy'];self.assertEqual([t['code'] for t in buys],['000001','000002'])
        self.assertTrue(all(t['gross']+t['total']<=t['equity_before']*.5+.01 for t in buys))
        self.assertTrue(all(t['quantity']%100==0 for t in buys));self.assertEqual(max(r['positions'] for r in a.daily),2)
        self.assertIn('same_code_held',[r['reason'] for r in a.skips]);self.assertGreaterEqual(a.cash,0)
    def test_buy_day_stop_waits_until_next_day(self):
        dates,f=self.market({1:[10,10.1,9,9.8],2:[9.7,9.8,9.6,9.7]})
        a=self.account(dates,[('000001',0)],{'000001':f});sell=next(t for t in a.trades if t['side']=='sell')
        self.assertEqual(sell['date'],str(dates[2].date()));self.assertEqual(sell['price'],9.7)
        self.assertEqual(sell['reason'],'buy_day_stop_wait_tplus1')
    def test_intraday_cash_cannot_fund_previous_open(self):
        dates,normal=self.market();_,dip=self.market({2:[10,10.1,9.3,9.6]})
        frames={'000001':dip,'000002':normal.copy(),'000003':normal.copy()}
        a=self.account(dates,[('000001',0),('000002',0),('000003',1)],frames)
        self.assertFalse(any(t['side']=='buy' and t['code']=='000003' for t in a.trades))
        self.assertTrue(any(r.get('code')=='000003' and r['reason']=='two_positions_full_at_open' for r in a.skips))
    def test_limit_unlock_not_backdated_to_open(self):
        dates,normal=self.market();_,dip=self.market({2:[9,9.8,9,9.5]})
        frames={'000001':dip,'000002':normal.copy(),'000003':normal.copy()}
        a=self.account(dates,[('000001',0),('000002',0),('000003',1)],frames)
        sale=next(t for t in a.trades if t['side']=='sell' and t['code']=='000001')
        self.assertEqual(sale['phase'],'intraday');self.assertEqual(sale['price'],9)
        self.assertFalse(any(t['side']=='buy' and t['code']=='000003' for t in a.trades))
    def test_upper_limit_entry_skipped_without_using_unlock(self):
        dates,f=self.market({1:[11,11.1,10.7,10.9]})
        a=self.account(dates,[('000001',0)],{'000001':f})
        self.assertEqual(len(a.trades),0);self.assertEqual(a.skips[0]['reason'],'opening_at_upper_limit_no_fill_assumed')
    def test_profit_floor_uses_previous_high(self):
        dates,f=self.market({1:[10,13,9.9,12.5],2:[12.4,12.5,12,12.1]})
        a=self.account(dates,[('000001',0)],{'000001':f});sale=next(t for t in a.trades if t['side']=='sell')
        self.assertEqual(sale['date'],str(dates[2].date()));self.assertEqual(sale['price'],12.1)
    def test_dividend_receivable_and_cash_pay_date_are_separate(self):
        changes={i:[9.8,9.9,9.7,9.8] for i in range(3,9)}
        qfix={i:{'open':9.8,'high':9.9,'low':9.7,'close':9.8} for i in range(3)}
        dates,f=self.market(changes,raw_override={3:{'preclose':9.8}},q_override=qfix)
        action=dict(id='cash_test',code='000001',record=str(dates[2].date()),ex=str(dates[3].date()),pay=str(dates[5].date()),listed=None,cash=.2,bonus=0.,reserve=0.)
        a=self.account(dates,[('000001',0)],{'000001':f},[action]);q=a.history[0]['buy_shares'];gross=q*.2
        rows={r['date']:r for r in a.daily};before=rows[str(dates[2].date())];ex=rows[str(dates[3].date())];pay=rows[str(dates[5].date())]
        self.assertEqual(ex['cash'],before['cash']);self.assertAlmostEqual(ex['receivable_cash'],gross)
        self.assertAlmostEqual(pay['cash']-ex['cash'],gross);self.assertEqual(pay['receivable_cash'],0)
        self.assertAlmostEqual(ex['equity']-before['equity'],-gross*.2)
    def test_capitalization_waits_for_listing_and_oddlot_sale(self):
        changes={i:[6.67,6.7,6.6,6.67] for i in range(3,9)};changes[5]=[6,6.1,5.9,6]
        qfix={i:{'open':6.66666667,'high':6.73333334,'low':6.6,'close':6.66666667} for i in range(3)}
        dates,f=self.market(changes,raw_override={3:{'preclose':6.67}},q_override=qfix)
        action=dict(id='reserve_test',code='000001',record=str(dates[2].date()),ex=str(dates[3].date()),pay=None,listed=str(dates[4].date()),cash=0.,bonus=0.,reserve=.5)
        a=self.account(dates,[('000001',0)],{'000001':f},[action])
        listing=next(r for r in a.action_log if r['kind']=='new_shares_listed');self.assertEqual(listing['date'],str(dates[4].date()))
        sale=next(t for t in a.trades if t['side']=='sell');self.assertEqual(sale['quantity'],int(a.history[0]['buy_shares']*1.5))
    def test_historical_fee_changes_and_minimum_commission(self):
        self.assertEqual(fees(1000,'2019-01-02')['commission'],5)
        self.assertEqual(fees(100000,'2022-04-28')['transfer'],2)
        self.assertEqual(fees(100000,'2022-04-29')['transfer'],1)
        self.assertEqual(fees(100000,'2023-08-27',True)['stamp'],100)
        self.assertEqual(fees(100000,'2023-08-28',True)['stamp'],50)

if __name__=='__main__':unittest.main(verbosity=2)
