"""Static capital-sleeve blends of 40-day and 10-day G7 risk review."""
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent; STUDY = HERE.parent
SOURCE = STUDY / "reports" / "m6_asymmetric_risk_state"
OUT = SOURCE / "blends"


def stats(z):
    nav = (1 + z["return"]).cumprod(); days = max((z.date.iloc[-1] - z.date.iloc[0]).days, 1)
    return {"final_nav": nav.iloc[-1], "annualized_return": nav.iloc[-1] ** (365.25 / days) - 1,
            "max_drawdown": (nav / nav.cummax() - 1).min(),
            "sharpe": np.sqrt(252) * z["return"].mean() / z["return"].std(),
            "average_exposure": z.exposure.mean()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    a = pd.read_parquet(SOURCE / "M0_40日二元_curve.parquet").sort_values("date")
    b = pd.read_parquet(SOURCE / "M2_10日二元_curve.parquet").sort_values("date")
    a["r"] = a.net_nav.pct_change().fillna(0); b["r"] = b.net_nav.pct_change().fillna(0)
    rows = []
    for w40 in (0, .25, .5, .75, 1):
        z = pd.DataFrame({"date": a.date, "return": w40 * a.r + (1-w40) * b.r,
                          "exposure": w40 * a.exposure + (1-w40) * b.exposure})
        name = f"40日{int(w40*100)}_10日{int((1-w40)*100)}"
        z.to_parquet(OUT / f"{name}_curve.parquet", index=False)
        for period, start, end in [("设计期2018-2023", "2018-01-01", "2023-12-31"),
                                   ("验证期2024", "2024-01-01", "2024-12-31"),
                                   ("验证期2025-2026-08", "2025-01-01", "2026-08-31"),
                                   ("全周期", "2018-01-01", "2026-08-31")]:
            q = z[z.date.between(start, end)].copy(); m = stats(q)
            m.update({"blend": name, "weight_40d": w40, "period": period}); rows.append(m)
    result = pd.DataFrame(rows); result.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    print(result[result.period == "全周期"].sort_values("annualized_return", ascending=False).to_string(index=False))
    print(result.pivot(index="blend", columns="period", values="annualized_return").to_string())


if __name__ == "__main__": main()
