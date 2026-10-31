"""Fetch only two observed held-stock-year gaps; preserve supplier responses."""
from pathlib import Path
from datetime import datetime
import json
import sys
import argparse
import baostock as bs

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from daily_market_update import install_baostock_socket_safety

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--gaps',type=Path)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    install_baostock_socket_safety()
    out=ROOT/'strategies/hushen_2/results/holdout_restricted/june2020_all_starts'
    destination=args.output or out/'supplemental_actions_baostock_2020.json'
    keys=json.loads(args.gaps.read_text()) if args.gaps else ['000659.SZ/2020','601717.SH/2020']
    if destination.exists():raise RuntimeError('Retained response already exists; inspect it instead of overwriting')
    response=bs.login();assert response.error_code=='0',response.error_msg
    records={};receipts=[]
    try:
        for key in keys:
            symbol,year=key.split('/')
            code=symbol[-2:].lower()+'.'+symbol[:6]
            response=bs.query_dividend_data(code=code,year=year,yearType='operate')
            assert response.error_code=='0',response.error_msg
            values=[]
            while response.next():values.append(response.get_row_data())
            assert response.error_code=='0',response.error_msg
            rows=[dict(zip(response.fields,row)) for row in values]
            for row in rows:
                if row.get('dividOperateDate'):
                    assert row['dividOperateDate'].startswith(year+'-')
                    row['source']='BaoStock query_dividend_data operate-year direct response'
                    # No synthesized pay/release dates are inserted into retained raw records.
            records[key]=rows
            receipts.append({'key':key,'code':code,'year':year,'yearType':'operate','error_code':response.error_code,'fields':response.fields,'rows':len(rows)})
            print(key,rows,flush=True)
    finally:bs.logout()
    payload={'scope':'Observed actual-held June-2020-start account coverage gaps only','fetched_at':datetime.now().isoformat(),
             'requested_keys':sorted(records),'successful_empty_keys':sorted(k for k,v in records.items() if not v),
             'keys_with_events':sorted(k for k,v in records.items() if v),'report_receipts':receipts,'records':records}
    destination.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print(destination,flush=True)

if __name__=='__main__':main()
