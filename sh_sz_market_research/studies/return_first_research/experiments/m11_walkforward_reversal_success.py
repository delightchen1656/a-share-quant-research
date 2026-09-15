"""Walk-forward second-stage model for Q3 reversal success and adverse excursion."""
from pathlib import Path
import sys
import lightgbm as lgb
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m5_opportunity_quality_gates import quality_table  # noqa
from m10_position_risk_weighting import run  # noqa
from m2_simple_baselines import metrics  # noqa
OUT=STUDY/"reports"/"m11_walkforward_reversal_success"
FEATURES=["ret5","ret20","ret60","ret120","vol20","vol60","position60","liq_ratio","amount20","beta60","residual20","ivol20","max20"]

def forward_min(s,n=40):
    return s.shift(-1)[::-1].rolling(n,min_periods=n).min()[::-1]

def build():
    x,_,_=prepare();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
    x["idio1"]=x.ret1-x.beta60*x.idx1;x["ivol20"]=g.idio1.transform(lambda s:s.rolling(20).std())
    x["max20"]=g.ret1.transform(lambda s:s.rolling(20).max())
    entry=g.qfq_close.shift(-1);x["future40"]=g.qfq_close.shift(-40)/entry-1
    x["mae40"]=g.qfq_close.transform(forward_min)/entry-1
    # Success means positive 40-day return without first suffering an 8% close-to-close loss.
    x["success40"]=((x.future40>0)&(x.mae40>-.08)).astype(float)
    x.loc[x.future40.isna()|x.mae40.isna(),"success40"]=np.nan;x["ml_success"]=np.nan
    rng=np.random.default_rng(20260914);meta=[]
    for year in range(2021,2027):
        begin=pd.Timestamp(max(2018,year-3),1,1);cutoff=pd.Timestamp(year-1,12,1)
        train=x[x.date.between(begin,cutoff)&x.Q3_trend_residual.notna()].dropna(subset=FEATURES+["success40"])
        if len(train)>300000:train=train.iloc[rng.choice(len(train),300000,replace=False)]
        test=x[(x.date.dt.year==year)&x.Q3_trend_residual.notna()&x[FEATURES].notna().all(axis=1)]
        model=lgb.LGBMClassifier(n_estimators=220,learning_rate=.03,num_leaves=20,max_depth=6,min_child_samples=350,
            subsample=.8,colsample_bytree=.8,reg_lambda=10,reg_alpha=3,verbosity=-1,n_jobs=-1,random_state=year)
        model.fit(train[FEATURES],train.success40)
        pred=model.predict_proba(test[FEATURES])[:,1];x.loc[test.index,"ml_success"]=pred
        actual=x.loc[test.index,"success40"];valid=actual.notna();auc=np.nan
        if valid.any():
            from sklearn.metrics import roc_auc_score
            auc=roc_auc_score(actual[valid],pred[valid])
        meta.append({"year":year,"train_begin":begin,"label_cutoff":cutoff,"train_rows":len(train),"test_rows":len(test),"auc":auc,"base_rate":train.success40.mean()})
        print(year,len(train),auc,flush=True)
    pd.DataFrame(meta).to_csv(OUT/"model_diagnostics.csv",index=False,encoding="utf-8-sig")
    e=x[x.Q3_trend_residual.notna()&x.ml_success.notna()].copy();d=e.groupby("date")
    e["base_rank"]=d.Q3_trend_residual.rank(pct=True);e["ml_rank"]=d.ml_success.rank(pct=True)
    e["score_ml_only"]=e.ml_rank
    e["score_blend_25"]=.75*e.base_rank+.25*e.ml_rank
    e["score_blend_50"]=.50*e.base_rank+.50*e.ml_rank
    e["score_blend_75"]=.25*e.base_rank+.75*e.ml_rank
    x=x.merge(e[["date","symbol","score_ml_only","score_blend_25","score_blend_50","score_blend_75"]],on=["date","symbol"],how="left")
    return x

def main():
    OUT.mkdir(parents=True,exist_ok=True);x=build();quality,cuts=quality_table(x);quality=quality.reindex(pd.DatetimeIndex(sorted(x.date.unique()))).ffill();rows=[]
    configs=[("base","Q3_trend_residual"),("ml_only","score_ml_only"),("blend25","score_blend_25"),("blend50","score_blend_50"),("blend75","score_blend_75")]
    original=x.Q3_trend_residual.copy()
    for name,score in configs:
        print(name,flush=True);x["Q3_trend_residual"]=x[score] if score in x else original
        c=run(x,quality,cuts,"inv_ivol");c.to_parquet(OUT/f"{name}_curve.parquet",index=False)
        for period,start,end in [("设计期2021-2023","2021-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期2021-2026","2021-01-01","2026-08-31")]:
            z=c[c.date.between(start,end)].copy();z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod();z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod();z["net_return"]=z.net_nav.pct_change().fillna(0)
            m=metrics(z);m.update({"strategy":name,"period":period});rows.append(m)
    r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期2021-2026"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())

if __name__=="__main__":main()
