import contextlib
import io
import tempfile
import unittest
from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import engine


class AccountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.original=engine.OUT;engine.OUT=Path(self.temp.name)
        self.days=pd.bdate_range('2021-01-04',periods=12).strftime('%Y-%m-%d').tolist();self.ix={d:i for i,d in enumerate(self.days)}

    def tearDown(self):engine.OUT=self.original;self.temp.cleanup()

    def simulate(self,events=None,changes=None,actions=None,factors=None,missing=None,missing_force='defer',forced_day=5,stop_loss=None):
        if events is None:events=[dict(code='000001',name='test',date=self.days[0],is_leader=True)]
        d=pd.DataFrame(events);quotes={};fac={}
        for code in d.code.unique():
            quotes[code]={day:pd.Series(dict(open=10.,high=10.1,low=9.8,close=10.,preclose=10.)) for day in self.days}
            fac[code]={day:1. for day in self.days}
        if changes:
            for (code,day),vals in changes.items():
                for k,v in vals.items():quotes[code][day][k]=v
        if factors:fac.update(factors)
        for code,day in missing or []:del quotes[code][day]
        with contextlib.redirect_stdout(io.StringIO()):
            result=engine.run(d,{},self.days,self.ix,quotes,fac,actions or {},'sample',False,20000,1,missing_force=missing_force,forced_day=forced_day,stop_loss=stop_loss)
        folder=engine.OUT/result['key']
        return result,pd.read_parquet(folder/'trades.parquet'),pd.read_parquet(folder/'ledger.parquet'),pd.read_parquet(folder/'daily_nav.parquet')

    def test_lots_and_t1(self):
        change={('000001',self.days[1]):dict(high=11.),('000001',self.days[2]):dict(high=10.4)}
        r,t,l,n=self.simulate(changes=change)
        self.assertEqual(t.buy_qty.iloc[0],1900)
        self.assertEqual(t.buy_offset.iloc[0],1)
        self.assertAlmostEqual(t.iloc[0].sale_gross,1900*10.3)
        self.assertTrue((n.cash>=0).all())
        self.assertAlmostEqual(r['summary']['final_equity'],20000+t.pnl.sum())

    def test_force_exact_B5(self):
        r,t,_,_=self.simulate(changes={('000001',self.days[6]):dict(close=9.)})
        self.assertEqual(t.buy_offset.iloc[0],5)
        self.assertEqual(t.reason.iloc[0],'forced_B5_close')
        self.assertEqual(t.sale_gross.iloc[0],1900*9)

    def test_force_exact_B1(self):
        _,t,_,_=self.simulate(forced_day=1)
        self.assertEqual(t.buy_offset.iloc[0],1)
        self.assertEqual(t.reason.iloc[0],'forced_B1_close')

    def test_same_bar_stop_precedes_profit(self):
        _,t,_,_=self.simulate(stop_loss=.05,changes={('000001',self.days[2]):dict(high=10.5,low=9.4)})
        self.assertEqual(t.reason.iloc[0],'stop_loss_touch')
        self.assertAlmostEqual(t.sale_gross.iloc[0],1900*9.5)

    def test_gap_stop_at_open(self):
        _,t,_,_=self.simulate(stop_loss=.05,changes={('000001',self.days[2]):dict(open=9.3,high=9.4,low=9.2,close=9.3)})
        self.assertEqual(t.reason.iloc[0],'stop_loss_open')
        self.assertAlmostEqual(t.sale_gross.iloc[0],1900*9.3)

    def test_intraday_proceeds_not_available_at_open(self):
        events=[dict(code='000001',name='a',date=self.days[0],is_leader=True),dict(code='000002',name='b',date=self.days[1],is_leader=True)]
        r,t,_,_=self.simulate(events=events,changes={('000001',self.days[2]):dict(high=10.4)})
        self.assertEqual(r['summary']['trades'],1)
        self.assertEqual(r['summary']['skipped_slots'],1)

    def test_cash_dividend_pay_after_sale(self):
        ex=self.days[2];pay=self.days[4]
        changes={('000001',day):dict(open=9.,high=9.1,low=8.9,close=9.,preclose=9.) for day in self.days[2:]}
        changes[('000001',ex)]['high']=9.31
        factors={'000001':{day:(10/9 if day>=ex else 1.) for day in self.days}}
        actions={('000001',ex):dict(cash=1.,stock=0.,taxable_stock=0.,pay=pay,release=ex,reference_error=0.)}
        r,t,l,n=self.simulate(changes=changes,actions=actions,factors=factors)
        self.assertEqual(t.buy_offset.iloc[0],1)
        self.assertEqual(t.dividend_net.iloc[0],1520.)
        self.assertEqual(n.loc[n.date==ex,'receivable'].iloc[0],1520.)
        self.assertEqual(n.loc[n.date==pay,'receivable'].iloc[0],0.)
        self.assertAlmostEqual(r['summary']['final_equity'],20000+t.pnl.sum())

    def test_bonus_not_sold_before_listing(self):
        ex=self.days[2];release=self.days[3]
        changes={('000001',day):dict(open=6.67,high=6.9,low=6.5,close=6.67,preclose=6.67) for day in self.days[2:]}
        factors={'000001':{day:(1.5 if day>=ex else 1.) for day in self.days}}
        actions={('000001',ex):dict(cash=0.,stock=.5,taxable_stock=0.,pay=ex,release=release,reference_error=0.)}
        _,t,l,_=self.simulate(changes=changes,actions=actions,factors=factors)
        self.assertEqual(t.sell_date.iloc[0],release)
        self.assertEqual(l.loc[l.kind=='sell','qty'].iloc[0],2850)

    def test_missing_close_proxy_does_not_release_opening_slot(self):
        events=[dict(code='000001',name='a',date=self.days[0],is_leader=True),dict(code='000002',name='b',date=self.days[5],is_leader=True)]
        r,t,_,_=self.simulate(events=events,missing=[('000001',self.days[6])],missing_force='last_close')
        self.assertEqual(r['summary']['trades'],1)
        self.assertEqual(r['summary']['skipped_slots'],1)
        self.assertEqual(t.buy_offset.iloc[0],5)
        self.assertEqual(t.reason.iloc[0],'forced_B5_last_close_proxy')


if __name__=='__main__':unittest.main()
