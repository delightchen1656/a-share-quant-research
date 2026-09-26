"""Conservative current-vintage annual signals; source provenance remains a gate."""
import hashlib,json
import numpy as np
import pandas as pd
import research as r
from prepare_lower_liquidity import PATH as BASE

DIRECTORY=r.HERE/'public_sources/annual_performance'
FEATURES=r.HERE/'features_broad_financials.parquet'
NAMES=['fin_roe','fin_margin','fin_cash','fin_growth']

def events(rows):
    f=pd.DataFrame(rows)
    if f.empty:return pd.DataFrame()
    for col in ('REPORTDATE','NOTICE_DATE','UPDATE_DATE','EITIME'):
        f[col]=pd.to_datetime(f[col],errors='coerce')
    f=f.dropna(subset=['REPORTDATE','NOTICE_DATE','UPDATE_DATE']).copy()
    source=f.get('_source_schema',pd.Series('BATCH',index=f.index))
    # F10 genuinely does not expose ingestion time. Do not fabricate EITIME.
    # Its disclosed update/notice lag remains a weaker, explicitly flagged proxy.
    f=f[(source=='F10')|f.EITIME.notna()].copy()
    f=f[(f.REPORTDATE.dt.month==12)&(f.REPORTDATE.dt.day==31)]
    f['fin_available']=f[['NOTICE_DATE','UPDATE_DATE','EITIME']].max(axis=1)
    f=f[f.fin_available>f.REPORTDATE].sort_values(['fin_available','REPORTDATE'])
    # An old report revised later must not replace a newer report already visible.
    f=f[f.REPORTDATE==f.REPORTDATE.cummax()].drop_duplicates('fin_available',keep='last')
    n=lambda col:pd.to_numeric(f[col],errors='coerce')
    f['fin_roe']=n('WEIGHTAVG_ROE').clip(-100,100)
    f['fin_margin']=(100*n('PARENT_NETPROFIT')/n('TOTAL_OPERATE_INCOME').where(n('TOTAL_OPERATE_INCOME')>0)).clip(-100,100)
    f['fin_cash']=(n('MGJYXJJE')/n('BASIC_EPS').where(n('BASIC_EPS')>0)).clip(-5,5)
    f['fin_growth']=n('SJLTZ').clip(-100,100)
    return f.rename(columns={'REPORTDATE':'fin_report'})[['fin_available','fin_report']+NAMES].replace([np.inf,-np.inf],np.nan)

def align(rows,dates):
    left=pd.DataFrame({'signal_date':pd.to_datetime(dates),'ordinal':np.arange(len(dates))})
    ev=events(rows)
    if ev.empty:
        out=pd.DataFrame({name:np.nan for name in NAMES},index=range(len(dates)))
        out['fin_available']=pd.NaT;out['fin_report']=pd.NaT
        return out
    out=pd.merge_asof(left.sort_values('signal_date'),ev,on=None,left_on='signal_date',right_on='fin_available',
        direction='backward',allow_exact_matches=False).sort_values('ordinal')
    stale=(out.signal_date-out.fin_report)>pd.Timedelta(days=900)
    out.loc[stale,NAMES]=np.nan
    out.loc[stale,['fin_available','fin_report']]=pd.NaT
    return out[['fin_available','fin_report']+NAMES].reset_index(drop=True)

def main(supplement=None,extra_audit=None):
    assert not FEATURES.exists(),'Preserve completed feature versions'
    manifest=json.loads((DIRECTORY/'download_summary.json').read_text(encoding='utf-8'))
    rows=[]
    for item in manifest['pages']:
        path=DIRECTORY/('%d_%03d.json'%(item['year'],item['page']))
        raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
        rows.extend(json.loads(raw)['result']['data'])
    universe=pd.read_csv(r.e.DATA/'metadata/historical_mainboard_universe.csv')
    wanted=set(universe.symbol);reports={}
    for row in rows:
        if row.get('SECUCODE') in wanted:reports.setdefault(row['SECUCODE'],[]).append(row)
    if supplement:
        assert not (set(reports)&set(supplement)),'Do not overwrite existing source reports'
        reports.update(supplement)
    f=pd.read_parquet(BASE);f=f[f.amount20>=20e6].copy()
    percentile=f.groupby('execute_date').float_cap_proxy.rank(pct=True)
    f['float_cap_proxy_group']=np.minimum(np.floor(percentile*3),2).fillna(-1).astype(int)
    parts=[]
    for i,(symbol,group) in enumerate(f.groupby('symbol')):
        z=align(reports.get(symbol,[]),group.signal_date);z.index=group.index;parts.append(z)
        if i%500==0:print('FINANCIAL_ALIGN',i,flush=True)
    f=f.join(pd.concat(parts));known=f.fin_available.notna()
    assert (f.loc[known,'fin_available']<f.loc[known,'signal_date']).all()
    retired=set(universe.loc[universe.outDate.notna(),'symbol'])
    coverage={str(year):dict(rows=len(group),known=float(group.fin_available.notna().mean()),
        retired_known=float(group.loc[group.symbol.isin(retired),'fin_available'].notna().mean()))
        for year,group in f.groupby(f.execute_date.dt.year)}
    f.to_parquet(FEATURES,index=False)
    r.save(FEATURES.with_suffix('.json'),dict(rows=len(f),symbols=f.symbol.nunique(),coverage=coverage,
        historical_universe=len(wanted),report_symbols=len(reports),
        retired_universe=len(retired),retired_report_symbols=len(retired&set(reports)),
        no_report_symbols=sorted(wanted-set(reports)),
        source_manifest_sha256=hashlib.sha256((DIRECTORY/'download_summary.json').read_bytes()).hexdigest(),
        source_features_sha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
        rule='strictly after max(NOTICE_DATE,UPDATE_DATE,EITIME); annual latest visible report; max900days old; missing signals neutral, no deletion;20million amount and recomputed size terciles',
        supplement=extra_audit,
        vintage_warning='Current-vintage, NOT certified original PIT; original filing audit required for successful candidates'))
    print('PREPARED',len(f),coverage,flush=True)

if __name__=='__main__':main()
