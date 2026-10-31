import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import market
from service import Tracker


class SignalPolicyTest(unittest.TestCase):
    def payloads(self,atrs):
        return [dict(id=f'2026-10-21_60000{i}.SH',symbol=f'60000{i}.SH',name=f'候选{i}',rank=i,
            signal_date='2026-10-21',valid_from='2026-10-22',trigger=10.,atr=a,score=.5-i*.01,size_proxy=18.,vol60=.03)
            for i,a in enumerate(atrs,1)]

    def test_inclusive_threshold_original_ranks_no_refill(self):
        raw=self.payloads([.02499999,.025,.05]);result=market.filter_signal_payloads(raw)
        self.assertEqual([s['rank'] for s in result],[2,3])
        self.assertEqual([s['rank'] for s in raw],[1,2,3])
        market.validate_signals(result,dict(market_date='2026-10-21',sessions=['2026-10-21','2026-10-22']))
        with self.assertRaises(ValueError):market.filter_signal_payloads(raw+[dict(raw[0],rank=4)])

    def test_empty_zero_and_frame_parity(self):
        self.assertEqual(market.filter_signal_payloads(self.payloads([.015,.02,.024])),[])
        rows=pd.DataFrame(dict(date=pd.to_datetime(['2026-10-21']*3),symbol=['a','b','c'],atr_pct=[.02,.025,.04],score=[3,2,1]))
        panel=rows[['date','symbol']].assign(f_log_amount=18.,f_turn=1.,vol60=.03)
        with patch('market.build_signals',return_value=rows) as build:
            selected=market.build_recommendations(panel)
        self.assertEqual(selected.symbol.tolist(),['b','c']);build.assert_called_once()
        with self.assertRaises(ValueError):market.filter_signal_frame(pd.concat([rows,rows.iloc[[0]]]).assign(size_proxy=18.,vol60=.03))

    def test_p12_inclusive_and_no_refill_missing_features_fail_closed(self):
        from signal_policy import MINIMUM_SIZE_PROXY,MINIMUM_VOL60
        raw=self.payloads([.03,.03,.03])
        raw[0].update(size_proxy=MINIMUM_SIZE_PROXY,vol60=MINIMUM_VOL60)
        raw[1]['size_proxy']=MINIMUM_SIZE_PROXY-1e-10
        raw[2]['vol60']=MINIMUM_VOL60-1e-10
        self.assertEqual([s['rank'] for s in market.filter_signal_payloads(raw)],[1])
        bad=dict(raw[0]);bad.pop('vol60')
        with self.assertRaises((KeyError,ValueError)):market.filter_signal_payloads([bad])
        with self.assertRaises(ValueError):market.validate_signals([bad],dict(market_date='2026-10-21',sessions=['2026-10-21','2026-10-22']))

    def test_old_cache_namespace_is_preserved(self):
        new=market.signal_cache_path('data','2026-10-21')
        self.assertIn(market.SIGNAL_FILTER_POLICY_ID,new.name)
        self.assertNotEqual(new,Path('data')/f'signals_2026-10-21_{market.EXECUTION_ATR_POLICY}.json')

    def test_legacy_accepted_order_and_cash_not_rewritten(self):
        clock=datetime(2026,10,21,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        sessions=['2026-10-21','2026-10-22','2026-11-20']
        with tempfile.TemporaryDirectory() as tmp:
            tracker=Tracker(tmp);old=self.payloads([.02])[0]
            tracker.ledger.append('accept',dict(signal_id=old['id'],symbol=old['symbol'],name=old['name'],signal_date=old['signal_date'],atr=.02,trigger=10.,quantity=100))
            tracker.info=dict(status='ready',market_date='2026-10-21',signals=[old],signal_filter_policy=market.SIGNAL_FILTER_POLICY_ID)
            with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=sessions):
                tracker.ledger.confirm('2026-10-21',100000,100000)
                before=tracker.ledger.events();snapshot=tracker.snapshot()
            self.assertEqual(snapshot['orders'][0]['atr'],.02)
            self.assertEqual(snapshot['signals'][0]['atr'],.02)
            self.assertEqual(snapshot['signals'][0]['status'],'accept')
            self.assertEqual(snapshot['cash'],100000)
            self.assertEqual(tracker.ledger.events(),before)

    def test_stale_policy_not_ready_and_new_low_atr_not_accepted(self):
        clock=datetime(2026,10,21,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        with tempfile.TemporaryDirectory() as tmp:
            tracker=Tracker(tmp);tracker.info=dict(status='ready',market_date='2026-10-21',signals=self.payloads([.02]))
            with patch('service.now',return_value=clock),patch('service.market.calendar_extended',return_value=['2026-10-21','2026-10-22']):
                tracker.ledger.confirm('2026-10-21',100000,100000)
                self.assertFalse(tracker.snapshot()['market_ready'])
                tracker.info['signal_filter_policy']=market.SIGNAL_FILTER_POLICY_ID
                self.assertEqual(tracker.snapshot()['signals'],[])
                with self.assertRaises(ValueError):tracker.action('accept',dict(signal_id=self.payloads([.02])[0]['id'],quantity=100))


if __name__=='__main__':unittest.main()
