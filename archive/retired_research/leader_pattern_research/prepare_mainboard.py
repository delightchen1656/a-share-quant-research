"""Latest user scope: SH/SZ MAIN BOARD ONLY. Freeze existing verified quote paths."""
from pathlib import Path
import json,hashlib,shutil
import pandas as pd

HERE=Path(__file__).resolve().parent
SOURCE=HERE/'market_wide/holdout_restricted/v1'
OUT=HERE/'market_wide/holdout_restricted/mainboard_v1'
MAIN_REGEX=r'^(600|601|603|605|000|001|002|003)\d{3}$'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8');t.replace(p)
def main():
    if (OUT/'inputs_daily/manifest.json').exists():print('Verified main-board snapshot already prepared.');return
    OUT.mkdir(parents=True,exist_ok=True)
    u=pd.read_parquet(SOURCE/'universe.parquet');u=u[u.code.str.match(MAIN_REGEX)].copy();u['board']='主板'
    assert len(u)==3194 and int(u.is_leader.sum())==118
    u.to_parquet(OUT/'universe.parquet',index=False);shutil.copy2(SOURCE/'exchange_sessions.csv',OUT/'exchange_sessions.csv')
    frozen=HERE/'holdout_restricted/patterns_v1/inputs_daily'
    original=json.loads((frozen/'manifest.json').read_text(encoding='utf-8'))
    old={(r['code'],r['mode']):r for r in original['files']}
    records=[]
    for s in u.itertuples():
        for mode in ['raw','qfq']:
            if (s.code,mode) in old:
                r=old[(s.code,mode)];p=frozen/mode/f'{s.code}.parquet';assert sha(p)==r['snapshot_sha256']
                record=dict(code=s.code,mode=mode,path=str(p.resolve()),snapshot_sha256=sha(p),rows=r['rows'],source_type='Original_frozen_leader_mainboard')
            else:
                meta=SOURCE/'inputs_daily'/mode/f'{s.code}.json';r=json.loads(meta.read_text(encoding='utf-8'))
                p=Path(r['path']);assert r['ok'] and sha(p)==r['snapshot_sha256'];record=r
            records.append(record)
    assert len(records)==len(u)*2
    dump(OUT/'SCOPE.json',dict(user_scope='沪深主板，不含创业板、科创板、北交所',main_board_regex=MAIN_REGEX,
        stocks=len(u),leader_stocks=int(u.is_leader.sum()),original_leader_pool=185,
        first_scope_replaced=True,cutoff='2026-10-26',only_mainboard_will_be_matched_published_or_scheduled=True))
    dump(OUT/'inputs_daily/manifest.json',dict(cutoff='2026-10-26',stocks=len(u),required_stocks=len(u),
        scope='SH_SZ_MAIN_BOARD_ONLY',snapshots=len(records),files=records,all_protected_assets_readonly=True,universe_sha256=sha(OUT/'universe.parquet')))
    print('Main board only:',len(u),'stocks;',int(u.is_leader.sum()),'star-marked leaders;',len(records),'verified snapshots.')
if __name__=='__main__':main()
