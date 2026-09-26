"""Offline research by default. Network recovery requires an explicit flag."""
import json
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent

def run(name,*args):
    print('PIPELINE',name,flush=True)
    subprocess.run([sys.executable,str(HERE/name),*args],check=True)

def main():
    if '--recover-history' not in sys.argv:
        assert (HERE/'monthly_A_alignment_20260924/action_ledger/manifest.json').exists()
        run('monthly_A_hundred_rounds.py','--existing-history')
        return
    run('monthly_A_public_recovery.py')
    for folder in ('warmup','action_ledger'):
        manifest=HERE/'monthly_A_alignment_20260924'/folder/'manifest.json'
        state=json.loads(manifest.read_text(encoding='utf-8'))
        assert not any('error' in r for r in state['results'])
    run('monthly_A_warm_factors.py')
    run('monthly_A_hundred_rounds.py')
    print('PIPELINE COMPLETE',flush=True)

if __name__=='__main__':main()
