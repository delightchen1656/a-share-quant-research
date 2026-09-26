"""Known annual profit / contemporary free-float cap PROXY, not true earnings yield."""
import hashlib,json
import pandas as pd
import numpy as np
import research as r
from prepare_complete_financials import FEATURES as BASE

FEATURES=r.HERE/'features_earnings_float_value.parquet'

def annual_lookup():
    root=r.HERE/'public_sources';records=[]
    summary=json.loads((root/'annual_performance/download_summary.json').read_text(encoding='utf-8'))
    for item in summary['pages']:
        raw=(root/'annual_performance'/('%d_%03d.json'%(item['year'],item['page']))).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        for x in json.loads(raw)['result']['data']:
            records.append(dict(symbol=x['SECUCODE'],fin_report=pd.Timestamp(x['REPORTDATE']),annual_profit=x['PARENT_NETPROFIT']))
    summary=json.loads((root/'retired_financial_probe/download_summary.json').read_text(encoding='utf-8'))
    for item in summary['downloaded']:
        raw=(root/'retired_financial_probe'/(item['symbol']+'.json')).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==item['sha256']
        for x in json.loads(raw)['result']['data']:
            if x['REPORT_DATE'][:10] in {str(y)+'-12-31' for y in range(2017,2026)}:
                records.append(dict(symbol=item['symbol'],fin_report=pd.Timestamp(x['REPORT_DATE']),annual_profit=x['PARENTNETPROFIT']))
    out=pd.DataFrame(records);assert not out.duplicated(['symbol','fin_report']).any()
    return out

def add_value(frame,lookup):
    out=frame.merge(lookup,on=['symbol','fin_report'],how='left',validate='many_to_one',sort=False)
    assert len(out)==len(frame)
    out['earnings_float_proxy']=(pd.to_numeric(out.annual_profit,errors='coerce')/
        out.float_cap_proxy.where(out.float_cap_proxy>0)).replace([np.inf,-np.inf],np.nan).clip(-2,2)
    assert out.loc[out.fin_report.isna(),'earnings_float_proxy'].isna().all()
    return out

if __name__=='__main__':
    assert not FEATURES.exists(),'Preserve completed feature version'
    f=add_value(pd.read_parquet(BASE),annual_lookup())
    known=f.earnings_float_proxy.notna()
    assert (f.loc[known,'fin_available']<f.loc[known,'signal_date']).all()
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),known_fraction=float(known.mean()),
        base_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
        definition='annual parent profit of the already selected available report / signalday free-float cap proxy; clipped[-2,2]; NOT PE or true EP; floating share fraction distorts interpretation',
        warning='Same current-vintage financial availability caveats as round17; no certification of PIT or strategy performance'))
    print('PREPARED',len(f),float(known.mean()),flush=True)
