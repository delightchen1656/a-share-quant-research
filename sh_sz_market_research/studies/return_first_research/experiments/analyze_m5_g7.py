"""Yearly and extreme-day robustness checks for M5 G7 versus ungated Q3."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
SOURCE = STUDY / "reports" / "m5_opportunity_quality_gates"
OUT = SOURCE / "robustness"
FILES = {"Q3无门控": "G0_无门控_curve.parquet", "Q3机会门控G7": "G7_普跌且低离散_curve.parquet"}


def summarize(z):
    r = z.net_nav.pct_change().fillna(0)
    nav = (1 + r).cumprod()
    days = max((z.date.iloc[-1] - z.date.iloc[0]).days, 1)
    return {"final_nav": nav.iloc[-1], "annualized_return": nav.iloc[-1] ** (365.25 / days) - 1,
            "max_drawdown": (nav / nav.cummax() - 1).min(),
            "sharpe": np.sqrt(252) * r.mean() / r.std() if r.std() else 0,
            "average_exposure": z.exposure.mean(), "turnover": z.turnover.sum()}


def main():
    OUT.mkdir(parents=True, exist_ok=True); rows = []; concentration = []
    for strategy, file in FILES.items():
        c = pd.read_parquet(SOURCE / file); c.date = pd.to_datetime(c.date)
        for year, z in c.groupby(c.date.dt.year):
            m = summarize(z); m.update({"strategy": strategy, "year": int(year)}); rows.append(m)
        r = c.net_nav.pct_change().fillna(0)
        years = (c.date.iloc[-1] - c.date.iloc[0]).days / 365.25
        for n in (0, 5, 10, 20):
            q = r.copy()
            if n: q.loc[q.nlargest(n).index] = 0
            nav = (1 + q).prod()
            concentration.append({"strategy": strategy, "removed_best_days": n,
                                  "final_nav": nav, "annualized_return": nav ** (1 / years) - 1})
    years = pd.DataFrame(rows); years.to_csv(OUT / "yearly_metrics.csv", index=False, encoding="utf-8-sig")
    conc = pd.DataFrame(concentration); conc.to_csv(OUT / "best_day_concentration.csv", index=False, encoding="utf-8-sig")
    print(years.pivot(index="year", columns="strategy", values="annualized_return").to_string())
    print("\nCONCENTRATION\n", conc.to_string(index=False))


if __name__ == "__main__": main()
