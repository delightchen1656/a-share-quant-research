"""Latest registered ATR025 price-TR fixed-IOC replay; legacy inputs stay frozen."""
import argparse
import inspect
from pathlib import Path
import sys
import replay_original_q1
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from signal_policy import MINIMUM_ATR, configuration,filter_frame


def registered_filter(signals):
    return filter_frame(signals)


def registered_runner():
    source=inspect.getsource(replay_original_q1.main)
    changes=[
        ("signals['atr_pct']=joined[args.atr_policy].to_numpy()",
         "signals['atr_pct']=joined[args.atr_policy].to_numpy()\n        signals=registered_filter(signals)"),
        ("fixed_ioc_atr_{args.atr_policy}_{group}","fixed_ioc_atr025_rollback_atr_{args.atr_policy}_{group}"),
        ("protocol['atr']=args.atr_policy","protocol['atr']=args.atr_policy\n        protocol['signal_filter']=configuration()")]
    for old,new in changes:
        assert source.count(old)==1,(old,source.count(old));source=source.replace(old,new)
    replay_original_q1.__dict__.update(MINIMUM_ATR=MINIMUM_ATR,configuration=configuration,registered_filter=registered_filter,__file__=__file__)
    exec(compile(source,'<selected_atr025_fixed_ioc>','exec'),replay_original_q1.__dict__)
    return replay_original_q1.main


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year',type=int,choices=[2020,2025,2026],default=2020)
    parser.add_argument('--june',action='store_true')
    args=parser.parse_args()
    panel=Path(__file__).resolve().parents[1]/'results/holdout_restricted/uniform_atr_inputs/attempt_20261020_051343/ATR_ALTERNATIVES.parquet'
    sys.argv=[str(Path(replay_original_q1.__file__)),'--fixed-ioc','--legacy-expiry-close',
              '--atr-policy','price','--atr-panel',str(panel),'--start-year',str(args.start_year)]
    if args.june:sys.argv.append('--june')
    registered_runner()()


if __name__=='__main__':main()
