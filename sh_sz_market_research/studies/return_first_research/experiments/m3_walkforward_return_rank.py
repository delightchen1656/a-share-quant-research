"""Walk-forward technical return ranking with a low-turnover rank buffer."""
from __future__ import annotations

import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m2_simple_baselines import load_features, metrics, ONE_WAY_COST  # noqa: E402

OUT=STUDY/"reports"/"m3_walkforward_return_rank"
FEATURES=["ret5","ret20","ret60","ret120","vol20","vol60","position60",
          "liq_ratio","amount20"]
HORIZONS=(5,10,20)
TOP_N, BUFFER_N, REBALANCE=30,60,20


def train_predict(x,horizon):
    g=x.groupby("symbol",sort=False)
    future=g.qfq_close.shift(-horizon)/g.qfq_close.shift(-1)-1
    x[f"target{horizon}"]=future.groupby(x.date).rank(pct=True)
    x[f"ml{horizon}"]=np.nan
    metadata=[]
    rng=np.random.default_rng(20260914+horizon)
    for year in range(2021,2027):
        cutoff=pd.Timestamp(year=year-1,month=12,day=1)
        begin=pd.Timestamp(year=max(2018,year-3),month=1,day=1)
        train=x[x.date.between(begin,cutoff)&x.eligible].dropna(subset=FEATURES+[f"target{horizon}"])
        if len(train)>450_000:
            train=train.iloc[rng.choice(len(train),450_000,replace=False)]
        test=x[(x.date.dt.year==year)&x.eligible&x[FEATURES].notna().all(axis=1)]
        model=lgb.LGBMRegressor(objective="regression_l1",n_estimators=180,learning_rate=.035,
            num_leaves=24,max_depth=6,min_child_samples=300,subsample=.8,colsample_bytree=.8,
            reg_lambda=8,reg_alpha=2,verbosity=-1,n_jobs=-1,random_state=year+horizon)
        model.fit(train[FEATURES],train[f"target{horizon}"])
        x.loc[test.index,f"ml{horizon}"]=model.predict(test[FEATURES])
        ic=pd.Series(x.loc[test.index,f"ml{horizon}"],index=test.index).corr(
            x.loc[test.index,f"target{horizon}"],method="spearman")
        metadata.append({"horizon":horizon,"prediction_year":year,"train_begin":str(begin.date()),
                         "train_label_cutoff":str(cutoff.date()),"train_rows":len(train),
                         "test_rows":len(test),"rank_ic":ic})
        print(f"h={horizon} year={year} rows={len(train)} rankIC={ic:.4f}",flush=True)
    return metadata


def simulate_buffer(x,score,top_n=TOP_N,buffer_n=BUFFER_N,rebalance=REBALANCE,
                    start="2021-01-01",end="2026-08-31"):
    z=x[x.date.between(start,end)]; dates=sorted(z.date.unique())
    days={d:a.set_index("symbol") for d,a in z.groupby("date")}
    current={}; pending=None; gross=net=1.; rows=[]
    for i,date in enumerate(dates):
        d=days[date]
        ret=sum(w*float(d.at[s,"ret1"]) for s,w in current.items()
                if s in d.index and np.isfinite(d.at[s,"ret1"]))
        gross*=1+ret; net*=1+ret; turnover=0.
        if pending is not None:
            target={}
            for s,w in pending.items():
                if s not in d.index: continue
                q=d.loc[s]
                if bool(q.tradable) and not bool(q.one_price_up): target[s]=w
            for s,w in current.items():
                if s in target: continue
                if s in d.index and (not bool(d.at[s,"tradable"]) or bool(d.at[s,"one_price_down"])):
                    target[s]=w
            total=sum(target.values())
            if total>1: target={s:w/total for s,w in target.items()}
            turnover=sum(abs(target.get(s,0)-current.get(s,0)) for s in set(target)|set(current))
            net*=max(0,1-turnover*ONE_WAY_COST); current=target; pending=None
        rows.append({"date":date,"gross_nav":gross,"net_nav":net,"turnover":turnover,
                     "exposure":sum(current.values()),"positions":len(current)})
        if i%rebalance==rebalance-1:
            rank=d[d[score].notna()].sort_values(score,ascending=False)
            buffer=set(rank.head(buffer_n).index)
            keep=[s for s in current if s in buffer]
            add=[s for s in rank.index if s not in keep][:(top_n-len(keep))]
            names=(keep+add)[:top_n]
            pending={s:1/top_n for s in names}
    c=pd.DataFrame(rows); c["net_return"]=c.net_nav.pct_change().fillna(0)
    return c,metrics(c)


def main():
    OUT.mkdir(parents=True,exist_ok=True); print("loading feature panel",flush=True)
    x=load_features(); meta=[]
    for h in HORIZONS: meta.extend(train_predict(x,h))
    x["ml_ensemble"]=x[[f"ml{h}" for h in HORIZONS]].rank(pct=True).mean(axis=1)
    pd.DataFrame(meta).to_csv(OUT/"model_year_rank_ic.csv",index=False,encoding="utf-8-sig")
    configs=[
      ("ml5_base","ml5",30,60,20),
      ("ml5_concentrated","ml5",15,45,10),
      ("ml5_patient","ml5",50,150,40),
      ("ml10_patient","ml10",50,150,40),
      ("ml20_patient","ml20",50,150,60),
      ("ensemble_patient","ml_ensemble",40,120,40),
    ]
    results=[]
    for name,score,top,buffer,rebalance in configs:
        print(f"backtest {name}",flush=True)
        curve,m=simulate_buffer(x,score,top,buffer,rebalance)
        m.update({"strategy":name,"score":score,"top_n":top,
                  "buffer_n":buffer,"rebalance":rebalance}); results.append(m)
        curve.to_parquet(OUT/f"{name}_curve.parquet",index=False)
    result=pd.DataFrame(results).sort_values("annualized_return",ascending=False)
    result.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(result.to_string(index=False))

if __name__=="__main__":main()
