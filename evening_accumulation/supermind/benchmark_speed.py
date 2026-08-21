"""Reproducible local microbenchmark for legacy vs optimized SuperMind hot paths."""
import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent


def legacy_features(x, names):
    x = x.sort_index().copy(); c, v = x.close, x.volume
    r = c.pct_change(fill_method=None); vchg = v.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan)
    o = {"ret5": c.pct_change(5, fill_method=None).iloc[-1], "ret20": c.pct_change(20, fill_method=None).iloc[-1],
         "ret60": c.pct_change(60, fill_method=None).iloc[-1]}
    o["range20"] = x.high.rolling(20).max().iloc[-1] / x.low.rolling(20).min().iloc[-1] - 1
    o["range60"] = x.high.rolling(60).max().iloc[-1] / x.low.rolling(60).min().iloc[-1] - 1
    o["dd20"] = c.iloc[-1] / c.rolling(20).max().iloc[-1] - 1
    o["vol20"], o["vol60"] = r.rolling(20).std().iloc[-1], r.rolling(60).std().iloc[-1]
    o["volume_ratio"] = v.rolling(5).mean().iloc[-1] / v.rolling(20).mean().iloc[-1]
    o["volume_cv"] = v.rolling(20).std().iloc[-1] / v.rolling(20).mean().iloc[-1]
    o["up_volume_share"] = v.where(r > 0, 0).rolling(20).sum().iloc[-1] / v.rolling(20).sum().iloc[-1]
    o["pv_corr"] = r.rolling(20).corr(vchg).iloc[-1]
    lo, hi = c.rolling(60).min().iloc[-1], c.rolling(60).max().iloc[-1]
    o["close_pos60"] = (c.iloc[-1] - lo) / (hi - lo)
    o["turn20"] = x.turnover_rate.rolling(20).mean().iloc[-1]
    o["amount20"] = np.log1p(x.turnover.rolling(20).mean().iloc[-1])
    o["breakout_gap"] = c.iloc[-1] / c.shift(1).rolling(60).max().iloc[-1] - 1
    o["rise_from_low60"] = c.iloc[-1] / lo - 1
    o["volume_spike"] = v.iloc[-1] / v.rolling(20).mean().iloc[-1]
    return [float(o[n]) for n in names]


def fast_features(x, names):
    c=x.close.to_numpy(float); v=x.volume.to_numpy(float); h=x.high.to_numpy(float); lo=x.low.to_numpy(float)
    r=c[1:]/c[:-1]-1; vc=v[1:]/v[:-1]-1; mv=np.mean(v[-20:]); low60=np.min(c[-60:]); high60=np.max(c[-60:])
    o={"ret5":c[-1]/c[-6]-1,"ret20":c[-1]/c[-21]-1,"ret60":c[-1]/c[-61]-1,
       "range20":np.max(h[-20:])/np.min(lo[-20:])-1,"range60":np.max(h[-60:])/np.min(lo[-60:])-1,
       "dd20":c[-1]/np.max(c[-20:])-1,"vol20":np.std(r[-20:],ddof=1),"vol60":np.std(r[-60:],ddof=1),
       "volume_ratio":np.mean(v[-5:])/mv,"volume_cv":np.std(v[-20:],ddof=1)/mv,
       "up_volume_share":np.sum(v[-20:][r[-20:]>0])/np.sum(v[-20:]),"pv_corr":np.corrcoef(r[-20:],vc[-20:])[0,1],
       "close_pos60":(c[-1]-low60)/(high60-low60),"turn20":np.mean(x.turnover_rate.to_numpy(float)[-20:]),
       "amount20":np.log1p(np.mean(x.turnover.to_numpy(float)[-20:])),"breakout_gap":c[-1]/np.max(c[-61:-1])-1,
       "rise_from_low60":c[-1]/low60-1,"volume_spike":v[-1]/mv}
    return [float(o[n]) for n in names]


