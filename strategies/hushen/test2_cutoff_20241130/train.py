from pathlib import Path
import json,hashlib
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
SOURCE=HERE.parent/'cutoff_20241130'
CUT=pd.Timestamp('2024-11-30')
def stock_features(x):
    x=x.copy().set_index('date').sort_index()
    assert x.index.max()<CUT
    for k in x:x[k]=pd.to_numeric(x[k],errors='coerce')
    x=x[x.close>0]
    r=(x.close/x.preclose-1).where(x.tradestatus.eq(1)&x.preclose.gt(0),0)
    vol=r.rolling(60).std()
    ov=np.log(x.open/x.preclose).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum()
    intr=np.log(x.close/x.open).replace([np.inf,-np.inf],np.nan).fillna(0).rolling(20).sum()
    cap=x.close*x.volume/(x.turn/100).replace(0,np.nan)
    age=pd.Series(np.arange(len(x))+1,index=x.index)
    eligible=(age>=252)&x.amount.rolling(20).mean().ge(1e7)&x.close.ge(2)&x.isST.eq(0)&x.tradestatus.eq(1)&vol.gt(.001)&vol.lt(.09)
    f=pd.DataFrame(dict(cap=cap,vol=vol,overnight=ov,intraday=intr)).astype(np.float32)
    chain=(x.close/x.preclose).where(lambda z:(z>0)&np.isfinite(z)).cumprod()
    return f,eligible,chain
def main():
    manifest=json.loads((SOURCE/'snapshot_manifest.json').read_text())
    assert manifest['maximum_observation_date']<'2024-11-30'
    marketfile=SOURCE/'snapshot/benchmark.parquet'
    assert hashlib.sha256(marketfile.read_bytes()).hexdigest()==manifest['benchmark_sha256']
    dates=pd.DatetimeIndex(pd.read_parquet(marketfile).date);assert dates.max()<CUT
    symbols=sorted(r['symbol'] for r in manifest['files']);positions={s:i for i,s in enumerate(symbols)}
    matrices={k:pd.DataFrame(np.nan,index=dates,columns=symbols,dtype=np.float32) for k in ('cap','vol','overnight','intraday')}
    eligible=pd.DataFrame(False,index=dates,columns=symbols)
    prices=pd.DataFrame(np.nan,index=dates,columns=symbols,dtype=float)
    for i,r in enumerate(manifest['files']):
        p=SOURCE/'snapshot'/(r['symbol']+'.parquet');assert hashlib.sha256(p.read_bytes()).hexdigest()==r['sha256']
        f,e,c=stock_features(pd.read_parquet(p));s=r['symbol']
        for k in matrices:matrices[k][s]=f[k].reindex(dates)
        eligible[s]=e.reindex(dates,fill_value=False)
        prices[s]=c.reindex(dates)
        if (i+1)%500==0:print('Features',i+1,flush=True)
    ranks={k:v.where(eligible).rank(axis=1,pct=True,method='average').astype(np.float32) for k,v in matrices.items()}
    start=int(np.flatnonzero(dates>=pd.Timestamp('2020-01-01'))[0])
    signal_indices=[i-1 for i in range(start,len(dates)) if (i==start or (i-1)%20==0) and i-1+20<len(dates)]
    sd=dates[signal_indices];ends=dates[np.array(signal_indices)+20]
    labels=(prices.shift(-20)/prices-1).iloc[signal_indices].fillna(-1.)
    assert ends.max()<CUT
    dev=(sd<pd.Timestamp('2023-01-01'))&(ends<pd.Timestamp('2023-01-01'))
    valid=sd>=pd.Timestamp('2023-01-01')
    trials=[];metrics={}
    for cap in (.30,.35,.40):
        for vol in (.15,.20,.25):
            ov=.25;intr=round(1-cap-vol-ov,10);weights=[cap,vol,ov,intr]
            cid='C%.2f_V%.2f_O%.2f_I%.2f'%tuple(weights)
            score=-cap*ranks['cap']-vol*ranks['vol']+ov*ranks['overnight']-intr*ranks['intraday']
            smooth=score.rolling(5,min_periods=3).mean().astype(np.float32).iloc[signal_indices].where(eligible.iloc[signal_indices])
            rows=[]
            # Only development metrics participate in the grid selection.
            for j in np.flatnonzero(dev):
                s=smooth.iloc[j].dropna();y=labels.iloc[j].reindex(s.index)
                rows.append(dict(signal_date=str(sd[j].date()),label_end=str(ends[j].date()),n=len(s),ic=float(s.rank().corr(y.rank()))))
            assert rows and all(np.isfinite(r['ic']) for r in rows)
            trials.append(dict(config=cid,weights=weights,dev_mean_ic=float(np.mean([r['ic'] for r in rows])),dev_periods=len(rows),dev_samples=sum(r['n'] for r in rows),distance_original=float(np.abs(np.array(weights)-[.35,.2,.25,.2]).sum())))
            metrics[cid]=rows
    trials.sort(key=lambda r:(-r['dev_mean_ic'],r['distance_original'],r['config']));winner=trials[0]
    (HERE/'selected_weights.json').write_text(json.dumps(winner,indent=2),encoding='utf-8')
    cap,vol,ov,intr=winner['weights']
    score=-cap*ranks['cap']-vol*ranks['vol']+ov*ranks['overnight']-intr*ranks['intraday']
    smooth=score.rolling(5,min_periods=3).mean().astype(np.float32).iloc[signal_indices].where(eligible.iloc[signal_indices])
    rows=[]
    for j in np.flatnonzero(valid):
        s=smooth.iloc[j].dropna();y=labels.iloc[j].reindex(s.index)
        rows.append(dict(signal_date=str(sd[j].date()),label_end=str(ends[j].date()),n=len(s),ic=float(s.rank().corr(y.rank()))))
    smooth.to_parquet(HERE/'selected_signal_scores.parquet')
    result=dict(selected=winner,trials=trials,validation=rows,validation_mean_ic=float(np.mean([r['ic'] for r in rows])),
        validation_positive_fraction=float(np.mean([r['ic']>0 for r in rows])),maximum_observation_date=manifest['maximum_observation_date'],
        maximum_label_date=str(ends.max().date()),symbols=len(symbols),protocol_sha256=hashlib.sha256((HERE/'PROTOCOL.md').read_bytes()).hexdigest(),
        snapshot_manifest_sha256=hashlib.sha256((SOURCE/'snapshot_manifest.json').read_bytes()).hexdigest(),
        warning='Factor IC only, not a portfolio backtest. Inherited framework has prior exposure to later research data.')
    (HERE/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    (HERE/'development_period_metrics.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('trials','validation')},indent=2),flush=True)
if __name__=='__main__':main()
