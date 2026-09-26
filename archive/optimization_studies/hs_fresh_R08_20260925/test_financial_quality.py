import unittest
import pandas as pd
import round16_financial_quality as m

class FinancialQualityTests(unittest.TestCase):
    def sample(self,year,notice,update,roe):
        return dict(REPORT_DATE=str(year)+'-12-31',NOTICE_DATE=notice,UPDATE_DATE=update,
            ROEJQ=roe,XSJLL=20,PARENTNETPROFITTZ=10,EPSJB=2,MGJYXJJE=3)
    def test_late_revision_and_strict_date(self):
        rows=[self.sample(2018,'2019-03-23','2020-03-21',16)]
        dates=pd.to_datetime(['2020-03-20','2020-03-21','2020-03-22'])
        z=m.point_in_time(rows,dates)
        self.assertTrue(z.fin_roe.iloc[:2].isna().all())
        self.assertEqual(z.fin_roe.iloc[2],16)
    def test_future_record_and_missing_dates(self):
        old=self.sample(2018,'2019-03-23','2019-03-23',15)
        future=self.sample(2019,'2020-03-21','2021-03-20',90)
        missing=self.sample(2019,'2020-03-21',None,99)
        dates=pd.date_range('2020-01-01',periods=8)
        pd.testing.assert_frame_equal(m.point_in_time([old],dates),m.point_in_time([old,future,missing],dates))
    def test_missing_stock_retained(self):
        f=pd.DataFrame(dict(symbol=['600001.SH','600002.SH'],downside=[.01,.01],
            vol60=[.01,.02],long_risk=[1,2],fin_roe=[None,10],fin_margin=[None,20],
            fin_growth=[None,5],fin_cash=[None,1]))
        for family in {x['family'] for x in m.CONFIGS}:
            self.assertEqual(len(m.rank(f,dict(family=family,buffer=60))),2)
        self.assertEqual(len(m.CONFIGS),16)

if __name__=='__main__':unittest.main()
