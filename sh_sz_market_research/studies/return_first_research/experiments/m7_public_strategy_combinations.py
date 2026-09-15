"""Combine current Q3-G7 core with independently reproduced anti-MAX sleeve."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent; STUDY = HERE.parent
CORE = STUDY / "reports" / "m6_asymmetric_risk_state" / "blends" / "40日75_10日25_curve.parquet"
ANTI = STUDY / "reports" / "m7_public_strategy_reproductions" / "P1_anti_max_ivol_curve.parquet"
OUT = STUDY / "reports" / "m7_public_strategy_combinations"
SWITCH_COST = .003


def load():
    a = pd.read_parquet(CORE).sort_values("date")[["date", "return", "exposure"]]
    b = pd.read_parquet(ANTI).sort_values("date")
    b["anti_return"] = b.net_nav.pct_change().fillna(0)
    return a.merge(b[["date", "anti_return", "exposure"]].rename(columns={"exposure": "anti_exposure"}), on="date")


def stats(z):
    nav = (1 + z["return"]).cumprod(); days = max((z.date.iloc[-1] - z.date.iloc[0]).days, 1)
    return {"final_nav": nav.iloc[-1], "annualized_return": nav.iloc[-1] ** (365.25/days) - 1,
            "max_drawdown": (nav/nav.cummax()-1).min(),
            "sharpe": np.sqrt(252)*z["return"].mean()/z["return"].std(),
            "average_core_weight": z.core_weight.mean()}


def make_strategy(x, name):
    if name.startswith("静态"):
        w = float(name.split("_")[1]) / 100
        weight = pd.Series(w, index=x.index)
    else:
        core_nav = (1+x["return"]).cumprod(); anti_nav = (1+x.anti_return).cumprod()
        if name == "因子动量60":
            lead = core_nav.pct_change(60) >= anti_nav.pct_change(60)
            raw = lead.map({True:.80, False:.20})
        elif name == "因子动量120":
            lead = core_nav.pct_change(120) >= anti_nav.pct_change(120)
            raw = lead.map({True:.80, False:.20})
        elif name == "双袖套逆波动":
            vc = x["return"].rolling(60).std().clip(lower=.002)
            va = x.anti_return.rolling(60).std().clip(lower=.002)
            raw = (1/vc)/((1/vc)+(1/va))
            raw = raw.clip(.30,.85)
        else: raise KeyError(name)
        # Review every 20 trading days. Shift one day to preserve T+1 execution.
        review = pd.Series(False, index=x.index); review.iloc[119::20] = True
        weight = raw.where(review).ffill().shift(1).fillna(.75)
    switch = weight.diff().abs().fillna(0)
    y = pd.DataFrame({"date": x.date, "core_weight": weight})
    y["return"] = weight*x["return"] + (1-weight)*x.anti_return - switch*SWITCH_COST
    return y


def main():
    OUT.mkdir(parents=True, exist_ok=True); x = load(); rows=[]
    names = ["静态_100", "静态_90", "静态_80", "静态_70", "静态_50", "因子动量60", "因子动量120", "双袖套逆波动"]
    for name in names:
        y=make_strategy(x,name); y.to_parquet(OUT/f"{name}_curve.parquet",index=False)
        for period,start,end in [("设计期2018-2023","2018-01-01","2023-12-31"),
                                 ("验证期2024","2024-01-01","2024-12-31"),
                                 ("验证期2025-2026-08","2025-01-01","2026-08-31"),
                                 ("全周期","2018-01-01","2026-08-31")]:
            z=y[y.date.between(start,end)].copy(); m=stats(z); m.update({"strategy":name,"period":period}); rows.append(m)
    r=pd.DataFrame(rows); r.to_csv(OUT/"results.csv",index=False,encoding="utf-8-sig")
    r.pivot(index="strategy",columns="period",values=["annualized_return","max_drawdown","sharpe"]).to_csv(OUT/"comparison.csv",encoding="utf-8-sig")
    print(r[r.period=="全周期"].sort_values("annualized_return",ascending=False).to_string(index=False))
    print("\nPERIOD RETURNS\n",r.pivot(index="strategy",columns="period",values="annualized_return").to_string())
    print("\nDAILY CORRELATION",x["return"].corr(x.anti_return))


if __name__ == "__main__": main()
