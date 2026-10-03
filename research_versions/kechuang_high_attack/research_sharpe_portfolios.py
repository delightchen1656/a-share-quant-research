"""Search risk-adjusted portfolio structures using Baseline 3-1 and Baseline 2-2."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

import research_baseline2 as engine


ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "archive/optimization_studies/sharpe_frontier_20260911"
DEFENSE_CURVE = ROOT.parent / "star_industry_rotation/outputs/baseline45_local/equity_baseline5_full_100w.csv"
OVERLAY_ONE_WAY_COST = 0.001
PERIODS = {
    "design_2020_2024": (pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")),
    "recent_2025_202607": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-31")),
    "full_2020_202607": (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-07-31")),
}


def metrics(returns: pd.Series) -> dict:
    returns = returns.fillna(0.0)
    nav = (1 + returns).cumprod()
    years = max((nav.index[-1] - nav.index[0]).days / 365.25, 1 / 12)
    total = float(nav.iloc[-1] - 1)
    vol = float(returns.std(ddof=1) * np.sqrt(252))
    cagr = float((1 + total) ** (1 / years) - 1)
    sharpe = float(returns.mean() / returns.std(ddof=1) * np.sqrt(252)) if returns.std(ddof=1) > 0 else 0.0
    mdd = float((nav / nav.cummax() - 1).min())
    return {"cagr": cagr, "total_return": total, "max_drawdown": mdd,
            "sharpe": sharpe, "volatility": vol, "final_equity": float(nav.iloc[-1] * 1_000_000)}


def monthly_weights(index, values):
    frame = pd.DataFrame(index=index, columns=["attack", "defense"], dtype=float)
    frame.loc[:, :] = values
    return frame


def candidate_returns(base: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    ra, rd = base.attack, base.defense
    out = {}
    # Direction 1: fixed diversification with daily sleeve rebalancing cost.
    for wa in np.arange(0.10, 1.00, 0.10):
        name = f"fixed_{int(wa*100):02d}_{int((1-wa)*100):02d}"
        gross = wa * ra + (1 - wa) * rd
        post_attack_weight = wa * (1 + ra) / (1 + gross).replace(0, np.nan)
        turnover = (post_attack_weight - wa).abs().fillna(0)
        out[name] = (f"固定日配比 进攻{wa:.0%}/防守{1-wa:.0%}",
                     gross - OVERLAY_ONE_WAY_COST * turnover)
    # Direction 2: trailing inverse-volatility allocation; all inputs lagged one day.
    for lookback in (20, 40, 60, 90):
        vola = ra.rolling(lookback).std().shift(1)
        vold = rd.rolling(lookback).std().shift(1)
        wa = (1 / vola) / (1 / vola + 1 / vold)
        wa = wa.clip(0.15, 0.85).fillna(0.5)
        # Hold weights constant inside each month to keep turnover realistic.
        wa = wa.groupby(wa.index.to_period("M")).transform("first")
        gross = wa * ra + (1 - wa) * rd
        turnover = wa.diff().abs().fillna(0)
        out[f"invvol_{lookback}"] = (f"{lookback}日逆波动月配",
                                      gross - OVERLAY_ONE_WAY_COST * turnover)
    # Direction 3: volatility target applied to several diversified cores; no leverage.
    for wa in (0.35, 0.50, 0.65, 0.80):
        core = wa * ra + (1 - wa) * rd
        for target in (0.12, 0.15, 0.18, 0.22, 0.26):
            realized = core.rolling(20).std().shift(1) * np.sqrt(252)
            exposure = (target / realized).clip(0.20, 1.00).fillna(0.50)
            turnover = exposure.diff().abs().fillna(0)
            out[f"voltarget_{int(wa*100)}_{int(target*100)}"] = (
                f"进攻{wa:.0%}核心+目标波动{target:.0%}",
                exposure * core - OVERLAY_ONE_WAY_COST * turnover
            )
    # Direction 4: gradual drawdown throttle, based only on prior close NAV.
    for wa in (0.50, 0.65, 0.80):
        core = wa * ra + (1 - wa) * rd
        for mild, hard in ((0.08, 0.15), (0.10, 0.18), (0.12, 0.22)):
            nav = (1 + core).cumprod()
            dd = (nav / nav.cummax() - 1).shift(1).fillna(0)
            exposure = pd.Series(1.0, index=core.index)
            exposure[dd <= -mild] = 0.65
            exposure[dd <= -hard] = 0.30
            turnover = exposure.diff().abs().fillna(0)
            out[f"dd_{int(wa*100)}_{int(mild*100)}_{int(hard*100)}"] = (
                f"进攻{wa:.0%}核心+回撤{mild:.0%}/{hard:.0%}降仓",
                exposure * core - OVERLAY_ONE_WAY_COST * turnover
            )
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    engine.THRESHOLD = 0.63
    engine.SIGNAL_THRESHOLD = 0.63
    prep, _ = engine.prepare()
    result, attack_curve, _ = engine.simulate(
        prep, {"stop_risk_filter", "trend_adaptive_expiry"},
        pd.Timestamp("2020-01-01"), pd.Timestamp("2026-07-31")
    )
    defense_curve = pd.read_csv(DEFENSE_CURVE, parse_dates=["date"])
    attack = attack_curve.set_index("date").equity.pct_change().fillna(0).rename("attack")
    defense = defense_curve.set_index("date").equity.pct_change().fillna(0).rename("defense")
    base = pd.concat([attack, defense], axis=1, join="inner").fillna(0)
    base.to_csv(OUT / "aligned_daily_returns.csv", encoding="utf-8-sig")
    candidates = candidate_returns(base)
    candidates["baseline3_1"] = ("基准3-1强势延持", base.attack)
    candidates["baseline2_2"] = ("基准2-2升温防守", base.defense)
    rows = []
    for variant, (name, returns) in candidates.items():
        row = {"variant": variant, "name_cn": name}
        for period, (start, end) in PERIODS.items():
            value = metrics(returns.loc[start:end])
            for key, number in value.items():
                row[f"{period}_{key}"] = number
        mdds = [abs(row[f"{p}_max_drawdown"]) for p in PERIODS]
        row["eligible_mdd_10_50"] = all(0.10 <= x <= 0.50 for x in mdds)
        row["robust_sharpe"] = min(row["design_2020_2024_sharpe"], row["recent_2025_202607_sharpe"])
        row["ranking_score"] = row["recent_2025_202607_sharpe"] if row["eligible_mdd_10_50"] else -99
        rows.append(row)
    ranking = pd.DataFrame(rows).sort_values(
        ["eligible_mdd_10_50", "ranking_score", "robust_sharpe"], ascending=[False, False, False]
    )
    ranking.insert(0, "rank", range(1, len(ranking) + 1))
    ranking.to_csv(OUT / "ranking.csv", index=False, encoding="utf-8-sig")
    eligible = ranking[ranking.eligible_mdd_10_50]
    winner = eligible.iloc[0]
    robust_winner = eligible.sort_values("robust_sharpe", ascending=False).iloc[0]
    returns = candidates[winner.variant][1]
    pd.DataFrame({"date": returns.index, "return": returns.values,
                  "equity": (1 + returns).cumprod().values * 1_000_000}).to_csv(
        OUT / "recent_sharpe_winner_curve.csv", index=False, encoding="utf-8-sig"
    )
    robust_returns = candidates[robust_winner.variant][1]
    pd.DataFrame({"date": robust_returns.index, "return": robust_returns.values,
                  "equity": (1 + robust_returns).cumprod().values * 1_000_000}).to_csv(
        OUT / "robust_sharpe_winner_curve.csv", index=False, encoding="utf-8-sig"
    )
    meta = {"created_at": "2026-09-11", "candidates": len(ranking),
            "objective": "maximize recent out-of-sample Sharpe subject to MDD 10%-50% in all three periods",
            "overlay_one_way_cost": OVERLAY_ONE_WAY_COST,
            "winner": winner[["variant", "name_cn", "recent_2025_202607_sharpe",
                              "recent_2025_202607_cagr", "recent_2025_202607_max_drawdown",
                              "full_2020_202607_sharpe", "full_2020_202607_cagr",
                              "full_2020_202607_max_drawdown"]].to_dict(),
            "robust_winner": robust_winner[["variant", "name_cn", "robust_sharpe",
                              "design_2020_2024_sharpe", "recent_2025_202607_sharpe",
                              "full_2020_202607_sharpe", "full_2020_202607_cagr",
                              "full_2020_202607_max_drawdown"]].to_dict(),
            "baseline3_1_check": result}
    (OUT / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(ranking.head(12)[["rank", "variant", "name_cn", "recent_2025_202607_sharpe",
          "recent_2025_202607_cagr", "recent_2025_202607_max_drawdown",
          "full_2020_202607_sharpe", "full_2020_202607_cagr",
          "full_2020_202607_max_drawdown", "eligible_mdd_10_50"]].to_string(index=False))


if __name__ == "__main__":
    main()
