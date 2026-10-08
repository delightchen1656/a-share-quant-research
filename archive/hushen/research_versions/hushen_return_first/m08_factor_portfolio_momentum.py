"""Factor-portfolio momentum using only previously realised sleeve returns."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent
OUT=STUDY/"reports"/"m8_factor_portfolio_momentum"; COST=.003
FILES={
 "core":STUDY/"reports"/"m6_asymmetric_risk_state"/"M0_40日二元_curve.parquet",
 "anti_max":STUDY/"reports"/"m7_public_strategy_reproductions"/"P1_anti_max_ivol_curve.parquet",
 "resrev_lottery":STUDY/"reports"/"m7_public_strategy_reproductions"/"P2_resrev_anti_lottery_curve.parquet",
 "max_reversal":STUDY/"reports"/"m7_public_strategy_reproductions"/"P5_max_reversal_curve.parquet",
 "r8":STUDY/"reports"/"m3_reversal_regime"/"R8_低波反转分散40_curve.parquet",
}

def load():
    out=None
    for name,path in FILES.items():
        z=pd.read_parquet(path).sort_values("date"); z[name]=z.net_nav.pct_change().fillna(0)
        out=z[["date",name]] if out is None else out.merge(z[["date",name]],on="date")
    return out

def weights(x,name):
    assets=list(FILES); n=len(x); w=pd.DataFrame(0.,index=x.index,columns=assets)
    nav=(1+x[assets]).cumprod(); mom60=nav.pct_change(60); mom120=nav.pct_change(120)
    vol60=x[assets].rolling(60).std().clip(lower=.002)
    review=set(range(119,n,20)); current=pd.Series(1/len(assets),index=assets)
    for i in range(n):
        if i in review:
            if name=="F0_等权": current[:]=1/len(assets)
            else:
                if name=="F1_因子动量60": score=mom60.iloc[i]
                elif name=="F2_因子动量120": score=mom120.iloc[i]
                elif name=="F3_风险调整动量": score=mom120.iloc[i]/vol60.iloc[i]
                elif name=="F4_双周期动量": score=.5*mom60.iloc[i]+.5*mom120.iloc[i]
                elif name=="F5_核心锚定":
                    score=.5*mom60.iloc[i]+.5*mom120.iloc[i]; current[:]=0; current["core"]=.5
                    for a in score.drop("core").nlargest(2).index: current[a]=.25
                    w.iloc[i]=current; continue
                current[:]=0
                for a in score.nlargest(2).index: current[a]=.5
        w.iloc[i]=current
    return w.shift(1).fillna(1/len(assets))

def stats(y):
    nav=(1+y["return"]).cumprod(); days=max((y.date.iloc[-1]-y.date.iloc[0]).days,1); r=y["return"]
    return {"final_nav":nav.iloc[-1],"annualized_return":nav.iloc[-1]**(365.25/days)-1,
            "max_drawdown":(nav/nav.cummax()-1).min(),"sharpe":np.sqrt(252)*r.mean()/r.std()}

def main():
    OUT.mkdir(parents=True,exist_ok=True); x=load(); rows=[]
    for name in ["F0_等权","F1_因子动量60","F2_因子动量120","F3_风险调整动量","F4_双周期动量","F5_核心锚定"]:
        w=weights(x,name); switch=w.diff().abs().sum(axis=1).fillna(0)
        y=pd.DataFrame({"date":x.date,"return":((w*x[list(FILES)]).sum(axis=1)-switch*COST)})
        y.to_parquet(OUT/f"{name}_curve.parquet",index=False)
        for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),("验证期2024","2024-01-01","2024-12-31"),
                                 ("验证期2025-2026-08","2025-01-01","2026-08-31"),("全周期","2018-01-01","2026-08-31")]:
            m=stats(y[y.date.between(start,end)]); m.update({"strategy":name,"period":period}); rows.append(m)
    r=pd.DataFrame(rows); r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    print(r[r.period=="全周期"].sort_values("annualized_return",ascending=False).to_string(index=False))
    print(r.pivot(index="strategy",columns="period",values="annualized_return").to_string())

if __name__=="__main__":main()
