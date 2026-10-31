"""Unfiltered baseline control; preserve audited ATR025 runner unchanged."""
import inspect
from pathlib import Path
import run_atr025_annual_post2024 as prior

FROZEN_INDEX=prior.BASE/'results/holdout_restricted/atr025_annual_post2024/attempt_20261022_001047/SSE_PRICE_INDEX.parquet'

def main():
    source=inspect.getsource(prior.main)
    replacements=[
        ('atr025_annual_post2024','atr_baseline_annual_post2024'),
        ("signals=signals.loc[signals.atr_pct.ge(.025)].copy()","signals=signals.loc[signals.atr_pct.ge(0.)].copy()"),
        ('threshold=.025','threshold=0.'),
        ("filter='Original top3 >=0.025 inclusive; no refill'","filter='Original top3, no ATR filter'"),
        ("if (out/'SSE_PRICE_INDEX.parquet').exists():index=pd.read_parquet(out/'SSE_PRICE_INDEX.parquet')","if True:index=pd.read_parquet(FROZEN_INDEX)"),
        ("OLD/'atr_ge_025/EQUITY_CURVES.parquet'","OLD/'original/EQUITY_CURVES.parquet'"),
    ]
    for old,new in replacements:
        assert old in source,old
        source=source.replace(old,new)
    prior.__dict__.update(FROZEN_INDEX=FROZEN_INDEX,__file__=__file__)
    exec(compile(source,'<audited_baseline_same_annual_loop>','exec'),prior.__dict__)
    prior.main()

if __name__=='__main__':main()
