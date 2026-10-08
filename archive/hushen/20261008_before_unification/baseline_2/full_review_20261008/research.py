"""Frozen-core independent factor reconstruction and falsification diagnostics."""
from pathlib import Path
from types import SimpleNamespace as NS
import ast, hashlib, importlib.util, json, sys, types
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
BASE=HERE.parents[1]
ROOT=BASE.parents[1]
DATA=ROOT/'sh_sz_market_research/data_pipeline/data'
Q=json.loads((HERE/'protocol.json').read_text(encoding='utf-8'))
FEATURES=['cap','vol','overnight','intraday']
CONTROLS={'original':[-.35,-.20,.25,-.20], 'size_only':[-1,0,0,0],
          'low_vol_only':[0,-1,0,0], 'overnight_only':[0,0,1,0], 'intraday_only':[0,0,0,-1],
          'without_size':[0,-.20,.25,-.20], 'without_vol':[-.35,0,.25,-.20],
          'without_overnight':[-.35,-.20,0,-.20], 'without_intraday':[-.35,-.20,.25,0]}
BAD={'000029.SZ','000981.SZ','002166.SZ','002466.SZ','002546.SZ','002759.SZ','003038.SZ','600272.SH','600483.SH','601258.SH','601686.SH'}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def dump(name,x): (HERE/name).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def mod(path,name):
    sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def features(x):
    x=x[x.close>0].copy()
    r=(x.close/x.preclose-1).where(x.tradestatus.eq(1)&x.preclose.gt(0),0.)
    f=pd.DataFrame(index=x.index)
    f['cap']=x.close*x.volume/(x.turn/100).replace(0,np.nan)
    f['vol']=r.rolling(60).std()
    f['overnight']=np.log(x.open/x.preclose).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum()
    f['intraday']=np.log(x.close/x.open).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum()
    eligible=((np.arange(len(x))+1>=252)&x.amount.rolling(20).mean().ge(1e7)&x.close.ge(2)&
              x.isST.eq(0)&x.tradestatus.eq(1)&f.vol.gt(.001)&f.vol.lt(.09))
    chain=(x.close/x.preclose).where(lambda z:z.gt(0)&np.isfinite(z)).cumprod()
    return f.astype(np.float32),eligible,chain

def prepare():
    source=mod(HERE/'uploaded_v5.py','audit_original')
    dates=pd.DatetimeIndex(pd.read_parquet(BASE/'start_date_study/benchmark.parquet').date)
    dates=dates[dates<=Q['end']]
    meta=pd.read_csv(DATA/'metadata/historical_mainboard_universe.csv').set_index('symbol')
    files=sorted((DATA/'raw').glob('*/*.parquet'))
    symbols=[p.stem for p in files]
    shape=(len(dates),len(symbols))
    values={k:np.full(shape,np.nan,dtype=np.float32) for k in FEATURES}
    eligible=np.zeros(shape,dtype=bool)
    chain=np.full(shape,np.nan,dtype=np.float64)
    audit=[];errors=[];pit_changes=0;prefix_tests=[];inputs=[]
    probes=[pd.Timestamp('2019-12-31'),pd.Timestamp('2022-12-30'),pd.Timestamp('2026-09-29')]
    sample_raw={str(d.date()):{} for d in probes}
    for j,path in enumerate(files):
        if not source.mainboard(path.stem):raise ValueError('Unexpected non-mainboard raw input')
        x=pd.read_parquet(path);x.date=pd.to_datetime(x.date)
        inputs.append(dict(symbol=path.stem,sha256=sha(path),max_date=str(x.date.max().date())))
        if x.date.duplicated().any():errors.append([path.stem,'duplicate_date'])
        x=x[x.date<=Q['end']].set_index('date').sort_index()
        columns=['open','high','low','close','preclose','volume','amount','turn','tradestatus','isST']
        x=x[columns].apply(pd.to_numeric,errors='raise')
        live=x[x.tradestatus.eq(1)]
        invalid=live[(live[['open','high','low','close','preclose']]<=0).any(axis=1)|
                     live.high.lt(live[['open','close','low']].max(axis=1)-.001)|
                     live.low.gt(live[['open','close','high']].min(axis=1)+.001)|live.volume.lt(0)]
        if len(invalid):errors.append([path.stem,'invalid_active_bars',len(invalid)])
        noncalendar=x.index.difference(dates)
        if len(noncalendar):errors.append([path.stem,'not_in_calendar',len(noncalendar)])
        f,e,c=features(x)
        listed=pd.Series(True,index=e.index)
        if path.stem not in meta.index:
            errors.append([path.stem,'missing_security_metadata'])
        else:
            row=meta.loc[path.stem]
            if pd.notna(row.ipoDate):listed &= listed.index>=pd.Timestamp(row.ipoDate)
            if pd.notna(row.outDate):listed &= listed.index<pd.Timestamp(row.outDate)
        pit_changes+=int((e&~listed).sum());e &= listed
        for k in FEATURES:values[k][:,j]=f[k].reindex(dates).to_numpy()
        eligible[:,j]=e.reindex(dates,fill_value=False).to_numpy()
        chain[:,j]=c.reindex(dates).to_numpy()
        if j%113==0 and len(x.loc[:'2022-12-30'])>300:
            prefix=features(x.loc[:'2022-12-30'])[0]
            prefix_tests.append(bool(np.allclose(prefix,f.reindex(prefix.index),equal_nan=True)))
        renamed=x.rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'}).copy()
        renamed['is_paused']=1-renamed.tradestatus
        for d in probes:
            z=renamed.loc[:d].tail(320)
            if len(z):sample_raw[str(d.date())][path.stem]=z[source.FIELDS]
        audit.append(dict(symbol=path.stem,rows=len(x),start=str(x.index.min().date()),end=str(x.index.max().date()),
                          active=int(x.tradestatus.eq(1).sum()),historical_delisted=bool(path.stem in meta.index and pd.notna(meta.loc[path.stem,'outDate']))))
        if (j+1)%600==0:print('DATA',j+1,len(files),flush=True)
    ranks={k:pd.DataFrame(values[k],index=dates,columns=symbols).where(eligible).rank(axis=1,pct=True,method='average').astype(np.float32) for k in FEATURES}
    original=sum(w*ranks[k] for w,k in zip(CONTROLS['original'],FEATURES)).rolling(5,min_periods=3).mean().astype(np.float32).where(eligible)
    parity=[]
    for d in probes:
        ds=dates[dates<=d][-5:]
        members={str(dd.date()):set(meta.index[(pd.to_datetime(meta.ipoDate)<=dd)&(meta.outDate.isna()|(pd.to_datetime(meta.outDate)>dd))]) for dd in ds}
        got,_=source.compute_signals(sample_raw[str(d.date())],members,ds)
        expect=original.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist()
        parity.append(dict(date=str(d.date()),equal=got==expect,first_difference=next(((a,b) for a,b in zip(got,expect) if a!=b),None)))
    if errors:dump('data_errors.json',errors)
    dump('data_audit.json',dict(symbols=len(symbols),rows=sum(r['rows'] for r in audit),errors=errors,pit_eligibility_changes=pit_changes,
        details=audit,delisted_count=sum(r['historical_delisted'] for r in audit),prefix_independence=prefix_tests,platform_signal_parity=parity,
        boundaries='Metadata is historical vendor inventory, not independently proven complete exchange universe. QFQ anomalies retained; raw prices/preclose are used.'))
    dump('inputs.json',dict(files=inputs,calendar_sha256=sha(BASE/'start_date_study/benchmark.parquet'),protocol_sha256=sha(HERE/'protocol.json'),source_sha256=sha(HERE/'uploaded_v5.py')))
    assert not errors,errors[:10]
    assert all(prefix_tests) and all(r['equal'] for r in parity),parity
    np.savez_compressed(HERE/'factor_cache.npz',dates=dates.values,symbols=np.array(symbols),eligible=eligible,chain=chain,
                        **{k:v.to_numpy() for k,v in ranks.items()})
    requests=[pd.Timestamp(year=y,month=m,day=1) for y in range(2020,2027) for m in (1,7)]
    dump('requests.json',[dict(requested=str(r.date()),actual=str(dates[dates>=r][0].date())) for r in requests])
    print('PREPARED',shape,flush=True)

