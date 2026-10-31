import tempfile
import unittest
from unittest.mock import patch

from service import Tracker


class CalculationProgressTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.t=Tracker(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def position(self):
        self.t.ledger.append('accept',dict(signal_id='s',symbol='600000.SH',signal_date='2026-10-19',atr=.03,trigger=10.,quantity=700))
        self.t.ledger.append('buy',dict(order_id='s',date='2026-10-20',quantity=700,price=10.,fee=5.))
        self.t.ledger.append('protection',dict(symbol='600000.SH'))

    def test_linked_full_exit_does_not_create_cleanup(self):
        self.position()
        self.t.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-21',quantity=700,price=11.,fee=5.))
        state=self.t.ledger.state(asof='2026-10-22')
        self.assertEqual(state['positions'],[])
        self.assertEqual(state['pending_cleanups'],[])
        self.assertEqual(state['cash'],100690.)

    def test_partial_exit_still_requires_protection_for_remaining_shares(self):
        self.position()
        self.t.ledger.append('sell',dict(symbol='600000.SH',date='2026-10-21',quantity=200,price=11.,fee=5.))
        state=self.t.ledger.state(asof='2026-10-22')
        self.assertEqual(state['pending_cleanups'],[])
        self.assertEqual(state['positions'][0]['quantity'],500)
        self.assertFalse(state['positions'][0]['protection'])

    def test_progress_reports_phase_counters_and_elapsed_without_ledger_write(self):
        before=self.t.ledger.events()
        self.t.running=True
        self.t.update_clock=self.t.stage_clock=100.
        with patch('service.time.monotonic',return_value=110.):
            self.t.progress('feature files 500/3414')
        with patch('service.time.monotonic',return_value=120.):
            c=self.t.calculation_state()
        self.assertEqual(c['stage'],'features')
        self.assertEqual(c['stage_index'],2)
        self.assertEqual(c['elapsed_seconds'],20)
        self.assertEqual(c['stage_elapsed_seconds'],10)
        self.assertIn('500/3414',c['detail'])
        with patch('service.time.monotonic',return_value=130.):
            self.t.progress('冻结模型 utility 预测中 · 10,000条特征')
        self.assertEqual(self.t.calculation_state()['stage'],'models')
        self.assertEqual(self.t.ledger.events(),before)

    def test_stopped_elapsed_is_frozen_and_failure_stays_visible(self):
        self.t.update_clock=100.
        self.t.update_finished_clock=150.
        self.t.info=dict(status='blocked',message='fixture failure')
        with patch('service.time.monotonic',return_value=999.):
            c=self.t.calculation_state()
        self.assertEqual(c['elapsed_seconds'],50)
        self.assertEqual(c['code'],'blocked')
        self.assertEqual(c['detail'],'fixture failure')

    def test_actual_work_moves_inside_slow_stages_and_only_ready_reaches_100(self):
        self.t.running=True
        points=[]
        for message in ('feature files 20/100','feature files 80/100',
                        '历史特征合并与日期代码完整性核验',
                        '冻结模型 utility 预测中 · rows 0/100000',
                        '冻结模型 utility 预测中 · rows 50000/100000',
                        '冻结模型 utility 预测中 · rows 100000/100000',
                        '冻结模型 pen025 预测中 · rows 50000/100000',
                        '冻结模型 pen100 预测中 · rows 100000/100000',
                        '模型评分完成，计算历史横截面排名',
                        '按原冻结因子排序并筛选ATR≥2.5%',
                        '保存并校验当日冻结信号','发布次日推荐'):
            self.t.progress(message)
            points.append(self.t.calculation_state()['progress_percent'])
        self.assertEqual(points,sorted(points))
        self.assertLess(max(points),100)
        self.t.running=False;self.t.info={'status':'ready'}
        self.assertEqual(self.t.calculation_state()['progress_percent'],100)

    def test_native_model_batches_are_bitwise_equal_to_one_shot(self):
        import numpy as np
        import pandas as pd
        import market
        import json
        hashes=json.loads((market.BASE/'model/manifest.json').read_text(encoding='utf-8'))
        rng=np.random.default_rng(20261029)
        x=pd.DataFrame(rng.normal(size=(10003,len(market.FEATURES))),columns=market.FEATURES)
        x.iloc[::19,2]=np.nan
        for name in ('utility','pen025','pen100'):
            model=market.load_verified_model(market.BASE/'model'/f'{name}.txt',hashes[name],market.FEATURES)
            full=model.predict(x,num_threads=4)
            chunked=np.concatenate([model.predict(x.iloc[i:i+997],num_threads=4) for i in range(0,len(x),997)])
            np.testing.assert_array_equal(full,chunked)

    def test_remaining_estimate_requires_a_previous_full_run(self):
        self.t.running=True
        self.t.full_model_run=True
        self.t.update_clock=100.
        self.assertNotIn('estimated_remaining_seconds',self.t.calculation_state())
        self.t.last_calculation=dict(seconds=200)
        with patch('service.time.monotonic',return_value=160.):
            self.assertEqual(self.t.calculation_state()['estimated_remaining_seconds'],140)


if __name__=='__main__':
    unittest.main()
