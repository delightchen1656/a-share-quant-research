"""Artifact integrity and saved fidelity checks (no production or broker writes)."""
import hashlib
import json
from pathlib import Path
import unittest
import lightgbm as lgb
import pandas as pd

HERE=Path(__file__).resolve().parent

class ReconstructionTests(unittest.TestCase):
    def test_models_match_artifact_manifest(self):
        report=json.loads((HERE/'behavioral_v1/REPORT.json').read_text(encoding='utf-8'))
        protocol=json.loads((HERE/'behavioral_v1/PROTOCOL.json').read_text(encoding='utf-8'))
        for name,expected in report['models'].items():
            path=HERE/'behavioral_v1'/f'{name}.txt'
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),expected)
            model=lgb.Booster(model_file=str(path))
            self.assertEqual(model.feature_name(),protocol['features'])
            self.assertEqual(model.num_trees(),500)

    def test_saved_signal_fidelity(self):
        folder=HERE/'behavioral_v1'
        teacher=pd.read_csv(folder/'teacher_signals_pre2025.csv',parse_dates=['date'])
        shadow=pd.read_csv(folder/'reconstructed_signals_pre2025.csv',parse_dates=['date'])
        metrics=pd.read_csv(folder/'SIGNAL_FIDELITY.csv')
        for frame in (teacher,shadow):
            self.assertLess(frame.date.max(),pd.Timestamp('2025-01-01'))
            self.assertFalse(frame.duplicated(['date','symbol']).any())
            self.assertTrue(frame.groupby('date').size().eq(3).all())
        for row in metrics.itertuples():
            a=teacher[teacher.date.dt.year.eq(row.year)]
            b=shadow[shadow.date.dt.year.eq(row.year)]
            common=a.merge(b,on=['date','symbol'])
            self.assertAlmostEqual(len(common)/len(a),row.top3_overlap)
        self.assertEqual(set(metrics.year),{2020,2021,2022,2023,2024})

if __name__=='__main__': unittest.main()
