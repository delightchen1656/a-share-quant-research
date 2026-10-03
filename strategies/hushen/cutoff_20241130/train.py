"""Bounded R08 factor-weight fitting. No post-cutoff inputs or portfolio claims."""
from pathlib import Path
import hashlib, json, sys, types
import importlib.util
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
CUT=pd.Timestamp('2024-11-30')
HORIZON=40
def features(x,market):
    x=x.set_index('date').sort_index().copy()
    assert x.index.max()<CUT
    for c in x:x[c]=pd.to_numeric(x[c],errors='coerce')
    ratio=x.close/x.preclose
    ratio=ratio.where((ratio>0)&np.isfinite(ratio),np.nan)
    c=ratio.cumprod()  # raw corporate-action-reference chain, no future adjustment scale
    ret=c.pct_change(fill_method=None)
    vol20=ret.rolling(20).std()
    event=x.close.shift()/x.preclose-1
    dist=event.where(event.between(.0005,.08),0).clip(upper=.04).rolling(250,min_periods=250).sum()
    a=np.log(c.reindex(market.index).where(lambda z:z>0)).diff()
    b=np.log(market.where(market>0)).diff()
    va=a.rolling(252,min_periods=220).var();vb=b.rolling(252,min_periods=220).var()
    beta=a.rolling(252,min_periods=220).cov(b)/vb
    mom=a.rolling(232,min_periods=220).sum().shift(20)
    bm=b.rolling(232,min_periods=220).sum().shift(20)
    risk=va.shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232)
    residual=(va-beta.pow(2)*vb).shift(20).clip(lower=1e-6).pow(.5)*np.sqrt(232)
    f=pd.DataFrame(index=market.index)
    f['float_cap_proxy']=x.volume/(x.turn.where(x.turn>0)/100)*x.close
    f['distribution_proxy']=dist;f['long_risk']=mom/risk
    f['market_adjusted']=(mom-beta.shift(20)*bm)/residual
    f['vol60']=ret.rolling(60).std();f['ret5']=c/c.shift(5)-1;f['turn20']=x.turn.rolling(20).mean()
    eligible=(pd.Series(np.arange(len(x))+1,index=x.index)>=250)&x.isST.eq(0)&x.tradestatus.eq(1)&vol20.between(.001,.08)&x.amount.rolling(20).mean().ge(50e6)
    eligible &= x.preclose.gt(0).rolling(250,min_periods=250).sum().eq(250)
    f['eligible']=eligible.reindex(market.index).fillna(False).astype(bool)
    f['label']=c.reindex(market.index).shift(-HORIZON)/c.reindex(market.index)-1
    f['missing_terminal']=f.label.isna()
    f['label']=f.label.fillna(-1.)
    f['label_end']=pd.Series(market.index,index=market.index).shift(-HORIZON)
    return f,c,x

def periods(market):
    days=market.index;selected=[];last=None
    for i,d in enumerate(days):
        if d<pd.Timestamp('2020-01-01'):continue
        key=(d.year,d.month)
        due=last is None or (key!=last and d.month%2==1)
        last=key
        if due and i>0:selected.append(days[i-1])
    return pd.DatetimeIndex(selected)

