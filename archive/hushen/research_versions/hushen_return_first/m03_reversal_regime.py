"""Reversal and market-regime routes derived from factor diagnostics."""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; STUDY=HERE.parent; PROJECT=STUDY.parents[1]
sys.path.insert(0,str(HERE))
from m2_simple_baselines import load_features, metrics, ONE_WAY_COST  # noqa
OUT=STUDY/"reports"/"m3_reversal_regime"

def build():
    x=load_features(); e=x[x.eligible].copy(); d=e.groupby("date")
    hi=lambda c:d[c].rank(pct=True); lo=lambda c:1-hi(c)
    e["rev_lowrisk"]=.40*lo("ret20")+.30*lo("vol60")+.20*lo("amount20")+.10*lo("liq_ratio")
    e["rev_confirm"]=(.35*lo("ret20")+.25*hi("ret5")+.25*lo("vol60")
                      +.15*lo("amount20")).where((e.ret20<0)&(e.ret5>0))
    e["long_reversal"]=(.40*lo("ret120")+.25*hi("ret5")+.20*lo("vol60")
                        +.15*lo("amount20")).where((e.ret120<0)&(e.ret5>0))
    x=x.merge(e[["date","symbol","rev_lowrisk","rev_confirm","long_reversal"]],
              on=["date","symbol"],how="left")
    idx=pd.read_parquet(PROJECT/"data_pipeline"/"data"/"indices"/"000905.SH.parquet")
    idx.date=pd.to_datetime(idx.date); c=pd.to_numeric(idx.close,errors="coerce")
    state=pd.DataFrame({"date":idx.date,"idx20":c.pct_change(20),
                        "above120":c>c.rolling(120).mean()}).set_index("date")
    return x,state

def simulate(x,state,score,regime="none",top_n=50,buffer_n=150,rebalance=20):
    z=x[x.date.between("2018-01-01","2026-08-31")]; dates=sorted(z.date.unique())
    days={date:a.set_index("symbol") for date,a in z.groupby("date")}
    current={}; pending=None; gross=net=1.; rows=[]
    for i,date in enumerate(dates):
        d=days[date]
        r=sum(w*float(d.at[s,"ret1"]) for s,w in current.items()
              if s in d.index and np.isfinite(d.at[s,"ret1"]))
        gross*=1+r; net*=1+r; turnover=0
        if pending is not None:
            target={s:w for s,w in pending.items() if s in d.index and bool(d.at[s,"tradable"])
                    and not bool(d.at[s,"one_price_up"])}
            for s,w in current.items():
                if s not in target and s in d.index and (not bool(d.at[s,"tradable"]) or bool(d.at[s,"one_price_down"])):
                    target[s]=w
            if sum(target.values())>1: target={s:w/sum(target.values()) for s,w in target.items()}
            turnover=sum(abs(target.get(s,0)-current.get(s,0)) for s in set(target)|set(current))
            net*=max(0,1-turnover*ONE_WAY_COST); current=target; pending=None
        rows.append({"date":date,"gross_nav":gross,"net_nav":net,"turnover":turnover,
                     "exposure":sum(current.values()),"positions":len(current)})
        if i%rebalance==rebalance-1:
            q=days[date]; ranked=q[q[score].notna()].sort_values(score,ascending=False)
            keep=[s for s in current if s in set(ranked.head(buffer_n).index)]
            names=(keep+[s for s in ranked.index if s not in keep])[:top_n]
            st=state.loc[date] if date in state.index else None
            exposure=1.0
            if regime=="soft" and st is not None and not (bool(st.above120) or st.idx20>.03): exposure=.35
            if regime=="hard" and st is not None and not (bool(st.above120) or st.idx20>.03): exposure=0
            pending={s:exposure/top_n for s in names}
    c=pd.DataFrame(rows); c["net_return"]=c.net_nav.pct_change().fillna(0)
    return c,metrics(c)

def main():
    OUT.mkdir(parents=True,exist_ok=True); x,state=build()
    configs=[("R1_低波反转","rev_lowrisk","none",50,150,20),
             ("R2_反转确认","rev_confirm","none",50,150,20),
             ("R3_长期反转确认","long_reversal","none",50,150,20),
             ("R4_低波反转软择时","rev_lowrisk","soft",50,150,20),
             ("R5_低波反转硬择时","rev_lowrisk","hard",50,150,20),
             ("R6_低波反转耐心40","rev_lowrisk","none",50,200,40),
             ("R7_低波反转耐心60","rev_lowrisk","none",50,300,60),
             ("R8_低波反转分散40","rev_lowrisk","none",80,240,40)]
    rows=[]
    for name,score,regime,top,buffer,rebalance in configs:
        print(name,flush=True); c,m=simulate(x,state,score,regime,top,buffer,rebalance)
        m.update({"strategy":name,"top_n":top,"buffer_n":buffer,"rebalance":rebalance})
        rows.append(m); c.to_parquet(OUT/f"{name}_curve.parquet",index=False)
    r=pd.DataFrame(rows).sort_values("annualized_return",ascending=False)
    r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig"); print(r.to_string(index=False))

if __name__=="__main__":main()
