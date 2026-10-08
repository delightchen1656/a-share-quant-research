"""Train 20/40/60-session return and adverse-excursion models for pool >=1."""
from __future__ import annotations
import json, zlib
from pathlib import Path
import joblib, lightgbm as lgb
import numpy as np, pandas as pd

HERE=Path(__file__).resolve().parent; PROJECT=HERE.parents[1]
DATA=PROJECT/"data_pipeline"/"data"; FD=DATA/"derived"/"features"; Q=DATA/"qfq"
EVENTS=PROJECT/"studies"/"rapid_rally_10d50"/"outputs"/"event_details.csv"
OUT=HERE/"outputs"/"trend_models"; MOD=HERE/"models"/"trend"
FEATURES=["ret5","ret20","ret60","range20","range60","dd20","vol20","vol60","volume_ratio",
 "volume_cv","up_volume_share","pv_corr","close_pos60","turn20","amount20","breakout_gap","rise_from_low60","volume_spike"]

def targets(close,low):
 n=len(close); out={k:np.full(n,np.nan) for k in ("f20","f40","f60","mae20")}
 for h in (20,40,60):
  if n>h: out[f"f{h}"][:n-h]=close[h:]/close[:n-h]-1
 if n>20:
  w=np.lib.stride_tricks.sliding_window_view(low[1:],20)
  out["mae20"][:len(w)]=w.min(axis=1)/close[:len(w)]-1
 return out

def main():
 OUT.mkdir(parents=True,exist_ok=True); MOD.mkdir(parents=True,exist_ok=True)
 ev=pd.read_csv(EVENTS,parse_dates=["end_date"])
 ends={s:np.sort(g.end_date.to_numpy(dtype="datetime64[ns]")) for s,g in ev.groupby("symbol")}
 train=[]; score=[]; paths=list(FD.rglob("*.parquet"))
 for i,p in enumerate(paths,1):
  s=p.stem; x=pd.read_parquet(p,columns=["date","symbol","t1_buyable"]+FEATURES); x.date=pd.to_datetime(x.date)
  q=pd.read_parquet(Q/s[-2:]/f"{s}.parquet",columns=["date","close","low"]); q.date=pd.to_datetime(q.date)
  x=x.merge(q,on="date"); ts=targets(x.close.to_numpy(float),x.low.to_numpy(float))
  for k,v in ts.items(): x[k]=v
  x["past_events"]=np.searchsorted(ends.get(s,np.array([],dtype="datetime64[ns]")),x.date.to_numpy(),side="right")
  good=x.past_events.ge(1)&x.t1_buyable.fillna(False)&x[FEATURES].notna().all(axis=1)
  a=x[good&x.date.le("2023-09-30")].dropna(subset=["f20","f40","f60","mae20"])
  if len(a)>240: a=a.sample(240,random_state=zlib.crc32(s.encode())&0xffffffff)
  if len(a): train.append(a)
  b=x[good&x.date.ge("2024-01-01")&x.date.le("2026-07-31")]
  if len(b): score.append(b[["date","symbol","past_events"]+FEATURES])
  if i%500==0: print(f"loaded {i}/{len(paths)}",flush=True)
 tr=pd.concat(train,ignore_index=True); sc=pd.concat(score,ignore_index=True)
 meta={"train_samples":len(tr),"train_end":"2023-09-30","score_start":"2024-01-01","features":FEATURES}
 for target in ("f20","f40","f60","mae20"):
  y=tr[target].clip(-.50,1.00 if target!="mae20" else 0)
  model=lgb.LGBMRegressor(n_estimators=450,learning_rate=.03,num_leaves=15,max_depth=5,min_child_samples=120,
   subsample=.8,colsample_bytree=.8,reg_lambda=8,reg_alpha=1,random_state=20260914,n_jobs=8,verbosity=-1)
  model.fit(tr[FEATURES].astype("float32"),y)
  sc["pred_"+target]=model.predict(sc[FEATURES].astype("float32"))
  joblib.dump({"model":model,"features":FEATURES,"target":target,"metadata":meta},MOD/f"{target}.joblib",compress=3)
  print(target,"trained",flush=True)
 sc[["date","symbol","past_events"]+FEATURES+["pred_f20","pred_f40","pred_f60","pred_mae20"]].to_parquet(OUT/"trend_scores_2024_2026.parquet",index=False)
 (OUT/"metadata.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps(meta,ensure_ascii=False),flush=True)
if __name__=="__main__":main()
