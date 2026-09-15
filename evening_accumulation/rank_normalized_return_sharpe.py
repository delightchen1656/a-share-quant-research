"""Rank all existing candidates with normalized CAGR and Sharpe.

The loss is annual-return dominant while preserving risk-adjusted quality:

  period_utility = 0.75 * normalized_CAGR + 0.25 * normalized_Sharpe
  utility = 0.40 * design_utility + 0.60 * recent_utility
            - 0.20 * abs(design_utility - recent_utility)
  loss = -utility + constraint_penalties

Normalization is cross-sectional winsorized min-max (5th/95th percentile) inside
each period.  Drawdown eligibility remains a hard 10%-50% constraint in design,
recent and full periods.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OLD = ROOT / "archive/optimization_studies/sharpe_frontier_20260911/ranking.csv"
NEW = ROOT / "archive/optimization_studies/sharpe_public_structures_20260911/ranking.csv"
OUT = ROOT / "archive/optimization_studies/normalized_return_sharpe_20260911"


def load_pool() -> pd.DataFrame:
    a = pd.read_csv(OLD).rename(columns={
        "design_2020_2024_cagr": "design_cagr",
        "design_2020_2024_sharpe": "design_sharpe",
        "design_2020_2024_max_drawdown": "design_mdd",
        "recent_2025_202607_cagr": "recent_cagr",
        "recent_2025_202607_sharpe": "recent_sharpe",
        "recent_2025_202607_max_drawdown": "recent_mdd",
        "full_2020_202607_cagr": "full_cagr",
        "full_2020_202607_sharpe": "full_sharpe",
        "full_2020_202607_max_drawdown": "full_mdd",
        "eligible_mdd_10_50": "eligible",
    })
    a["source"] = "sharpe_frontier"
    b = pd.read_csv(NEW)
    b["source"] = "public_structures"
    cols = ["source", "variant", "name_cn", "design_cagr", "design_sharpe", "design_mdd",
            "recent_cagr", "recent_sharpe", "recent_mdd", "full_cagr", "full_sharpe",
            "full_mdd", "eligible"]
    pool = pd.concat([a[cols], b[cols]], ignore_index=True)
    # The two raw baselines occur in both studies; retain one exact copy.
    pool = pool.drop_duplicates(subset=["variant"], keep="first")
    pool["candidate_id"] = pool["source"] + ":" + pool["variant"]
    return pool


def normalize(s: pd.Series) -> tuple[pd.Series, dict]:
    lo, hi = float(s.quantile(0.05)), float(s.quantile(0.95))
    if hi <= lo:
        return pd.Series(0.5, index=s.index), {"q05": lo, "q95": hi}
    return ((s.clip(lo, hi) - lo) / (hi - lo)), {"q05": lo, "q95": hi}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    pool = load_pool()
    bounds = {}
    for period in ("design", "recent"):
        for metric in ("cagr", "sharpe"):
            col = f"{period}_{metric}"
            pool[f"n_{col}"], bounds[col] = normalize(pool[col])
        pool[f"{period}_utility"] = (
            0.75 * pool[f"n_{period}_cagr"] + 0.25 * pool[f"n_{period}_sharpe"]
        )

    pool["stability_penalty"] = 0.20 * (
        pool["design_utility"] - pool["recent_utility"]
    ).abs()
    pool["raw_utility"] = (
        0.40 * pool["design_utility"] + 0.60 * pool["recent_utility"]
        - pool["stability_penalty"]
    )
    calculated_eligible = np.logical_and.reduce([
        pool[f"{p}_mdd"].abs().between(0.10, 0.50) for p in ("design", "recent", "full")
    ])
    pool["eligible"] = calculated_eligible
    pool["constraint_penalty"] = np.where(pool["eligible"], 0.0, 10.0)
    pool["loss"] = -pool["raw_utility"] + pool["constraint_penalty"]
    pool = pool.sort_values(["loss", "recent_cagr", "recent_sharpe"], ascending=[True, False, False])
    pool.insert(0, "rank", range(1, len(pool) + 1))
    pool.to_csv(OUT / "ranking.csv", index=False, encoding="utf-8-sig")

    winner = pool.iloc[0]
    summary = {
        "created_at": "2026-09-11",
        "candidate_count_after_dedup": int(len(pool)),
        "loss": "-(0.40*U_design + 0.60*U_recent - 0.20*abs(U_design-U_recent)) + constraint_penalty",
        "period_utility": "0.75*normalized_CAGR + 0.25*normalized_Sharpe",
        "normalization": "within-period cross-sectional winsorized min-max using q05 and q95",
        "hard_constraint": "absolute MDD in [10%, 50%] for design, recent and full periods",
        "normalization_bounds": bounds,
        "winner": winner.to_dict(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    view = ["rank", "candidate_id", "name_cn", "loss", "design_cagr", "design_sharpe",
            "recent_cagr", "recent_sharpe", "full_cagr", "full_sharpe", "full_mdd", "eligible"]
    print(pool[view].head(15).to_string(index=False))


if __name__ == "__main__":
    main()
