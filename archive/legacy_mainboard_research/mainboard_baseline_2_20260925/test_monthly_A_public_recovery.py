import unittest
import pandas as pd
from monthly_A_public_recovery import action_map,reconstruct

class Recovery(unittest.TestCase):
    def test_two_reporting_periods_paid_together(self):
        base=dict(SECUCODE='600720.SH',EX_DIVIDEND_DATE='2024-06-13',BONUS_IT_RATIO=None)
        a=dict(base,REPORT_DATE='2022-12-31',PRETAX_BONUS_RMB=1.104)
        b=dict(base,REPORT_DATE='2023-12-31',PRETAX_BONUS_RMB=2.57)
        event=action_map([a,b,a])[('600720.SH',pd.Timestamp('2024-06-13'))]
        self.assertAlmostEqual(event['cash'],.3674)

    def test_conflicting_same_period_rejected(self):
        a=dict(SECUCODE='X',EX_DIVIDEND_DATE='2024-06-13',REPORT_DATE='2023-12-31',PRETAX_BONUS_RMB=1)
        with self.assertRaises(ValueError):action_map([a,dict(a,PRETAX_BONUS_RMB=2)])

    def test_price_continuity_on_cash_plus_bonus(self):
        raw=pd.DataFrame(dict(date=pd.to_datetime(['2024-06-12','2024-06-13']),open=[11.,9.],high=[11.,9.],low=[11.,9.],close=[11.,9.]))
        result=reconstruct(raw,[dict(date=pd.Timestamp('2024-06-13'),cash=.2,bonus=.2)])
        self.assertAlmostEqual(result.close.iloc[0],result.close.iloc[1])

if __name__=='__main__':unittest.main()