def main():
    manifest=json.loads((HERE/'snapshot_manifest.json').read_text())
    assert manifest['maximum_observation_date']<'2024-11-30'
    assert hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest()==manifest['protocol_sha256']
    benchmark=HERE/'snapshot/benchmark.parquet'
    assert hashlib.sha256(benchmark.read_bytes()).hexdigest()==manifest['benchmark_sha256']
    market=pd.read_parquet(benchmark).set_index('date').close
    assert market.index.max()<CUT
    dates=periods(market);chunks=[];parity=[]
    sys.modules.setdefault('mindgo_api',types.ModuleType('mindgo_api'))
    spec=importlib.util.spec_from_file_location('frozen_r08',HERE.parent/'supermind_mainboard_baseline_1.py')
    original=importlib.util.module_from_spec(spec);spec.loader.exec_module(original)
    for i,item in enumerate(manifest['files']):
        p=HERE/'snapshot'/(item['symbol']+'.parquet')
        assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256']
        raw=pd.read_parquet(p)
        f,c,x=features(raw,market)
        take=f.reindex(dates);take=take[take.eligible & take.label_end.notna() & (take.label_end<CUT)].copy()
        take['symbol']=item['symbol'];take.index.name='signal_date';chunks.append(take.reset_index())
        if len(parity)<12 and len(take):
            d=take.index[-1];q=pd.DataFrame({'close':c.loc[:d].tail(320)})
            r=x.loc[:d].tail(320).rename(columns={'preclose':'prev_close','amount':'turnover','turn':'turnover_rate','isST':'is_st'})
            r['is_paused']=1-r.tradestatus
            check=original.stock_features(q,r,market.loc[:d].tail(320))
            if check is not None and all(np.isfinite(list(check.values()))):
                for k,v in check.items():assert np.isclose(v,f.loc[d,k],rtol=1e-8,atol=1e-9),(item['symbol'],k,v,f.loc[d,k])
                parity.append(dict(symbol=item['symbol'],date=str(d.date())))
        if (i+1)%500==0:print('Features',i+1,'/',len(manifest['files']),flush=True)
    data=pd.concat(chunks,ignore_index=True);frames=[]
    required=['long_risk','market_adjusted','distribution_proxy','vol60','ret5','turn20']
    for d,x in data.groupby('signal_date',sort=True):
        x=x.sort_values('symbol').replace([np.inf,-np.inf],np.nan)
        groups=np.minimum(np.floor(x.float_cap_proxy.rank(pct=True)*3),2)
        x=x.loc[groups==1].dropna(subset=required).copy()
        if len(x)<12:raise ValueError('Insufficient cross section')
        x['d_rank']=x.distribution_proxy.rank(pct=True)
        x['m_rank']=x.long_risk.rank(pct=True)
        x['v_rank']=1-x.vol60.rank(pct=True)
        frames.append(x)
    data=pd.concat(frames,ignore_index=True)
    assert data.signal_date.max()<CUT and data.label_end.max()<CUT
    data.to_parquet(HERE/'bounded_training_samples.parquet',index=False)
    trials=[];period_details=[]
    # Development-only selection. Validation is not read until winner is fixed.
    dev=data[(data.signal_date<'2023-01-01')&(data.label_end<'2023-01-01')]
    validation=data[data.signal_date>='2023-01-01']
    for wd in (.3,.4,.5):
        for wm in (.2,.3,.4):
            wv=round(1-wd-wm,10);cid='D%.1f_M%.1f_V%.1f'%(wd,wm,wv)
            scores=[]
            for d,x in dev.groupby('signal_date',sort=True):
                score=wd*x.d_rank+wm*x.m_rank+wv*x.v_rank
                ic=score.rank().corr(x.label.rank())
                assert np.isfinite(ic)
                scores.append(ic);period_details.append(dict(config=cid,signal_date=str(d.date()),ic=float(ic),n=len(x)))
            trials.append(dict(config=cid,weights=[wd,wm,wv],dev_mean_ic=float(np.mean(scores)),dev_positive_fraction=float(np.mean(np.array(scores)>0)),dev_periods=len(scores),distance_original=abs(wd-.4)+abs(wm-.3)+abs(wv-.3)))
    trials.sort(key=lambda r:(-r['dev_mean_ic'],r['distance_original'],r['config']))
    winner=trials[0]
    (HERE/'selected_weights.json').write_text(json.dumps(winner,indent=2),encoding='utf-8')
    validation_rows=[]
    wd,wm,wv=winner['weights']
    for d,x in validation.groupby('signal_date',sort=True):
        x=x.copy();x['score']=wd*x.d_rank+wm*x.m_rank+wv*x.v_rank
        ranked=x.sort_values(['score','symbol'],ascending=[False,True])
        validation_rows.append(dict(signal_date=str(d.date()),label_end=str(x.label_end.iloc[0].date()),n=len(x),ic=float(x.score.rank().corr(x.label.rank())),top12_label_mean=float(ranked.head(12).label.mean()),universe_label_mean=float(x.label.mean())))
    result=dict(cutoff_exclusive='2024-11-30',maximum_observation_date=manifest['maximum_observation_date'],maximum_label_date=str(data.label_end.max().date()),
        symbols=manifest['symbols'],samples=len(data),dev_samples=len(dev),validation_samples=len(validation),trials=trials,selected=winner,
        validation=validation_rows,validation_mean_ic=float(np.mean([r['ic'] for r in validation_rows])),
        validation_positive_fraction=float(np.mean([r['ic']>0 for r in validation_rows])),missing_terminal_labels=int(data.missing_terminal.sum()),
        formula_parity_checks=parity,protocol_sha256=manifest['protocol_sha256'],
        warning='IC is not portfolio performance. Framework previously selected using later data; not a pristine historical experiment.')
    (HERE/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (HERE/'development_period_metrics.json').write_text(json.dumps(period_details,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('trials','validation','formula_parity_checks')},indent=2),flush=True)
if __name__=='__main__':main()
