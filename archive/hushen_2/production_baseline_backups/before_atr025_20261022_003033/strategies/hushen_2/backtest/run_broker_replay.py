"""Local broker-feasible daily replay entry. Defaults retain historical mixed ATR.

Example: python -B run_broker_replay.py --start-group q1_2025
No changes to production tracker, orders, registered old results or market inputs.
"""
import sys
from run_june2020_starts import main

if __name__=='__main__':
    sys.argv[1:1]=['--software-live','--mixed-atr','--broker-ioc']
    main()
