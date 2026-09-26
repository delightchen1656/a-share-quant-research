"""Verify the fast search ledger against execution boundaries and reference cash ledger."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import backtest as base
import explore_returns as explore
import adaptive_explore as adaptive


class SearchLedgerTests(unittest.TestCase):
    def test_rotation_uses_only_prior_history(self):
        dates=pd.bdate_range('2023-01-02','2024-12-31')
        count=len(dates)
        equity=np.column_stack([100000*np.exp(np.arange(count)*.001),
                                100000*np.exp(np.arange(count)*-.001)])
        positions=np.column_stack([np.ones(count,dtype=bool),np.zeros(count,dtype=bool)])
        params=dict(lookback=63,frequency='M',top_n=1,score='return')
        signal,audit=adaptive.rotate(dates,equity,positions,params)
        cutoff=np.flatnonzero(dates<=pd.Timestamp('2024-06-28'))[-1]
        changed=equity.copy()
        changed[cutoff+1:,1]=1e20
        changed_signal,_=adaptive.rotate(dates,changed,positions,params)
        np.testing.assert_array_equal(signal[:cutoff+1],changed_signal[:cutoff+1])
        self.assertTrue((pd.to_datetime(audit.history_end)<pd.to_datetime(audit.selection_date)).all())

    def test_rotation_can_choose_cash(self):
        dates=pd.bdate_range('2023-01-02','2024-12-31')
        equity=100000*np.exp(-np.arange(len(dates))[:,None]*.001)
        positions=np.ones_like(equity,dtype=bool)
        signal,_=adaptive.rotate(dates,equity,positions,dict(lookback=63,frequency='Q',top_n=3,score='return'))
        self.assertFalse(signal.any())

    def bars(self):
        dates=pd.bdate_range('2023-01-02','2023-03-31')
        raw=pd.DataFrame(dict(open=10.,high=10.,low=10.,close=10.,preclose=10.,
                              volume=1_000_000,tradestatus=1),index=dates)
        return raw,raw.copy()

    @patch.object(base,'events',return_value=[])
    def test_minimum_sessions_counts_from_actual_buy(self,_):
        raw,qfq=self.bars()
        data=explore.prepare(raw,qfq,'2023-01-03')
        entry=np.zeros((len(data['dates']),1),dtype=bool)
        entry[0]=True
        exits=np.ones_like(entry)
        _,_,_,trades=explore.simulate(data,entry,exits,[explore.policy('min21')],detail=True)
        sells=trades[trades.side.eq('SELL')]
        self.assertEqual(len(sells),1)
        self.assertEqual(sells.holding_sessions.iloc[0],21)

    @patch.object(base,'events',return_value=[])
    def test_stop_is_next_open_and_not_intraday(self,_):
        raw,qfq=self.bars()
        raw.loc[raw.index[3],'close']=8.5
        raw.loc[raw.index[3],'low']=8.5
        qfq=raw.copy()
        data=explore.prepare(raw,qfq,'2023-01-03')
        entry=np.zeros((len(data['dates']),1),dtype=bool)
        entry[0]=True
        exits=np.zeros_like(entry)
        _,_,_,trades=explore.simulate(data,entry,exits,[explore.policy('stop12_trail25')],detail=True)
        sells=trades[trades.side.eq('SELL')]
        self.assertEqual(sells.date.iloc[0],raw.index[4])
        self.assertAlmostEqual(sells.price.iloc[0],9.99)

    def test_reference_agreement_with_actual_dividends(self):
        raw,qfq,_=base.load_data()
        en=pd.Series(True,index=raw.index)
        en.loc[en.index<'2025-01-02']=False
        data=explore.prepare(raw,qfq,'2025-01-01')
        _,equity,_,_=explore.simulate(data,en.loc[data['dates']].to_numpy()[:,None],
                                     (~en).loc[data['dates']].to_numpy()[:,None],[explore.policy('free')])
        curve,_,_,_=base.simulate(raw,en.astype(int),'reference',start='2025-01-01')
        np.testing.assert_allclose(equity[:,0],curve.equity,atol=1e-6,rtol=0)

    @patch.object(base,'events',return_value=[])
    def test_no_sale_on_buy_day(self,_):
        raw,qfq=self.bars()
        data=explore.prepare(raw,qfq,'2023-01-03')
        entry=np.ones((len(data['dates']),1),dtype=bool)
        _,_,_,trades=explore.simulate(data,entry,entry,[explore.policy('free')],detail=True)
        self.assertTrue((trades.loc[trades.side.eq('SELL'),'holding_sessions']>=1).all())
        self.assertEqual(trades.date.value_counts().max(),1)


if __name__=='__main__':
    unittest.main()
