from pathlib import Path
import ast,json,hashlib,importlib.util,sys,types,unittest
import numpy as np
import pandas as pd
from train import stock_features

HERE=Path(__file__).resolve().parent
SNAP=HERE.parent/'cutoff_20241130/snapshot'
sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
def load():
    p=HERE.parent/'supermind_test2_D11_fast_cutoff_20241130.py'
    spec=importlib.util.spec_from_file_location('d11_cutoff_export',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
class RevisionTests(unittest.TestCase):
    def test_dates_and_embargo(self):
        r=json.loads((HERE/'results.json').read_text());d=json.loads((HERE/'development_period_metrics.json').read_text())
        self.assertLess(r['maximum_observation_date'],'2024-11-30');self.assertLess(r['maximum_label_date'],'2024-11-30')
        for rows in d.values():
            for row in rows:self.assertLess(row['label_end'],'2023-01-01')
        for row in r['validation']:self.assertLess(row['label_end'],'2024-11-30')
        self.assertEqual(len(r['trials']),9)
    def test_original_and_fast_execution_unchanged(self):
        manifest=json.loads((HERE/'export_manifest.json').read_text())
        source=HERE.parent/'supermind_test2_D11_fast_daily.py'
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),manifest['source_sha256'])
        def funcs(p):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
        a=funcs(source);b=funcs(HERE.parent/manifest['entrypoint'])
        for k in a:
            if k!='compute_signals':self.assertEqual(a[k],b[k],k)
        m=load();self.assertEqual((m.INTERVAL,m.SMOOTH,m.COUNT,m.EXPOSURE),(20,5,5,.98))
    def test_future_observations_rejected(self):
        p=next(SNAP.glob('6*.parquet'));x=pd.read_parquet(p)
        x.loc[len(x)-1,'date']=pd.Timestamp('2024-12-02')
        with self.assertRaises(AssertionError):stock_features(x)
    def test_full_cross_section_export_parity(self):
        m=load();scores=pd.read_parquet(HERE/'selected_signal_scores.parquet');end=scores.index[-1]
        dates=pd.DatetimeIndex(pd.read_parquet(SNAP/'benchmark.parquet').date)
        dates=dates[dates<=end][-5:];raw={}
        for p in sorted(SNAP.glob('*.parquet')):
            if p.name=='benchmark.parquet':continue
            x=pd.read_parquet(p).set_index('date');x=x.loc[x.index<=end].tail(320)
            if x.empty:continue
            x=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
            x['is_paused']=1-pd.to_numeric(x.tradestatus)
            raw[p.stem]=x[m.FIELDS]
        members={d.strftime('%Y-%m-%d'):{s for s,x in raw.items() if d in x.index} for d in dates}
        ranked,_=m.compute_signals(raw,members,dates)
        expected=scores.loc[end].dropna().sort_values(ascending=False,kind='mergesort').index.tolist()[:100]
        self.assertEqual(ranked,expected)
        (HERE/'parity.json').write_text(json.dumps(dict(signal_date=str(end.date()),symbols=len(raw),top100_exact_match=True),indent=2),encoding='utf-8')
if __name__=='__main__':unittest.main()
