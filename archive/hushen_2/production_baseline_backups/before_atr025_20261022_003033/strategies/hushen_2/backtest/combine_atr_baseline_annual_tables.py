"""Normalize the no-filter baseline table to the same benchmark as ATR025."""
import inspect
import combine_atr025_annual_tables as prior


def main():
    source=inspect.getsource(prior.main)
    changes=[('atr025_requested_tables','atr_baseline_requested_tables'),
        ('ATR>=2.5% on original daily top3','No ATR filter on original daily top3')]
    for old,new in changes:
        assert source.count(old)==1,(old,source.count(old));source=source.replace(old,new)
    exec(compile(source,'<combine_no_atr_filter_annual>','exec'),prior.__dict__)
    prior.main()


if __name__=='__main__':main()
