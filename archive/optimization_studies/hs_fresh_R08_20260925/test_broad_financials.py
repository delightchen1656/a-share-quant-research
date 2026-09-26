import unittest
import pandas as pd
from prepare_broad_financials import align

class BroadFinancialTests(unittest.TestCase):
    def row(self,year,date,eitime=None,roe=10):
        return dict(REPORTDATE=str(year)+'-12-31',NOTICE_DATE=date,UPDATE_DATE=date,EITIME=eitime or date,
            WEIGHTAVG_ROE=roe,PARENT_NETPROFIT=20,TOTAL_OPERATE_INCOME=100,
            MGJYXJJE=3,BASIC_EPS=2,SJLTZ=5)
    def test_ingestion_lag_strict_and_future(self):
        row=self.row(2018,'2019-03-01','2019-04-29 11:13:42')
        dates=pd.to_datetime(['2019-04-29','2019-04-30','2020-01-01'])
        out=align([row],dates)
        self.assertTrue(pd.isna(out.fin_roe.iloc[0]));self.assertEqual(out.fin_roe.iloc[1],10)
        pd.testing.assert_frame_equal(out,align([row,self.row(2021,'2022-04-01',roe=90)],dates))
    def test_old_revision_cannot_replace_new_report(self):
        rows=[self.row(2018,'2020-05-01',roe=90),self.row(2019,'2020-04-01',roe=12)]
        out=align(rows,pd.to_datetime(['2020-04-02','2020-05-02']))
        self.assertEqual(out.fin_roe.tolist(),[12,12])
    def test_missing_and_stale(self):
        self.assertTrue(align([],pd.to_datetime(['2020-01-01'])).fin_roe.isna().all())
        self.assertTrue(align([self.row(2017,'2018-03-01')],pd.to_datetime(['2021-01-01'])).fin_roe.isna().all())
    def test_rank_order_and_missing_stock(self):
        import round17_broad_quality as m
        f=pd.DataFrame(dict(symbol=['600001.SH','600002.SH','600003.SH'],downside=[.01]*3,
            float_cap_proxy_group=[0,1,1],fin_roe=[None,10,20],fin_cash=[None,1,2],
            fin_margin=[None,10,20],vol60=[.01,.02,.03],turn20=[1,2,3],
            long_risk=[1,2,3],distribution_proxy=[.01,.02,.03]))
        self.assertEqual(len(m.CONFIGS),24)
        for cfg in m.CONFIGS:
            c=dict(cfg,buffer=60)
            a=m.rank(f,c);b=m.rank(f.iloc[::-1],c)
            pd.testing.assert_frame_equal(a.reset_index(drop=True),b.reset_index(drop=True))
            if c['size']=='all':self.assertEqual(len(a),3)

    def test_f10_missing_ingestion_is_explicit_not_fabricated(self):
        from prepare_complete_financials import convert
        row=dict(REPORT_DATE='2018-12-31',NOTICE_DATE='2019-03-01',UPDATE_DATE='2019-04-01',
            ROEJQ=12,PARENTNETPROFIT=20,TOTALOPERATEREVE=100,MGJYXJJE=3,EPSJB=2,PARENTNETPROFITTZ=5)
        converted=convert(row)
        self.assertIsNone(converted['EITIME'])
        out=align([converted],pd.to_datetime(['2019-04-01','2019-04-02']))
        self.assertTrue(pd.isna(out.fin_roe.iloc[0]));self.assertEqual(out.fin_roe.iloc[1],12)
        converted.pop('_source_schema')
        self.assertTrue(align([converted],pd.to_datetime(['2019-04-02'])).fin_roe.isna().all())

if __name__=='__main__':unittest.main()
