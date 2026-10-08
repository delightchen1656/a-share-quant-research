"""Reproduce the frozen daily review, using repository-local dependencies."""
from pathlib import Path
import hashlib,json,subprocess,sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    manifest=json.loads((HERE/'inputs.json').read_text(encoding='utf-8'))
    for row in manifest['files']:
        p=ROOT/'sh_sz_market_research/data_pipeline/data/raw'/row['symbol'][-2:]/(row['symbol']+'.parquet')
        if sha(p)!=row['sha256']:raise RuntimeError('Frozen market input changed: '+str(p))
    if sha(HERE/'uploaded_v5.py')!=manifest['source_sha256']:raise RuntimeError('Original strategy changed')
    if sha(HERE/'protocol.json')!=manifest['protocol_sha256']:raise RuntimeError('Frozen protocol changed')
    stages=[('build_daily.py',[]),('research.py',['prepare']),('research.py',['signals']),('backtest.py',['main']),
            ('backtest.py',['diagnostics']),('backtest.py',['equal_horizon']),('verify.py',[]),('statistics_report.py',[]),('report.py',[])]
    for name,args in stages:
        print('STAGE',name,*args,flush=True)
        subprocess.run([sys.executable,'-W','ignore::FutureWarning',str(HERE/name),*args],check=True)
    print('COMPLETED',HERE/'report.html')

if __name__=='__main__':main()
