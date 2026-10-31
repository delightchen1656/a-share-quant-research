"""Freeze quotes and only shared corporate-action evidence, never other strategy outputs."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from study import SOURCE,ROOT,digest

OUT=ROOT/'results_v9_accounts'
ACTION_INPUT=ROOT.parent/'strategies/hushen/research/transfer_2016_2024/inputs_pre2025'
REPAIR=ACTION_INPUT.parent/'action_repair_20261024'


def main():
    OUT.mkdir(exist_ok=True)
    d=pd.read_parquet(ROOT/'results_v4_decline_first/events.parquet')
    d=d.loc[d.year.between(2021,2024)].copy()
    cal=pd.to_datetime(pd.read_parquet(SOURCE/'calendar.parquet').date).dt.strftime('%Y-%m-%d').tolist();p={a:i for i,a in enumerate(cal)}
    m=json.loads((SOURCE/'MANIFEST.json').read_text(encoding='utf8'));hs={x['relative_path'].replace('\\','/'):x['sha256'] for x in m['files']}
    evidence=[];need=[]
    for code,g in d.groupby('code'):
        frames=[]
        for mode in ['raw','qfq']:
            path=SOURCE/mode/(code+'.parquet');assert digest(path)==hs[f'{mode}/{code}.parquet']
            a=pd.read_parquet(path).sort_values('date').reset_index(drop=True);a['date']=pd.to_datetime(a.date).dt.strftime('%Y-%m-%d');frames.append(a)
        r,q=frames;assert r.date.equals(q.date)
        valid=(pd.to_numeric(r.tradestatus)==1)&(r.volume>0)&(r.open>0)
        r=r.loc[valid].set_index('date');q=q.loc[valid].set_index('date')
        factor=q.close/r.close
        ratio=factor/factor.shift(1);changed=ratio.sub(1).abs()>1e-7
        for _,e in g.iterrows():
            k=p[e.date];buy=cal[k+1];end=cal[k+6]
            # No peeking used to choose stocks: audit all candidate holding windows equally.
            for day in r.index[(r.index>buy)&(r.index<=end)&changed]:
                evidence.append(dict(code=code,signal_date=e.date,buy_date=buy,scheduled_end=end,date=day,factor_ratio=float(ratio.loc[day])))
    records={};source_hashes={}
    original=json.loads((ACTION_INPUT/'actions_pre2025.json').read_text(encoding='utf8'))
    public=json.loads((ACTION_INPUT/'PUBLIC_INPUT_MANIFEST.json').read_text(encoding='utf8'))
    assert digest(ACTION_INPUT/'actions_pre2025.json')==public['actions_sha256']
    repaired=json.loads((ACTION_INPUT/'actions_pre2025_repaired_20261024.json').read_text(encoding='utf8'))
    repair_manifest=json.loads((REPAIR/'REPAIR_MANIFEST.json').read_text(encoding='utf8'))
    assert digest(ACTION_INPUT/'actions_pre2025_repaired_20261024.json')==repair_manifest['output_sha256']
    for e in evidence:
        code=e['code'];symbol=code+('.SH' if code.startswith('6') else '.SZ');key=symbol+'/'+e['date'][:4]
        if key in repaired:records[key]=repaired[key]
        elif key in original:records[key]=original[key]
        else:need.append([symbol,int(e['date'][:4])])
    source_hashes['original']=public['actions_sha256'];source_hashes['repaired']=repair_manifest['output_sha256']
    (OUT/'action_crossings.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
    (OUT/'corporate_action_records.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    gaps=sorted(set(tuple(x) for x in need));(OUT/'action_gaps.json').write_text(json.dumps(gaps,indent=2),encoding='utf8')
    (OUT/'INPUT_AUDIT.json').write_text(json.dumps(dict(crossings=len(evidence),keys=len(records),gaps=len(gaps),source_hashes=source_hashes,
        audit='Only candidate buy-to-B5 windows audited by raw/adjusted factor changes. Does not assert lifetime/full-year company-action completeness.'),indent=2),encoding='utf8')
    print('factor crossings',len(evidence),'keys',len(records),'gaps',gaps)


if __name__=='__main__':main()
