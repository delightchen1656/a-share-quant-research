from pathlib import Path
import unittest, json, ast, hashlib, importlib.util,sys,types
import numpy as np
import pandas as pd
from train import features
HERE=Path(__file__).resolve().parent
sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
def load(path):
    spec=importlib.util.spec_from_file_location('exported_cutoff',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
class ExportTests(unittest.TestCase):
    def test_weights_and_frozen_source(self):
        man=json.loads((HERE/'export_manifest.json').read_text())
        self.assertEqual(hashlib.sha256((HERE.parent/'supermind_mainboard_baseline_1.py').read_bytes()).hexdigest(),man['source_sha256'])
        m=load(HERE.parent/man['entrypoint'])
        self.assertEqual([m.DISTRIBUTION_WEIGHT,m.MOMENTUM_WEIGHT,m.LOW_VOL_WEIGHT],man['weights'])
    def test_execution_unchanged(self):
        def nodes(p):return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(p.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
        a=nodes(HERE.parent/'supermind_mainboard_baseline_1.py');b=nodes(HERE.parent/'supermind_mainboard_baseline_1_cutoff_20241130.py')
        for name in ['past_bars','rebalance_due','select_affordable','trade_state','handle_bar','before_trading','after_trading']:
            self.assertEqual(a[name],b[name],name)
    def test_export_factor_parity(self):
        m=load(HERE.parent/'supermind_mainboard_baseline_1_cutoff_20241130.py')
        result=json.loads((HERE/'results.json').read_text())
        market=pd.read_parquet(HERE/'snapshot/benchmark.parquet').set_index('date').close
        for case in result['formula_parity_checks']:
            raw=pd.read_parquet(HERE/'snapshot'/(case['symbol']+'.parquet'));f,_,x=features(raw,market)
            d=pd.Timestamp(case['date'])
            r=x.loc[:d].tail(320).rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
            r['is_paused']=1-r.tradestatus
            actual=m.stock_features(r,r,market.loc[:d].tail(320))
            for k,v in actual.items():self.assertTrue(np.isclose(v,f.loc[d,k],rtol=1e-8,atol=1e-9),k)
    def test_export_ranking(self):
        m=load(HERE.parent/'supermind_mainboard_baseline_1_cutoff_20241130.py')
        x=pd.DataFrame(dict(symbol=['S%03d'%i for i in range(90)],float_cap_proxy=np.arange(90)+1,
            distribution_proxy=np.sin(np.arange(90)),long_risk=np.cos(np.arange(90)),vol60=np.arange(90)%11,
            market_adjusted=1.,ret5=1.,turn20=1.))
        groups=np.minimum(np.floor(x.float_cap_proxy.rank(pct=True)*3),2)
        e=x.loc[groups==1].copy();e['score']=.3*e.distribution_proxy.rank(pct=True)+.2*e.long_risk.rank(pct=True)+.5*(1-e.vol60.rank(pct=True))
        expected=e.sort_values(['score','symbol'],ascending=[False,True]).head(60)
        self.assertEqual(m.rank_candidates(x).symbol.tolist(),expected.symbol.tolist())
if __name__=='__main__':unittest.main()
