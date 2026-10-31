"""Package integrity; posterior files are opt-in and never read by default."""
import argparse,hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent
def main():
    p=argparse.ArgumentParser();p.add_argument('--include-holdout',action='store_true');args=p.parse_args()
    m=json.loads((HERE/'PACKAGE_MANIFEST.json').read_text(encoding='utf8'));n=0
    for info in m['files']:
        rel=Path(info['path'])
        if 'holdout_restricted' in rel.parts and not args.include_holdout:continue
        path=(HERE/rel).resolve();assert path.is_relative_to(HERE.resolve())
        assert hashlib.sha256(path.read_bytes()).hexdigest()==info['sha256'],str(rel);n+=1
    rule=json.loads((HERE/'RULE.json').read_text(encoding='utf8'))
    assert rule['direction']=='方向1' and rule['account']['slots']==5 and rule['account']['take_profit']==.08
    print('Direction1 package hashes passed:',n,'files; posterior opt-in:',args.include_holdout)
if __name__=='__main__':main()
