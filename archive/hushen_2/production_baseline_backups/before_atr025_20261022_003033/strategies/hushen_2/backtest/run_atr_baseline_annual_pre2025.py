"""Exact counterpart to ATR025 annual replay, removing only its ATR filter."""
import inspect
import run_atr025_annual_pre2025 as prior


def main():
    source=inspect.getsource(prior.main)
    replacements=[
        ("'results/holdout_restricted/atr025_annual_pre2025'","'results/holdout_restricted/atr_baseline_annual_pre2025'"),
        ("signals.atr_pct.ge(.025)","signals.atr_pct.ge(0.)"),
        ("threshold=.025","threshold=0."),
    ]
    for old,new in replacements:
        assert source.count(old)==1,(old,source.count(old))
        source=source.replace(old,new)
    prior.__dict__.update(__file__=__file__)
    exec(compile(source,'<annual_pre2025_no_atr_filter>','exec'),prior.__dict__)
    prior.main()


if __name__=='__main__':main()
