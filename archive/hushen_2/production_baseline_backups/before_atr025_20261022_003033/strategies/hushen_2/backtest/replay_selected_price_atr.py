"""Selected uniform price-TR fixed-IOC replay; preserves historical replay entry points."""
import argparse
from pathlib import Path
import sys
import replay_original_q1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-year',type=int,choices=[2020,2025,2026],default=2020)
    parser.add_argument('--june',action='store_true')
    args=parser.parse_args()
    panel=Path(__file__).resolve().parents[1]/'results/holdout_restricted/uniform_atr_inputs/attempt_20261020_051343/ATR_ALTERNATIVES.parquet'
    sys.argv=[str(Path(replay_original_q1.__file__)),'--fixed-ioc','--legacy-expiry-close',
              '--atr-policy','price','--atr-panel',str(panel),'--start-year',str(args.start_year)]
    if args.june:sys.argv.append('--june')
    replay_original_q1.main()


if __name__=='__main__':main()
