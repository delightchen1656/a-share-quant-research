"""Freeze action responses for all issuer-years with possible basic signals.

No future outcomes, candidate returns or posterior files are used in this plan.
"""
from pathlib import Path
import json,hashlib
import pandas as pd
import baostock as bs
import structure

HERE=Path(__file__).resolve().parent
AREA=HERE/'inputs_pre2025'
OUT=AREA/'research_action_responses'
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    original=json.loads((AREA/'MANIFEST.json').read_text(encoding='utf8'))
    lookup={(x['code'],x['mode']):x for x in original['files']}
    u=pd.read_parquet(AREA/'universe.parquet')
    plan=set()
    for index,stock in enumerate(u.itertuples(),1):
        frames=[]
        for mode in ['raw','qfq']:
            info=lookup[(stock.code,mode)];p=HERE/info['path'];assert sha(p)==info['sha256']
            z=pd.read_parquet(p).sort_values('date').reset_index(drop=True);z['date']=pd.to_datetime(z.date).dt.strftime('%Y-%m-%d');frames.append(z)
        r,q=frames;f,_,_=structure.scan(q,r)
        for day in f.loc[f.candidate,'date']:
            year=int(day[:4])
            if 2020<=year<=2024:
                plan.add((stock.code,year))
                if day[5:7] in ['11','12'] and year<2024:plan.add((stock.code,year+1))
        if index%300==0:print('Action query planning',index,'/',len(u),flush=True)
    dump(OUT/'QUERY_PLAN.json',dict(years=[2020,2021,2022,2023,2024],scope='Every stock-year containing any basic signal before cooldown/filters, plus following year for November/December signals. No future labels used.',keys=sorted(plan)))
    merged={};files=[]
    login=bs.login();assert login.error_code=='0',login.error_msg
    try:
        for i,(code,year) in enumerate(sorted(plan),1):
            key=code+('.SH' if code.startswith('6') else '.SZ')+'/'+str(year)
            early=AREA/'action_responses_2020'/(code+'.json')
            p=early if year==2020 and early.exists() else OUT/(code+'_'+str(year)+'.json')
            if p.exists():obj=json.loads(p.read_text(encoding='utf8'))
            else:
                rs=bs.query_dividend_data(('sh.' if code.startswith('6') else 'sz.')+code,year=str(year),yearType='operate')
                assert rs.error_code=='0',(key,rs.error_msg)
                rows=[]
                while rs.next():rows.append(dict(zip(rs.fields,rs.get_row_data())))
                obj=dict(key=key,error_code=rs.error_code,records=rows);dump(p,obj)
            assert obj['key']==key and obj['error_code']=='0'
            for row in obj['records']:
                assert row.get('dividOperateDate','').startswith(str(year)+'-')
                for field,value in row.items():
                    if field.endswith('Date') and value:assert value<='2024-12-31',(key,field,value)
            merged[key]=obj['records'];files.append(dict(path=p.relative_to(AREA).as_posix(),sha256=sha(p),key=key))
            if i%100==0:print('Research issuer-year action evidence',i,'/',len(plan),flush=True)
    finally:bs.logout()
    target=AREA/'company_actions_research_2020_2024.json';dump(target,merged)
    whitelist=[AREA/'calendar.parquet',AREA/'universe.parquet',target,OUT/'QUERY_PLAN.json']
    whitelist+=[HERE/x['path'] for x in original['files']]
    whitelist+=[AREA/x['path'] for x in files]
    manifest=dict(complete=True,cutoff='2024-12-31',quote_source_manifest_sha256=sha(AREA/'MANIFEST.json'),
        coverage_issuer_years=len(plan),provider_records=sum(len(x) for x in merged.values()),responses=files,
        company_actions_file=target.relative_to(AREA).as_posix(),
        files=[dict(path=p.relative_to(AREA).as_posix(),sha256=sha(p)) for p in whitelist],
        limitation='Provider evidence for planned issuer-years, not an exchange-certified exhaustive corporate-action database. Later independent entry/holding reference-factor checks remain mandatory.')
    dump(AREA/'RESEARCH_2020_2024_MANIFEST.json',manifest)
    print('Research whitelist frozen:',len(plan),'issuer-years;',manifest['provider_records'],'records;',len(whitelist),'files',flush=True)

if __name__=='__main__':main()
