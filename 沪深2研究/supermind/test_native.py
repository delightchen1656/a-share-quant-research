"""Native callback contract tests with synchronous SuperMind-like receipts."""
import importlib.util,json,sys,types,unittest
from pathlib import Path
from types import SimpleNamespace as N
import numpy as np
import pandas as pd
import lightgbm as lgb

BASE=Path(__file__).resolve().parents[1]


def namespace():
    ns={};source=(BASE/'supermind_hushen_2.py').read_text(encoding='utf-8').replace('from mindgo_api import *','')
    exec(compile(source,'<supermind-native-test>','exec'),ns)
    calendar=pd.bdate_range('2018-01-01','2025-04-30')
    ns.update(g=N(),get_trade_days=lambda **kwargs:calendar,
        set_benchmark=lambda *a:None,set_commission=lambda *a:None,PerShare=lambda **k:k,
        set_slippage=lambda *a:None,PriceSlippage=lambda *a:a,set_volume_limit=lambda **k:None,
        enable_open_bar=lambda:None,subscribe=lambda *a:None,log=N(info=lambda *a:None),record=lambda **k:None,
        get_datetime=lambda:pd.Timestamp('2020-01-02 09:30'))
    context=N(portfolio=N(positions={},stock_account=N(available_cash=100000.,frozen_cash=0.)))
    ns['init'](context);ns['before_trading'](context)
    return ns,context


class NativeTest(unittest.TestCase):
    def test_exported_models_equal_original_with_missing_values(self):
        n,c=namespace();rng=np.random.RandomState(27)
        for name,model in n['g'].models.items():
            x=rng.normal(size=(512,14));x[0,:]=np.nan;x[1,:]=0
            b=lgb.Booster(model_str=(BASE/'model'/f'{name}.txt').read_text(encoding='utf-8'))
            np.testing.assert_array_equal(n['predict_trees'](model,x),b.predict(x,num_threads=2))

    def test_synchronous_partial_fill_is_not_mistaken_for_full_fill(self):
        n,c=namespace();g=n['g'];cancelled=[]
        p=dict(signal_date='2020-01-02',atr=.03)
        def order(symbol,quantity,price):
            n['on_order'](c,N(order_id='one',symbol=symbol,status='PARTIALLY_FILLED'))
            trade=N(order_id='one',order_book_id=symbol,exec_id='fill1',last_quantity=300,last_price=10.,trading_datetime=pd.Timestamp('2020-01-03 10:00'))
            n['on_trade'](c,trade);n['on_trade'](c,trade)
            return 'one'
        n.update(order=order,get_orders=lambda oid:[N(amount=700,filled_amount=300)],cancel_order=lambda oid:cancelled.append(oid))
        n['submit_ioc']('600000.SH',700,'buy',p,10.02)
        self.assertEqual(cancelled,['one']);self.assertEqual(g.terms['600000.SH']['quantity'],300)
        self.assertAlmostEqual(g.terms['600000.SH']['take'],11.2)
        self.assertAlmostEqual(g.terms['600000.SH']['stop'],9.55)
        self.assertEqual(g.terms['600000.SH']['deadline'],'2020-02-02')

    def test_native_quantity_shrinking_fails_loudly(self):
        n,c=namespace();cancelled=[]
        n.update(order=lambda *a,**k:'one',get_orders=lambda oid:[N(amount=600,filled_amount=0)],cancel_order=lambda oid:cancelled.append(oid))
        with self.assertRaisesRegex(RuntimeError,'fixed quantity'):n['submit_ioc']('600000.SH',700,'buy',{},10)
        self.assertEqual(cancelled,['one'])

    def test_order_acceptance_does_not_create_position_terms(self):
        n,c=namespace();n.update(order=lambda *a,**k:'one',get_orders=lambda oid:[N(amount=700,filled_amount=0)],cancel_order=lambda oid:None)
        n['submit_ioc']('600000.SH',700,'buy',{},10)
        self.assertFalse(n['g'].terms)

    def test_cash_rejection_keeps_fixed_quantity_and_consumes_one_attempt(self):
        n,c=namespace();p=dict(symbol='600000.SH',quantity=700,target=10.,signal_date='2020-01-01',expiry='2020-01-08',atr=.03)
        n['g'].pending=[p];c.portfolio.stock_account.available_cash=6000
        n['order']=lambda *a,**k:self.fail('Must not submit cash-inadequate fixed order')
        bar=N(open=10.,high=10.,low=10.,close=10.,is_paused=False,high_limit=11.)
        n['handle_bar'](c,{'600000.SH':bar});self.assertEqual(n['g'].pending,[])
        self.assertEqual(p['quantity'],700)

    def test_tplus1_no_sell_and_stale_buy_not_recreated(self):
        n,c=namespace();g=n['g'];g.terms['600000.SH']=dict(entry_date='2020-01-02',quantity=100,take=11.,stop=9.)
        c.portfolio.positions['600000.SH']=N(amount=100,available_amount=100,last_price=8.)
        n['order']=lambda *a,**k:self.fail('T+1 sell forbidden')
        n['handle_bar'](c,{'600000.SH':N(open=8.,high=8.,low=8.,close=8.,is_paused=False)})
        g.pending=[dict(symbol='600001.SH',expiry='2020-01-01')]
        n['before_trading'](c);self.assertFalse(g.pending)

    def test_same_minute_double_touch_chooses_stop(self):
        n,c=namespace();g=n['g'];g.terms['600000.SH']=dict(entry_date='2020-01-01',quantity=100,take=11.,stop=9.,expiry_session='2020-01-31')
        c.portfolio.positions['600000.SH']=N(amount=100,available_amount=100,last_price=10.)
        calls=[];n['submit_ioc']=lambda *args:calls.append(args)
        n['handle_bar'](c,{'600000.SH':N(open=10.,high=12.,low=8.,close=10.,low_limit=8.,is_paused=False)})
        self.assertEqual(g.terms['600000.SH']['exit_reason'],'stop');self.assertEqual(len(calls),1)

    def test_daily_frequency_rejected_before_signal_history(self):
        n,c=namespace()
        with self.assertRaisesRegex(RuntimeError,'MINUTE'):n['after_trading'](c)

    def test_no_same_day_sale_cash_reuse(self):
        n,c=namespace();n['g'].sell_cash_today=10000;c.portfolio.stock_account.available_cash=12000
        self.assertEqual(n['available_cash'](c),2000)

    def test_platform_actual_start_can_be_later_than_configured_hint(self):
        n,c=namespace();n['init'](c)
        n['get_datetime']=lambda:pd.Timestamp('2020-01-07 09:00')
        n['before_trading'](c)
        self.assertEqual(n['g'].actual_start,'2020-01-07')
        c.portfolio.stock_account.available_cash=99000
        n['get_datetime']=lambda:pd.Timestamp('2020-01-08 09:00')
        n['before_trading'](c)
        self.assertEqual(n['g'].actual_start,'2020-01-07')

    def test_actual_start_before_supported_history_is_rejected(self):
        n,c=namespace();n['init'](c)
        n['get_datetime']=lambda:pd.Timestamp('2019-12-31 09:00')
        with self.assertRaisesRegex(RuntimeError,'outside supported'):n['before_trading'](c)


if __name__=='__main__':unittest.main()
