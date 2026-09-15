"""Local reproductions of public A-share price/volume strategy ideas.

These are logic reproductions, not copied performance claims. All rankings use
T-close information and the common simulator executes the target from T+1.
"""
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent; STUDY = HERE.parent
sys.path.insert(0, str(HERE))
from m3_reversal_regime import simulate  # noqa
from m4_residual_reversal import prepare  # noqa

OUT = STUDY / "reports" / "m7_public_strategy_reproductions"


def build_public_scores():
    x, state, _ = prepare()
    x = x.sort_values(["symbol", "date"])
    g = x.groupby("symbol", sort=False)
    # China MAX / lottery effect: previous-month maximum daily return.
    x["max20"] = g.ret1.transform(lambda s: s.rolling(20).max())
    # Point-in-time idiosyncratic volatility relative to CSI 500.
    x["idio1"] = x.ret1 - x.beta60 * x.idx1
    x["ivol20"] = g.idio1.transform(lambda s: s.rolling(20).std())
    x["risk_adjusted_mom60"] = x.ret60 / x.vol60.clip(lower=.003)
    e = x[x.eligible].copy(); d = e.groupby("date")
    hi = lambda c: d[c].rank(pct=True)
    lo = lambda c: 1 - hi(c)

    # Published anomaly family: avoid lottery-like MAX and high IVOL stocks.
    e["P1_anti_max_ivol"] = .40*lo("max20") + .35*lo("ivol20") + .25*lo("vol60")
    # Residual reversal combined with anti-lottery quality.
    e["P2_resrev_anti_lottery"] = (.35*lo("residual20") + .25*lo("max20")
        + .25*lo("ivol20") + .15*lo("amount20")).where(e.ret120 > 0)
    # Public volume-price-quality recipe, restricted to positive momentum.
    e["P3_volume_price_quality"] = (.35*hi("liq_ratio") + .30*hi("ret60")
        + .20*lo("vol60") + .15*lo("amount20")).where((e.ret20 > .03) & (e.ret60 > 0))
    # Volatility-adjusted trend / time-series strength family.
    e["P4_risk_adjusted_trend"] = (.55*hi("risk_adjusted_mom60")
        + .25*hi("position60") + .20*lo("vol60")).where((e.ret60 > 0) & (e.ret20 < .25))
    # Anti-lottery plus monthly reversal without residual construction.
    e["P5_max_reversal"] = (.45*lo("ret20") + .30*lo("max20")
        + .25*lo("ivol20")).where(e.ret120 > 0)
    cols = [c for c in e.columns if c.startswith("P")]
    return x.merge(e[["date", "symbol"] + cols], on=["date", "symbol"], how="left"), state, cols


def periods(curve):
    from m2_simple_baselines import metrics
    result = []
    for period, start, end in [("设计期2018-2023", "2018-01-01", "2023-12-31"),
                               ("验证期2024", "2024-01-01", "2024-12-31"),
                               ("验证期2025-2026-08", "2025-01-01", "2026-08-31"),
                               ("全周期", "2018-01-01", "2026-08-31")]:
        z = curve[curve.date.between(start, end)].copy()
        z["gross_nav"] = (1 + z.gross_nav.pct_change().fillna(0)).cumprod()
        z["net_nav"] = (1 + z.net_nav.pct_change().fillna(0)).cumprod()
        z["net_return"] = z.net_nav.pct_change().fillna(0)
        m = metrics(z); m["period"] = period; result.append(m)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    x, state, cols = build_public_scores(); rows = []
    configs = {
        "P1_anti_max_ivol": (80, 240, 40),
        "P2_resrev_anti_lottery": (80, 240, 40),
        "P3_volume_price_quality": (50, 200, 20),
        "P4_risk_adjusted_trend": (50, 200, 20),
        "P5_max_reversal": (80, 240, 40),
    }
    for score in cols:
        top, buffer, rebalance = configs[score]
        print(score, flush=True)
        c, _ = simulate(x, state, score, "none", top, buffer, rebalance)
        c.to_parquet(OUT / f"{score}_curve.parquet", index=False)
        for m in periods(c):
            m.update({"strategy": score, "top_n": top, "buffer_n": buffer, "rebalance": rebalance})
            rows.append(m)
    result = pd.DataFrame(rows); result.to_csv(OUT / "results.csv", index=False, encoding="utf-8-sig")
    result.pivot(index="strategy", columns="period", values=["annualized_return", "max_drawdown", "sharpe"]).to_csv(
        OUT / "comparison.csv", encoding="utf-8-sig")
    print(result[result.period == "全周期"].sort_values("annualized_return", ascending=False).to_string(index=False))
    print("\nPERIOD RETURNS\n", result.pivot(index="strategy", columns="period", values="annualized_return").to_string())


if __name__ == "__main__": main()
