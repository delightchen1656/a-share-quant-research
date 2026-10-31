"""Prepare issuer-action evidence only; does not update market quotes."""
from pathlib import Path
import json,hashlib
import pandas as pd
import baostock as bs

HERE=Path(__file__).resolve().parent
AREA=HERE/'inputs_pre2025'
OUT=AREA/'action_responses_2020'

def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    OUT.mkdir(exist_ok=True)
    universe=pd.read_parquet(AREA/'universe.parquet')
    keys={};files=[]
    login=bs.login();assert login.error_code=='0',login.error_msg
    try:
        for i,u in enumerate(universe.itertuples(),1):
            code=u.code;key=code+('.SH' if code.startswith('6') else '.SZ')+'/2020'
            path=OUT/(code+'.json')
            if path.exists():obj=json.loads(path.read_text(encoding='utf8'))
            else:
                rs=bs.query_dividend_data(('sh.' if code.startswith('6') else 'sz.')+code,year='2020',yearType='operate')
                assert rs.error_code=='0',(code,rs.error_msg)
                rows=[]
                while rs.next():rows.append(dict(zip(rs.fields,rs.get_row_data())))
                obj=dict(key=key,error_code=rs.error_code,records=rows)
                dump(path,obj)
            assert obj['key']==key and obj['error_code']=='0'
            for row in obj['records']:
                assert row.get('dividOperateDate','').startswith('2020-'),(code,row)
                for field,value in row.items():
                    if field.endswith('Date') and value:assert value<='2024-12-31',(code,field,value)
            keys[key]=obj['records'];files.append(dict(path=path.relative_to(AREA).as_posix(),sha256=sha(path),key=key))
            if i%100==0:print('2020 action evidence',i,'/',len(universe),flush=True)
    finally:bs.logout()
    merged=AREA/'company_actions_2020.json';dump(merged,keys)
    dump(OUT/'MANIFEST.json',dict(complete=True,stocks=len(universe),requested_operate_year=2020,provider='baostock.query_dividend_data/yearType=operate',
        records=sum(len(x) for x in keys.values()),files=files,merged=dict(path=merged.relative_to(AREA).as_posix(),sha256=sha(merged)),
        note='Explicit provider responses; empty per-stock response is evidence, not a fabricated company-action table. Completeness remains subject to provider limitations.'))
    print('Complete',len(keys),'issuer-year responses',sum(len(x) for x in keys.values()),'action records',flush=True)

if __name__=='__main__':main()
