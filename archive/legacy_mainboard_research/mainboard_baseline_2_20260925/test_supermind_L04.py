import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from monthly_A_signal_blend import blend_score,price_signals

HERE=Path(__file__).resolve().parent
sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
spec=importlib.util.spec_from_file_location('platform_l04',HERE/'supermind_mainboard_baseline_2_L04.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class L04(unittest.TestCase):
    def test_momentum_matches_local(self):
        c=pd.Series(np.exp(np.arange(400)*.003))
        self.assertAlmostEqual(m._momentum12_1(c),price_signals(c).mom12.iloc[-1])
        self.assertTrue(np.isnan(m._momentum12_1(c.iloc[:252])))
        y=c.copy();y.iloc[-21:]*=2
        self.assertEqual(m._momentum12_1(c),m._momentum12_1(y))

    def test_current_future_bars_removed(self):
        f=pd.DataFrame({'close':[1,2,3]},index=pd.to_datetime(['2026-09-23','2026-09-24','2026-09-25']))
        with patch.object(m,'get_datetime',lambda:pd.Timestamp('2026-09-24 09:00'),create=True):
            self.assertEqual(list(m._past_bars(f).close),[1])

    def test_real_cached_rank_parity_both_regimes(self):
        f=pd.read_parquet(HERE/'monthly_A_signal_refine_20260925/signals.parquet')
        dates=sorted(f.execute_date.unique())[::10]
        for date in dates:
            frame=f[f.execute_date==date].sort_values('symbol')
            for strong in (False,True):
                q=frame.copy()
                if not strong:q=q[q.float_cap_proxy_group==1].copy()
                q['score']=blend_score(q,strong,'mom12',.12)
                expected=q.dropna(subset=['score']).sort_values(['score','symbol'],ascending=[False,True])
                actual=m._rank_candidates(frame,strong)
                self.assertEqual(list(actual.symbol),list(expected.symbol))
                np.testing.assert_allclose(actual.score.to_numpy(),expected.score.to_numpy(),rtol=0,atol=1e-14)

    def test_unchanged_execution_functions(self):
        def funcs(path):
            return {n.name:ast.dump(n,include_attributes=False) for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n,ast.FunctionDef)}
        old=funcs(HERE/'supermind_mainboard_baseline_2_monthly_A.py');new=funcs(HERE/'supermind_mainboard_baseline_2_L04.py')
        for name in ('_load_universe','_is_ordinary_mainboard_a','_rank01','_dividend_quality','_group_features','_risk_weights','_is_first_session_of_month','before_trading','_trade_state'):
            self.assertEqual(old[name],new[name],name)

    def test_no_seventh_target(self):
        symbols=['600%03d.SH'%i for i in range(12)]
        frame=pd.DataFrame(dict(symbol=symbols,downside=[.01]*12,base_score=np.arange(12),mom12=[.1]*12,score=np.arange(12)))
        bars=pd.DataFrame({'close':np.arange(1,122,dtype=float)},index=pd.bdate_range('2025-01-01',periods=121))
        def history(batch,*args):return {s:bars for s in batch}
        context=types.SimpleNamespace(portfolio=types.SimpleNamespace(positions={s:object() for s in symbols[6:]}))
        with patch.object(m,'g',types.SimpleNamespace(universe=symbols),create=True),patch.object(m,'history',history,create=True),patch.object(m,'get_datetime',lambda:pd.Timestamp('2026-09-25'),create=True),patch.object(m,'log',types.SimpleNamespace(info=lambda *x:None,warn=lambda *x:None),create=True),patch.object(m,'_features',lambda *x:dict(downside=.01)),patch.object(m,'_group_features',lambda *x:dict(float_cap_proxy=1.,turn20=.1)),patch.object(m,'_rank_candidates',lambda *x:frame):
            targets=m._build_targets(context)
        self.assertEqual(set(targets),set(symbols[6:]))
        self.assertEqual(len(targets),6)
        self.assertAlmostEqual(sum(targets.values()),.8)

if __name__=='__main__':unittest.main()