def signals():
    z=np.load(HERE/'factor_cache.npz');dates=pd.DatetimeIndex(z['dates']);symbols=z['symbols'].tolist()
    eligible=z['eligible'];chain=pd.DataFrame(z['chain'],index=dates,columns=symbols)
    ranks={k:pd.DataFrame(z[k],index=dates,columns=symbols) for k in FEATURES}
    label=chain.shift(-20)/chain-1
    all_ic=[]
    for name,w in CONTROLS.items():
        score=sum(a*ranks[k] for a,k in zip(w,FEATURES)).rolling(5,min_periods=3).mean().astype(np.float32).where(eligible)
        output={str(d.date()):score.loc[d].dropna().sort_values(ascending=False,kind='mergesort').head(100).index.tolist()
                for d in dates[(dates>='2018-12-20')&(dates<'2026-09-30')]}
        dump('rankings_'+name+'.json',output)
        for start,end,stage in [('2019-01-01','2022-12-31','development'),('2023-01-01','2023-12-31','selection'),('2024-01-01','2024-12-31','confirmation'),('2025-01-01','2026-09-30','evaluation')]:
            for i in range(0,len(dates)-20,20):
                d=dates[i]
                if not pd.Timestamp(start)<=d<=pd.Timestamp(end) or dates[i+20]>pd.Timestamp(end):continue
                a=score.iloc[i];y=label.iloc[i];ok=a.notna()&y.notna()
                if ok.sum()<100:continue
                sr=a[ok].rank(pct=True);yy=y[ok]
                groups=[float(yy[(sr>q/5)&(sr<=(q+1)/5)].mean()) for q in range(5)]
                all_ic.append(dict(control=name,stage=stage,date=str(d.date()),label_end=str(dates[i+20].date()),n=int(ok.sum()),
                                   missing_label=int((a.notna()&y.isna()).sum()),ic=float(a[ok].rank().corr(yy.rank())),quintile_returns=groups))
        print('SIGNALS',name,flush=True)
    dump('factor_diagnostics.json',all_ic)
    grouped=[]
    for (name,stage),g in pd.DataFrame(all_ic).groupby(['control','stage']):
        groups=np.array(g.quintile_returns.tolist()).mean(axis=0)
        grouped.append(dict(control=name,stage=stage,periods=len(g),mean_ic=float(g.ic.mean()),positive_fraction=float(g.ic.gt(0).mean()),
                            mean_quintile_returns=groups.tolist(),top_minus_bottom=float(groups[-1]-groups[0]),missing_labels=int(g.missing_label.sum())))
    dump('factor_summary.json',grouped)

if __name__=='__main__':{'prepare':prepare,'signals':signals}[sys.argv[1]]()
