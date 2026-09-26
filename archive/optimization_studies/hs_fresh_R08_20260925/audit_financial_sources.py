"""Cross-check 98 overlapping public financial histories; does not certify PIT."""
import json
import numpy as np
import research as r
from prepare_complete_financials import MAP

if __name__=='__main__':
    d=r.HERE/'public_sources/annual_performance'
    manifest=json.loads((d/'download_summary.json').read_text(encoding='utf-8'))
    lookup={}
    for p in manifest['pages']:
        rows=json.loads((d/('%d_%03d.json'%(p['year'],p['page']))).read_text(encoding='utf-8'))['result']['data']
        for row in rows:lookup[(row['SECUCODE'],row['REPORTDATE'][:10])]=row
    d=r.HERE/'public_sources/historical_financials'
    sm=json.loads((d/'download_summary.json').read_text(encoding='utf-8'))
    counts={k:dict(compared=0,equal=0,missing_one_side=0) for k in MAP}
    examples=[];matched=0
    for item in sm['downloaded']:
        rows=json.loads((d/(item['symbol']+'.json')).read_text(encoding='utf-8'))['result']['data']
        for row in rows:
            other=lookup.get((item['symbol'],row['REPORT_DATE'][:10]))
            if other is None:continue
            matched+=1
            for field,src in MAP.items():
                a,b=other.get(field),row.get(src);c=counts[field]
                if a is None or b is None:
                    c['missing_one_side']+=int((a is None)!=(b is None));continue
                c['compared']+=1
                same=(str(a)[:10]==str(b)[:10]) if 'DATE' in field else bool(np.isclose(float(a),float(b),rtol=1e-6,atol=1e-6))
                c['equal']+=int(same)
                if not same and len(examples)<30:examples.append(dict(symbol=item['symbol'],period=row['REPORT_DATE'],field=field,batch=a,F10=b))
    out=dict(matched_report_pairs=matched,counts=counts,first_differences=examples,
        warning='Cross-source agreement is not original-vintage public-availability proof')
    r.save(r.HERE/'financial_source_comparison.json',out);print(json.dumps(dict(matched=matched,counts=counts)),flush=True)
