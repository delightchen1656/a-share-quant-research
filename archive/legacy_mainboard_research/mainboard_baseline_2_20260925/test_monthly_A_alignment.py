import unittest
import pandas as pd
import monthly_A_aligned_engine as e

class Actions(unittest.TestCase):
    def setUp(self):
        e.ACTION_MODE='ledger';e.ACTION_LEDGER={};e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[]
        self.date=pd.Timestamp('2024-06-03')
        self.day=pd.DataFrame([dict(symbol='A',date=self.date,preclose=9.,open=9.,close=9.)]).set_index('symbol')

    def tearDown(self):
        e.ACTION_MODE='legacy';e.ACTION_LEDGER={};e.RECEIVABLES=[];e.LOCKED_BONUS=[];e.UNRESOLVED_ACTIONS=[]

    def event(self,cash=1.,bonus=0.,delay=0):
        e.ACTION_LEDGER[(self.date,'A')]=dict(cash=cash,bonus=bonus,pay_date=self.date+pd.Timedelta(days=delay),stock_date=self.date+pd.Timedelta(days=1))

    def test_cash_dividend_does_not_create_shares(self):
        self.event();pos={'A':1000}
        cash=e.apply_corporate_action(0.,pos,self.day,{'A':10.})
        self.assertEqual(pos,{'A':1000});self.assertEqual(cash,1000.)

    def test_later_payment_is_receivable_not_spendable(self):
        self.event(delay=1);pos={'A':1000}
        self.assertEqual(e.apply_corporate_action(0.,pos,self.day,{'A':10.}),0.)
        self.assertEqual(e.receivable_value(),1000.)
        day=self.day.copy();day['date']=self.date+pd.Timedelta(days=1)
        self.assertEqual(e.apply_corporate_action(0.,pos,day,{'A':9.}),1000.)
        self.assertEqual(e.receivable_value(),0.)

    def test_bonus_from_record_only_and_locked(self):
        self.event(cash=0,bonus=.1);pos={'A':1000}
        e.apply_corporate_action(0.,pos,self.day,{'A':10.})
        self.assertEqual(pos['A'],1100);self.assertEqual(e.LOCKED_BONUS[0]['quantity'],100)

    def test_unknown_large_adjustment_not_invented(self):
        pos={'A':1000};cash=e.apply_corporate_action(0.,pos,self.day,{'A':10.})
        self.assertEqual(cash,0);self.assertEqual(pos['A'],1000);self.assertEqual(len(e.UNRESOLVED_ACTIONS),1)

if __name__=='__main__':unittest.main()
