"""Public-idea-inspired Sharpe improvements on top of Baseline 3-1 and 2-2.

This is a structure test, not a parameter sweep.  Each candidate represents one
distinct idea and all observable state is shifted by one trading day.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parent / "archive/optimization_studies/sharpe_frontier_20260911/aligned_daily_returns.csv"
OUT = ROOT.parent / "archive/optimization_studies/sharpe_public_structures_20260911"
COST = 0.001
PERIODS = {
    "design": ("2020-01-01", "2024-12-31"),
    "recent": ("2025-01-01", "2026-07-31"),
    "full": ("2020-01-01", "2026-07-31"),
}


def stats(r: pd.Series) -> dict:
    r = r.fillna(0.0)
    nav = (1.0 + r).cumprod()
    years = max((r.index[-1] - r.index[0]).days / 365.25, 1 / 12)
    sd = r.std(ddof=1)
    return {
        "cagr": float(nav.iloc[-1] ** (1 / years) - 1),
        "sharpe": float(r.mean() / sd * np.sqrt(252)) if sd > 0 else 0.0,
        "mdd": float((nav / nav.cummax() - 1).min()),
        "vol": float(sd * np.sqrt(252)),
        "final": float(nav.iloc[-1] * 1_000_000),
    }


def net(core: pd.Series, exposure: pd.Series, weight: pd.Series | None = None) -> pd.Series:
    exposure = exposure.clip(0, 1).fillna(0.5)
    turnover = exposure.diff().abs().fillna(0)
    if weight is not None:
        turnover = turnover + exposure * weight.diff().abs().fillna(0)
    return exposure * core - COST * turnover


def candidates(df: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    a, d = df.attack, df.defense
    core50 = 0.5 * a + 0.5 * d
    core80 = 0.8 * a + 0.2 * d
    out: dict[str, tuple[str, pd.Series]] = {}

    # 1 Conditional volatility targeting: intervene only in extreme vol states.
    vol20 = core50.rolling(20).std() * np.sqrt(252)
    rank252 = vol20.rolling(252, min_periods=126).rank(pct=True).shift(1)
    exp = pd.Series(1.0, index=df.index)
    exp[rank252 >= 0.80] = 0.55
    exp[rank252 <= 0.20] = 0.85
    out["conditional_vol_extremes"] = ("条件波动极端管理", net(core50, exp))

    # 2 EWMA volatility targeting reacts faster than a simple rolling estimate.
    ewma = core50.ewm(span=20, adjust=False).std().shift(1) * np.sqrt(252)
    exp = (0.18 / ewma).clip(0.25, 1.0)
    out["ewma_vol_target"] = ("EWMA波动目标", net(core50, exp))

    # 3 Downside-vol targeting does not punish upside volatility.
    neg = core50.where(core50 < 0, 0.0)
    downvol = neg.rolling(40).std().shift(1) * np.sqrt(252)
    exp = (0.105 / downvol).clip(0.25, 1.0)
    out["downside_vol_target"] = ("下行波动目标", net(core50, exp))

    # 4 Trend-confirmed exposure on the diversified core.
    nav = (1 + core50).cumprod()
    trend = (nav.shift(1) > nav.rolling(100).mean().shift(1))
    exp = trend.astype(float) * 0.55 + 0.35
    out["core_trend_filter"] = ("组合净值趋势确认", net(core50, exp))

    # 5 Dual horizon trend avoids reacting to a single horizon.
    mom20 = nav.pct_change(20).shift(1)
    mom100 = nav.pct_change(100).shift(1)
    score = (mom20 > 0).astype(int) + (mom100 > 0).astype(int)
    exp = score.map({0: 0.30, 1: 0.65, 2: 1.00})
    out["dual_horizon_trend"] = ("双周期趋势敞口", net(core50, exp))

    # 6 Dynamic sleeve selection using trailing risk-adjusted momentum.
    ma = a.rolling(60).mean().shift(1) / a.rolling(60).std().shift(1)
    md = d.rolling(60).mean().shift(1) / d.rolling(60).std().shift(1)
    wa = pd.Series(np.where(ma > md, 0.70, 0.30), index=df.index).fillna(0.5)
    wa = wa.groupby(wa.index.to_period("M")).transform("first")
    core = wa * a + (1 - wa) * d
    out["sleeve_momentum"] = ("收益源风险动量月配", net(core, pd.Series(1.0, index=df.index), wa))

    # 7 Rolling minimum-variance mix, analytically solved for two sleeves.
    va = a.rolling(60).var().shift(1)
    vd = d.rolling(60).var().shift(1)
    cov = a.rolling(60).cov(d).shift(1)
    wa = ((vd - cov) / (va + vd - 2 * cov)).clip(0.2, 0.8).fillna(0.5)
    wa = wa.groupby(wa.index.to_period("M")).transform("first")
    core = wa * a + (1 - wa) * d
    out["minimum_variance"] = ("双源最小方差月配", net(core, pd.Series(1.0, index=df.index), wa))

    # 8 Correlation shock: reduce aggressive concentration when sleeves converge.
    corr = a.rolling(40).corr(d).shift(1)
    wa = pd.Series(0.70, index=df.index)
    wa[corr > 0.65] = 0.40
    core = wa * a + (1 - wa) * d
    out["correlation_shock"] = ("相关性冲击降集中", net(core, pd.Series(1.0, index=df.index), wa))

    # 9 Hysteretic drawdown control: slow re-entry to reduce whipsaw.
    nav80 = (1 + core80).cumprod()
    dd = (nav80 / nav80.cummax() - 1).shift(1).fillna(0)
    exp_values, state = [], 1.0
    for x in dd:
        if x <= -0.15:
            state = 0.30
        elif x <= -0.08 and state > 0.60:
            state = 0.60
        elif x >= -0.03:
            state = 1.00
        exp_values.append(state)
    out["drawdown_hysteresis"] = ("回撤迟滞恢复", net(core80, pd.Series(exp_values, index=df.index)))

    # 10 Loss-cluster brake uses only realized portfolio outcomes.
    losses = (core80 < 0).rolling(10).sum().shift(1)
    exp = pd.Series(1.0, index=df.index)
    exp[losses >= 7] = 0.50
    out["loss_cluster_brake"] = ("亏损簇刹车", net(core80, exp))

    # 11 Tail-loss brake based on trailing 5% quantile.
    q05 = core80.rolling(120, min_periods=60).quantile(0.05).shift(1)
    exp = pd.Series(1.0, index=df.index)
    exp[q05 < -0.025] = 0.55
    out["tail_loss_brake"] = ("左尾风险刹车", net(core80, exp))

    # 12 Hybrid: robust 50/50 core, downside risk and trend confirmation.
    trend_scale = pd.Series(np.where(mom100 > 0, 1.0, 0.65), index=df.index)
    risk_scale = (0.12 / downvol).clip(0.35, 1.0)
    exp = pd.concat([trend_scale, risk_scale], axis=1).min(axis=1)
    out["hybrid_downside_trend"] = ("下行风险与趋势联合", net(core50, exp))
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SOURCE, parse_dates=["date"]).set_index("date")
    pool = candidates(df)
    pool["baseline3_1"] = ("基准3-1强势延持", df.attack)
    pool["baseline2_2"] = ("基准2-2升温防守", df.defense)
    rows = []
    for key, (name, r) in pool.items():
        row = {"variant": key, "name_cn": name}
        for p, (start, end) in PERIODS.items():
            for metric, value in stats(r.loc[start:end]).items():
                row[f"{p}_{metric}"] = value
        row["eligible"] = all(0.10 <= abs(row[f"{p}_mdd"]) <= 0.50 for p in PERIODS)
        row["robust_sharpe"] = min(row["design_sharpe"], row["recent_sharpe"])
        rows.append(row)
    ranking = pd.DataFrame(rows).sort_values(
        ["eligible", "robust_sharpe", "recent_sharpe"], ascending=[False, False, False]
    )
    ranking.insert(0, "rank", range(1, len(ranking) + 1))
    ranking.to_csv(OUT / "ranking.csv", index=False, encoding="utf-8-sig")
    eligible = ranking[ranking.eligible]
    best = eligible.iloc[0]
    best_r = pool[best.variant][1]
    pd.DataFrame({"date": best_r.index, "return": best_r.values,
                  "equity": (1 + best_r).cumprod().values * 1_000_000}).to_csv(
        OUT / "winner_curve.csv", index=False, encoding="utf-8-sig")
    meta = {"created_at": "2026-09-11", "cost": COST, "count": len(ranking),
            "objective": "maximize minimum of design and recent Sharpe, MDD 10%-50% in every period",
            "winner": best.to_dict()}
    (OUT / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ranking[["rank", "variant", "name_cn", "design_sharpe", "recent_sharpe",
                   "full_sharpe", "recent_cagr", "full_cagr", "recent_mdd", "full_mdd",
                   "eligible"]].to_string(index=False))


if __name__ == "__main__":
    main()
