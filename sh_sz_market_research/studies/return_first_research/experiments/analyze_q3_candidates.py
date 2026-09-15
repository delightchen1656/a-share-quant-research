"""Robustness review for residual-reversal candidates and a fixed capital blend."""
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
SOURCE = STUDY / "reports" / "m4_residual_reversal"
OUT = STUDY / "reports" / "m4_q3_candidate_review"

CANDIDATES = {
    "Q3平衡80只40日": "Q3_trend_residual_curve.parquet",
    "Q3分散100只40日": "Q3_trend_residual_100x40_curve.parquet",
    "Q3进攻50只60日": "Q3_trend_residual_50x60_curve.parquet",
}


def daily_returns(path):
    z = pd.read_parquet(path).copy()
    z["date"] = pd.to_datetime(z["date"])
    z = z.sort_values("date")
    z["return"] = z["net_nav"].pct_change().fillna(0.0)
    return z[["date", "return", "exposure", "turnover"]]


def stats(z):
    r = z["return"].fillna(0.0)
    days = max((z.date.iloc[-1] - z.date.iloc[0]).days, 1)
    nav = (1 + r).cumprod()
    total = nav.iloc[-1] - 1
    return {
        "start": z.date.iloc[0], "end": z.date.iloc[-1],
        "final_nav": nav.iloc[-1], "total_return": total,
        "annualized_return": (1 + total) ** (365.25 / days) - 1,
        "max_drawdown": (nav / nav.cummax() - 1).min(),
        "sharpe": np.sqrt(252) * r.mean() / r.std() if r.std() else 0,
        "average_exposure": z.exposure.mean() if "exposure" in z else np.nan,
        "turnover": z.turnover.sum() if "turnover" in z else np.nan,
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    curves = {name: daily_returns(SOURCE / file) for name, file in CANDIDATES.items()}
    # Static capital-sleeve blend: no hindsight switching and no periodic rebalancing.
    left = curves["Q3平衡80只40日"].set_index("date")
    right = curves["Q3进攻50只60日"].set_index("date")
    blend = left.copy()
    blend["return"] = 0.5 * left["return"] + 0.5 * right["return"]
    blend["exposure"] = 0.5 * left["exposure"] + 0.5 * right["exposure"]
    blend["turnover"] = 0.5 * left["turnover"] + 0.5 * right["turnover"]
    curves["Q3平衡进攻各半"] = blend.reset_index()

    periods = [(str(y), f"{y}-01-01", f"{y}-12-31") for y in range(2018, 2027)]
    periods += [("阶段1_2018-2023", "2018-01-01", "2023-12-31"),
                ("阶段2_2024", "2024-01-01", "2024-12-31"),
                ("2025-2026-08", "2025-01-01", "2026-08-31"),
                ("全周期", "2018-01-01", "2026-08-31")]
    rows = []
    concentration = []
    for name, c in curves.items():
        for period, start, end in periods:
            z = c[c.date.between(start, end)]
            if len(z) < 2:
                continue
            m = stats(z); m.update({"strategy": name, "period": period}); rows.append(m)
        years = max((c.date.iloc[-1] - c.date.iloc[0]).days / 365.25, 1 / 252)
        for n in (0, 5, 10, 20):
            r = c["return"].copy()
            if n:
                r.loc[r.nlargest(n).index] = 0
            nav = (1 + r).prod()
            concentration.append({"strategy": name, "removed_best_days": n,
                                  "final_nav": nav, "annualized_return": nav ** (1 / years) - 1})
    period_df = pd.DataFrame(rows)
    period_df.to_csv(OUT / "period_metrics.csv", index=False, encoding="utf-8-sig")
    conc_df = pd.DataFrame(concentration)
    conc_df.to_csv(OUT / "best_day_concentration.csv", index=False, encoding="utf-8-sig")
    wide = period_df.pivot(index="period", columns="strategy", values="annualized_return")
    wide.to_csv(OUT / "annualized_by_period.csv", encoding="utf-8-sig")
    print(period_df[period_df.period.isin(["阶段1_2018-2023", "阶段2_2024", "2025-2026-08", "全周期"])][
        ["strategy", "period", "annualized_return", "max_drawdown", "sharpe"]].to_string(index=False))
    print("\nBEST-DAY CONCENTRATION")
    print(conc_df.to_string(index=False))


if __name__ == "__main__":
    main()
