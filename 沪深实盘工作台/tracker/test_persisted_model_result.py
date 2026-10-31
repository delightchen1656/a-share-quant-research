import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import market
from service import Tracker,save_model_result


class PersistedModelResultTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.clock=datetime(2026,10,19,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.h={'market_date':'2026-10-19','audit':'test','sessions':['2026-10-19','2026-10-20']}
        self.signals=[dict(id='2026-10-19_600000.SH',symbol='600000.SH',signal_date='2026-10-19',
                           valid_from='2026-10-20',trigger=10.,atr=.03,score=.4,rank=1,name='示例')]
        self.stack=ExitStack()
        for target,kwargs in [('service.now',{'return_value':self.clock}),
                              ('service.market.refresh_calendar',{}),
                              ('service.market.health',{'side_effect':lambda _:self.h}),
                              ('service.market.pipeline_identity',{'return_value':('verified_inputs',{})})]:
            self.stack.enter_context(patch(target,**kwargs))
        self.prediction=self.stack.enter_context(patch('service.market.predict',return_value=self.signals))
        self.tracker=Tracker(self.folder)
        self.tracker.ledger.confirm('2026-10-19',100000,100000)

    def tearDown(self):self.stack.close();self.temp.cleanup()

    def test_restart_reads_fixed_file_even_without_daily_file(self):
        self.tracker.update(background=False)
        self.assertEqual(self.tracker.info['status'],'ready')
        cache=self.folder/'latest_model_result.json'
        self.assertEqual(json.loads(cache.read_text(encoding='utf-8'))['signals'],self.signals)
        market.signal_cache_path(self.folder,'2026-10-19').unlink()
        reopened=Tracker(self.folder)
        reopened.update(background=False)
        self.assertEqual(reopened.info['status'],'ready')
        self.assertTrue(reopened.cache_reused)
        self.assertFalse(reopened.full_model_run)
        self.assertEqual(self.prediction.call_count,1)
        self.assertEqual(reopened.ledger.events(),[])

    def test_completed_model_survives_account_gate_changing_during_run(self):
        review=self.tracker.ledger.confirmation('2026-10-19')
        with patch.object(self.tracker,'snapshot',return_value=dict(revision=0,equity=100000,cash=100000,deferred=0)),patch.object(self.tracker.ledger,'confirmation',side_effect=[review,None]):
            self.tracker.update(background=False)
        self.assertEqual(self.tracker.info['status'],'blocked')
        self.assertTrue((self.folder/'latest_model_result.json').exists())
        reopened=Tracker(self.folder);reopened.update(background=False)
        self.assertEqual(reopened.info['status'],'ready')
        self.assertEqual(self.prediction.call_count,1)

    def test_new_market_date_computes_once_and_replaces_fixed_file(self):
        self.tracker.update(background=False)
        self.clock=datetime(2026,10,20,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.stack.enter_context(patch('service.now',return_value=self.clock))
        self.h={'market_date':'2026-10-20','audit':'test2','sessions':['2026-10-20','2026-10-21']}
        self.tracker.ledger.confirm('2026-10-20',100000,100000)
        self.prediction.return_value=[]
        self.tracker.update(background=False)
        self.assertEqual(self.tracker.info['status'],'ready')
        self.assertEqual(self.prediction.call_count,2)
        self.assertEqual(json.loads((self.folder/'latest_model_result.json').read_text(encoding='utf-8'))['market_date'],'2026-10-20')

    def test_interrupted_atomic_publish_preserves_previous_result(self):
        path=self.folder/'latest_model_result.json';save_model_result(path,{'old':True})
        with patch('service.os.replace',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):save_model_result(path,{'new':True})
        self.assertEqual(json.loads(path.read_text()),{'old':True})
        self.assertEqual(list(self.folder.glob('*.tmp')),[])


if __name__=='__main__':unittest.main()
