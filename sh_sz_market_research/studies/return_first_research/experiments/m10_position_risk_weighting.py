"""Risk-aware position weighting inside the fixed Q3-G7 stock selection."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent;STUDY=HERE.parent
sys.path.insert(0,str(HERE))
from m4_residual_reversal import prepare  # noqa
from m5_opportunity_quality_gates import quality_table  # noqa
from m2_simple_baselines import metrics,ONE_WAY_COST  # noqa
OUT=STUDY/"reports"/"m10_position_risk_weighting"

def capped_normalize(raw,total,n,cap_multiple=2.0):
    w=raw.clip(lower=0).fillna(0)
    if w.sum()==0:w[:]=1
    w=w/w.sum()*total; cap=cap_multiple*total/n
    for _ in range(5):
        over=w>cap
        if not over.any():break
        excess=(w[over]-cap).sum();w[over]=cap
        under=~over
        if w[under].sum()>0:w[under]+=excess*w[under]/w[under].sum()
    return w

def raw_weights(q,names,mode):
    d=q.loc[names]
    if mode=="equal":return pd.Series(1.,index=names)
    if mode=="inv_vol":return 1/d.vol60.clip(lower=.004)
    if mode=="inv_ivol":return 1/d.ivol20.clip(lower=.004)
    if mode=="score_invvol":
        s=d.Q3_trend_residual.rank(pct=True).clip(lower=.2);return s/d.vol60.clip(lower=.004)
    if mode=="lowbeta_invvol":return 1/(d.vol60.clip(lower=.004)*(1+d.beta60.clip(lower=0)))
    if mode=="residual_conviction":
        conviction=(-d.residual20).rank(pct=True).clip(lower=.2);return conviction/d.ivol20.clip(lower=.004)
    raise KeyError(mode)

def run(x,quality,cuts,mode):
    z=x[x.date.between("2018-01-01","2026-08-31")];dates=sorted(z.date.unique());days={d:a.set_index("symbol") for d,a in z.groupby("date")}
    current={};pending=None;gross=net=1.;rows=[];top=80;buffer=240
    for i,date in enumerate(dates):
        d=days[date];r=sum(w*float(d.at[s,"ret1"]) for s,w in current.items() if s in d.index and np.isfinite(d.at[s,"ret1"]))
        gross*=1+r;net*=1+r;turnover=0
        if pending is not None:
            target={s:w for s,w in pending.items() if s in d.index and bool(d.at[s,"tradable"]) and not bool(d.at[s,"one_price_up"])}
            for s,w in current.items():
                if s not in target and s in d.index and (not bool(d.at[s,"tradable"]) or bool(d.at[s,"one_price_down"])):target[s]=w
            if sum(target.values())>1:target={s:w/sum(target.values()) for s,w in target.items()}
            turnover=sum(abs(target.get(s,0)-current.get(s,0)) for s in set(target)|set(current));net*=max(0,1-turnover*ONE_WAY_COST);current=target;pending=None
        rows.append({"date":date,"gross_nav":gross,"net_nav":net,"turnover":turnover,"exposure":sum(current.values()),"positions":len(current)})
        if i%40==39:
            ranked=d[d.Q3_trend_residual.notna()].sort_values("Q3_trend_residual",ascending=False)
            keep=[s for s in current if s in set(ranked.head(buffer).index)];names=(keep+[s for s in ranked.index if s not in keep])[:top]
            q=quality.loc[date];danger=q.market_ret20<cuts["market_ret20"][.35] and q.residual_dispersion<cuts["residual_dispersion"][.35]
            exp=.35 if danger else 1.;raw=raw_weights(d,names,mode);w=capped_normalize(raw,exp,top)
            pending=w.to_dict()
    c=pd.DataFrame(rows);c["net_return"]=c.net_nav.pct_change().fillna(0);return c

def main():
    OUT.mkdir(parents=True,exist_ok=True);x,_,_=prepare();x=x.sort_values(["symbol","date"]);g=x.groupby("symbol",sort=False)
    x["idio1"]=x.ret1-x.beta60*x.idx1;x["ivol20"]=g.idio1.transform(lambda s:s.rolling(20).std())
    quality,cuts=quality_table(x);quality=quality.reindex(pd.DatetimeIndex(sorted(x.date.unique()))).ffill();rows=[]
    for mode in ["equal","inv_vol","inv_ivol","score_invvol","lowbeta_invvol","residual_conviction"]:
        print(mode,flush=True);c=run(x,quality,cuts,mode);c.to_parquet(OUT/f"{mode}_curve.parquet",index=False)
        for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
            z=c[c.date.between(start,end)].copy();z["gross_nav"]=(1+z.gross_nav.pct_change().fillna(0)).cumprod();z["net_nav"]=(1+z.net_nav.pct_change().fillna(0)).cumprod();z["net_return"]=z.net_nav.pct_change().fillna(0)
            m=metrics(z);m.update({"mode":mode,"period":period});rows.append(m)
    r=pd.DataFrame(rows);r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig");print(r[r.period=="全周期"].sort_values("sharpe",ascending=False).to_string(index=False));print(r.pivot(index="mode",columns="period",values="annualized_return").to_string())

if __name__=="__main__":main()