def legacy_probability(model, values):
    raw=model["baseline"]
    for tree in model["trees"]:
        i=0
        while not tree[i]["leaf"]:
            n=tree[i]; x=values[n["f"]]; i=n["l"] if (n["m"] if np.isnan(x) else x<=n["t"]) else n["r"]
        raw += tree[i]["v"]
    return 1/(1+math.exp(-raw))


def fast_probability(model, fast, values):
    raw=model["baseline"]
    for f,t,m,l,r,leaf,value in fast:
        i=0
        while not leaf[i]:
            x=values[f[i]]; i=l[i] if (m[i] if np.isnan(x) else x<=t[i]) else r[i]
        raw += value[i]
    return 1/(1+math.exp(-raw))


def batch_probability(model, fast, rows):
    x=np.asarray(rows,float); raw=np.full(len(x),model['baseline'],float)
    for f,t,m,l,r,leaf,value in fast:
        f=np.asarray(f); t=np.asarray(t); m=np.asarray(m); l=np.asarray(l); r=np.asarray(r); leaf=np.asarray(leaf); value=np.asarray(value)
        nodes=np.zeros(len(x),np.int32); active=~leaf[nodes]
        while np.any(active):
            ri=np.flatnonzero(active); ni=nodes[ri]; fi=f[ni]; xv=x[ri,fi]
            nodes[ri]=np.where(np.where(np.isnan(xv),m[ni],xv<=t[ni]),l[ni],r[ni]); active[ri]=~leaf[nodes[ri]]
        raw += value[nodes]
    return 1/(1+np.exp(-raw))


def main():
    model=json.loads((HERE/'event_standard_model.json').read_text(encoding='utf-8')); names=model['features']
    p=next((HERE.parent/'data/classified/SH/star/qfq').glob('*.parquet'))
    x=pd.read_parquet(p).tail(121).rename(columns={'amount':'turnover','turn':'turnover_rate','pctChg':'quote_rate','isST':'is_st'})
    fast=[([n['f'] for n in tr],[n['t'] for n in tr],[n['m'] for n in tr],[n['l'] for n in tr],
           [n['r'] for n in tr],[n['leaf'] for n in tr],[n['v'] for n in tr]) for tr in model['trees']]
    a=legacy_features(x,names); b=fast_features(x,names); assert np.allclose(a,b,equal_nan=True,rtol=1e-10,atol=1e-12)
    assert abs(legacy_probability(model,a)-fast_probability(model,fast,b)) < 1e-14
    def bench(fn,n):
        t=time.perf_counter()
        for _ in range(n): fn()
        return time.perf_counter()-t
    lf=bench(lambda:legacy_features(x,names),200); ff=bench(lambda:fast_features(x,names),200)
    lp=bench(lambda:legacy_probability(model,a),200); fp=bench(lambda:fast_probability(model,fast,b),200)
    rows=[b]*612
    legacy_day=bench(lambda:[legacy_probability(model,v) for v in rows],5)
    batch_day=bench(lambda:batch_probability(model,fast,rows),5)
    # One feature calculation and one prediction per stock is the real daily workload.
    result={'legacy_seconds_equal_work':lf+lp,'optimized_seconds_equal_work':ff+fp,
            'equal_work_speedup':(lf+lp)/(ff+fp),'feature_speedup':lf/ff,'single_tree_speedup':lp/fp,
            'batch_tree_speedup':legacy_day/batch_day,
            'estimated_daily_hot_path_speedup':(612*lf/200+legacy_day/5)/(612*ff/200+batch_day/5),
            'prediction_diff':abs(legacy_probability(model,a)-fast_probability(model,fast,b)),
            'batch_prediction_diff':float(np.max(np.abs(batch_probability(model,fast,rows)-legacy_probability(model,a))))}
    (HERE/'speed_benchmark.json').write_text(json.dumps(result,indent=2),encoding='utf-8'); print(json.dumps(result,indent=2))


if __name__=='__main__': main()
