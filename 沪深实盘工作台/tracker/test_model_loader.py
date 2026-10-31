import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import lightgbm as lgb
import numpy as np

import market
from model_loader import load_verified_model
from service import Tracker

class FrozenModelLoaderTest(unittest.TestCase):
    def setUp(self):
        self.root=Path(__file__).resolve().parents[1]
        self.manifest=json.loads((self.root/'model/manifest.json').read_text(encoding='utf-8'))
    def test_all_unicode_models_equal_original_native_ascii_path_predictions(self):
        rng=np.random.default_rng(171);x=rng.normal(size=(256,len(market.FEATURES)));x[::7,2]=np.nan
        for name in ('utility','pen025','pen100'):
            with self.subTest(model=name),tempfile.TemporaryDirectory(prefix='h2_model_') as tmp:
                original=self.root/'model'/f'{name}.txt';ascii_path=Path(tmp)/f'{name}.txt'
                ascii_path.write_bytes(original.read_bytes())
                self.assertTrue(str(ascii_path).isascii())
                native=lgb.Booster(model_file=str(ascii_path))
                actual=load_verified_model(original,self.manifest[name],market.FEATURES)
                np.testing.assert_array_equal(native.predict(x,num_threads=2),actual.predict(x,num_threads=2))
                self.assertEqual(native.num_trees(),actual.num_trees());self.assertEqual(native.feature_name(),actual.feature_name())
    def test_hash_failure_blocks_before_native_parser(self):
        with patch('lightgbm.Booster') as parser:
            with self.assertRaisesRegex(ValueError,'哈希不一致'):
                load_verified_model(self.root/'model/utility.txt','0'*64)
            parser.assert_not_called()
    def test_missing_or_invalid_manifest_and_feature_order_are_explicit(self):
        with self.assertRaisesRegex(ValueError,'哈希清单无效'):load_verified_model('missing.txt',None)
        with self.assertRaisesRegex(ValueError,'无法读取冻结模型'):load_verified_model('missing.txt','0'*64)
        with self.assertRaisesRegex(ValueError,'特征顺序不一致'):
            load_verified_model(self.root/'model/utility.txt',self.manifest['utility'],list(reversed(market.FEATURES)))
    def test_verified_bytes_pass_as_text_not_native_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'中文路径'/'模型.txt';path.parent.mkdir();payload=b'example model bytes';path.write_bytes(payload)
            with patch('lightgbm.Booster') as parser:
                load_verified_model(path,hashlib.sha256(payload).hexdigest())
                parser.assert_called_once_with(model_str='example model bytes')
    def test_failure_and_running_status_are_distinct_and_running_hides_old_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Tracker(tmp);t.info=dict(status='blocked',message='test error')
            self.assertEqual(t.calculation_state()['label'],'失败（已停止）')
            t.running=True;t.progress('冻结模型预测中')
            self.assertEqual(t.calculation_state()['code'],'running');self.assertEqual(t.calculation_state()['detail'],'冻结模型预测中')
            t.running=False
            self.assertEqual(t.calculation_state()['code'],'blocked')
    def test_running_never_presents_previous_signals_as_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Tracker(tmp)
            t.info=dict(status='ready',market_date='2026-10-26',signal_filter_policy=market.SIGNAL_FILTER_POLICY_ID,
                signals=[dict(id='old',symbol='600000.SH',signal_date='2026-10-26',rank=1,trigger=10,atr=.03)])
            t.ledger.confirm('2026-10-26',100000,100000)
            t.running=True;t.progress('冻结模型预测中')
            with patch.object(t,'cycle',return_value='2026-10-26'),patch.object(t,'sessions',return_value=['2026-10-26','2026-10-27']),patch('service.market.raw_marks',return_value={}):
                state=t.snapshot()
            self.assertFalse(state['market_ready']);self.assertEqual(state['signals'],[])
            self.assertEqual(state['calculation_status']['code'],'running')

if __name__=='__main__':unittest.main()
