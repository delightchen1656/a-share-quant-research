import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import market
from service import Tracker
from verify_pipeline import original_function,ARCHIVE

class PipelineTest(unittest.TestCase):
    def test_original_stock_feature_and_eligibility_intersection(self):
        rng=np.random.default_rng(71);n=500
        close=10*np.exp(np.cumsum(rng.normal(0,.01,n)))
        b=pd.DataFrame({'date':pd.bdate_range('2019-01-01',periods=n),'symbol':'600000.SH',
                        'open':close*.998,'high':close*1.02,'low':close*.98,'close':close,
                        'preclose':np.r_[close[0],close[:-1]],'volume':10_000_000,'amount':60e6,
                        'turn':2.,'tradestatus':1,'isST':0})
        b.loc[300:303,'tradestatus']=0;b.loc[340:345,'isST']=1;b.loc[370,'turn']=np.nan
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'qfq/SH').mkdir(parents=True);(root/'cache').mkdir()
            b.to_parquet(root/'qfq/SH/600000.SH.parquet',index=False)
            core=SimpleNamespace(FEATURE_START=pd.Timestamp('2018-01-01'),HARD_MAX_DATE=b.date.max(),EVAL_START=pd.Timestamp('2020-01-01'),LAST_SIGNAL_DATE=b.date.max())
            g={'np':np,'pd':pd,'CACHE':root/'cache','QFQ_ROOT':root/'qfq','core':core,'MODEL_FEATURES':market.FEATURES,
               'FEATURE_START':core.FEATURE_START,'HARD_MAX_DATE':core.HARD_MAX_DATE,'EVAL_START':core.EVAL_START,'LAST_SIGNAL_DATE':core.LAST_SIGNAL_DATE,
               'numeric':lambda x:pd.to_numeric(x,errors='coerce'),
               'FEATURE_COLUMNS':['vol60','overnight20','intraday20','turn20','mom60','mom20','vol20','ret5','mom120','close_to_high60']}
            m=original_function(ARCHIVE/'run_batch_002.py','build_model_panel',g)()
            t=original_function(ARCHIVE/'run_batch.py','build_feature_panel',g)()
            ref=m.merge(t[['date','symbol','overnight20','intraday20','turn20','mom60','vol20','ret5']],on=['date','symbol'],validate='one_to_one')
            ref['atr_pct']=t.set_index(['date','symbol']).atr_pct.reindex(pd.MultiIndex.from_frame(ref[['date','symbol']])).to_numpy()
            actual=market.model_features(b).reset_index(drop=True)
            self.assertTrue(ref[['date','symbol']].equals(actual[['date','symbol']]))
            for col in ref.columns:
                if col in ('date','symbol'):continue
                np.testing.assert_allclose(ref[col],actual[col],rtol=0,atol=1e-12,err_msg=col)

    def test_health_rejects_running_updater_and_committed_staging(self):
        with patch('market._updater_running',return_value=True):
            with self.assertRaisesRegex(ValueError,'更新进程'):market.health('.')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);run=root/'data_updates/20261019';run.mkdir(parents=True)
            (run/'audit.json').write_text(json.dumps({'status':'ok','target':'2026-10-19'}))
            (run/'staging').mkdir()
            with patch('market.ROOT',root),patch('market._updater_running',return_value=False):
                with self.assertRaisesRegex(ValueError,'暂存事务'):market.health(tmp)

    def test_hash_tamper_is_blocked(self):
        frame=pd.DataFrame({k:[0.] for k in market.FEATURES})
        with patch('market.digest',return_value='tampered'):
            with self.assertRaisesRegex(ValueError,'哈希不一致'):market.score_panel(frame)

    def test_signal_payload_checks(self):
        h={'market_date':'2026-10-19','sessions':['2026-10-19','2026-10-20']}
        s=dict(id='2026-10-19_600000.SH',symbol='600000.SH',signal_date='2026-10-19',valid_from='2026-10-20',rank=1,trigger=10.,atr=.03,score=.4)
        market.validate_signals([s],h)
        with self.assertRaises(ValueError):market.validate_signals([dict(s,valid_from='2026-10-21')],h)
        with self.assertRaises(ValueError):market.validate_signals([dict(s,trigger=float('nan'))],h)
        with self.assertRaises(ValueError):market.validate_signals([s,dict(s,rank=2)],h)
        self.assertNotEqual(market.signals_digest([s]),market.signals_digest([dict(s,score=.3)]))

    def test_incomplete_active_market_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);(data/'qfq/SH').mkdir(parents=True);(data/'metadata').mkdir()
            pd.DataFrame([dict(symbol='600000.SH',status='1')]).to_csv(data/'metadata/historical_mainboard_universe.csv',index=False)
            pd.DataFrame([dict(date=pd.Timestamp('2026-10-16'),symbol='600000.SH')]).to_parquet(data/'qfq/SH/600000.SH.parquet',index=False)
            with patch('market.DATA',data):
                with self.assertRaisesRegex(ValueError,'活跃证券缺少'):market.feature_panel('2026-10-19')

    def test_cache_freeze_reuse_and_stale_cache_failure(self):
        clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        h={'market_date':'2026-10-19','audit':'test','sessions':['2026-10-19','2026-10-20']}
        signals=[dict(id='2026-10-19_600000.SH',symbol='600000.SH',signal_date='2026-10-19',valid_from='2026-10-20',trigger=10.,atr=.03,score=.4,rank=1,name='示例')]
        with tempfile.TemporaryDirectory() as tmp:
            tracker=Tracker(tmp)
            with patch('service.now',return_value=clock),patch('service.market.refresh_calendar'),patch('service.market.health',return_value=h),patch('service.market.pipeline_identity',return_value=('abc',{})),patch('service.market.predict',return_value=signals) as prediction:
                tracker.update(background=False)
                self.assertEqual(tracker.info['status'],'ready')
                tracker.update(background=False)
                self.assertEqual(prediction.call_count,1)
                self.assertEqual(tracker.ledger.events(),[])
            with patch('service.now',return_value=clock),patch('service.market.refresh_calendar'),patch('service.market.health',return_value=h),patch('service.market.pipeline_identity',return_value=('changed',{})),patch('service.market.predict') as prediction:
                tracker.update(background=False)
                self.assertEqual(tracker.info['status'],'blocked');prediction.assert_not_called()
                self.assertEqual(json.loads(market.signal_cache_path(tmp,'2026-10-19').read_text(encoding='utf-8'))['pipeline_id'],'abc')

if __name__=='__main__':unittest.main()
