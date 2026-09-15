"""Twenty one-factor aggressive variants above Baseline 1-2, with MDD capped at 50%."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import research_baseline2 as engine


ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "archive" / "optimization_studies" / "baseline_1-2_high_risk20_20260910"
PERIODS = {
    "train_2020_2024": (pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")),
    "recent_2025_202607": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-31")),
    "full_2020_202607": (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-07-31")),
}

DEFAULTS = {
    "SIGNAL_THRESHOLD": 0.689688,
    "TOP_PER_DAY": 8,
    "MAX_POSITIONS": 14,
    "BASE_FRACTION": 0.10,
    "STOP_LOSS": 0.07,
    "TAKE_HALF": 0.24,
    "TAKE_ALL": 0.34,
    "MAX_CALENDAR_DAYS": 30,
    "STOP_PROBABILITY_CUTOFF": 0.50,
}

# Exactly twenty independent directions; each changes one item from Baseline 1-2.
DIRECTIONS = [
    ("d01_threshold_067", "信号阈值降至0.67", {"SIGNAL_THRESHOLD": 0.67}, set()),
    ("d02_threshold_065", "信号阈值降至0.65", {"SIGNAL_THRESHOLD": 0.65}, set()),
    ("d03_threshold_063", "信号阈值降至0.63", {"SIGNAL_THRESHOLD": 0.63}, set()),
    ("d04_top10", "每日候选增至10", {"TOP_PER_DAY": 10}, set()),
    ("d05_top12", "每日候选增至12", {"TOP_PER_DAY": 12}, set()),
    ("d06_positions16", "最大持仓增至16", {"MAX_POSITIONS": 16}, set()),
    ("d07_positions18", "最大持仓增至18", {"MAX_POSITIONS": 18}, set()),
    ("d08_fraction12", "单票目标仓位12%", {"BASE_FRACTION": 0.12}, set()),
    ("d09_fraction14", "单票目标仓位14%", {"BASE_FRACTION": 0.14}, set()),
    ("d10_stop08", "止损放宽至8%", {"STOP_LOSS": 0.08}, set()),
    ("d11_stop09", "止损放宽至9%", {"STOP_LOSS": 0.09}, set()),
    ("d12_stop10", "止损放宽至10%", {"STOP_LOSS": 0.10}, set()),
    ("d13_half28", "减半止盈提高至28%", {"TAKE_HALF": 0.28}, set()),
    ("d14_half32", "减半止盈提高至32%", {"TAKE_HALF": 0.32}, set()),
    ("d15_all38", "全部止盈提高至38%", {"TAKE_ALL": 0.38}, set()),
    ("d16_all42", "全部止盈提高至42%", {"TAKE_ALL": 0.42}, set()),
    ("d17_all46", "全部止盈提高至46%", {"TAKE_ALL": 0.46}, set()),
    ("d18_hold45", "最长持有45日", {"MAX_CALENDAR_DAYS": 45}, set()),
    ("d19_hold60", "最长持有60日", {"MAX_CALENDAR_DAYS": 60}, set()),
    ("d20_stopprob055", "止损概率上限放宽至0.55", {"STOP_PROBABILITY_CUTOFF": 0.55}, set()),
]


def configure(changes: dict) -> None:
    for key, value in DEFAULTS.items():
        setattr(engine, key, value)
    for key, value in changes.items():
        setattr(engine, key, value)


def evaluate(prep, variant: str, name: str, changes: dict, extra_modes: set[str]) -> dict:
    configure(changes)
    modes = {"stop_risk_filter"} | extra_modes
    row = {"variant": variant, "name_cn": name, "changed_parameter": json.dumps(changes, ensure_ascii=False)}
    for period, (start, end) in PERIODS.items():
        result, _, _ = engine.simulate(prep, modes, start, end)
        row[f"{period}_cagr"] = result["annualized_return"]
        row[f"{period}_mdd"] = result["max_drawdown"]
        row[f"{period}_final"] = result["final_equity"]
        row[f"{period}_trades"] = result["closed_trades"]
    cagrs = [row[f"{p}_cagr"] for p in PERIODS]
    mdds = [abs(row[f"{p}_mdd"]) for p in PERIODS]
    row["mean_cagr"] = sum(cagrs) / len(cagrs)
    row["min_cagr"] = min(cagrs)
    row["worst_mdd"] = max(mdds)
    row["eligible_mdd50"] = row["worst_mdd"] <= 0.50
    # Rewards all three periods and penalizes a direction whose weakest period collapses.
    row["balanced_growth_score"] = row["mean_cagr"] * 0.70 + row["min_cagr"] * 0.30
    return row


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Prepare down to the lowest tested threshold; per-run filtering is applied later.
    engine.THRESHOLD = 0.63
    prep, stop_meta = engine.prepare()
    checkpoint = OUT / "checkpoint.csv"
    rows = []
    if checkpoint.exists():
        rows = pd.read_csv(checkpoint).to_dict("records")
    completed = {row["variant"] for row in rows}
    jobs = [("baseline1-2", "基准1-2 止损过滤", {}, set())] + DIRECTIONS
    for index, (variant, name, changes, modes) in enumerate(jobs, 1):
        if variant in completed:
            print(f"[{index:02d}/{len(jobs)}] EXISTS {variant}", flush=True)
            continue
        print(f"[{index:02d}/{len(jobs)}] RUN {variant} {name}", flush=True)
        rows.append(evaluate(prep, variant, name, changes, modes))
        pd.DataFrame(rows).to_csv(checkpoint, index=False, encoding="utf-8-sig")
        print(f"[{index:02d}/{len(jobs)}] SAVED {variant}", flush=True)
    frame = pd.DataFrame(rows)
    frame["rank"] = frame["balanced_growth_score"].where(frame.eligible_mdd50).rank(method="min", ascending=False)
    frame = frame.sort_values(["eligible_mdd50", "balanced_growth_score"], ascending=[False, False])
    frame.to_csv(OUT / "direction_ranking.csv", index=False, encoding="utf-8-sig")
    top = frame[frame.eligible_mdd50].head(5)
    meta = {
        "created_at": "2026-09-10",
        "base": "基准1-2 止损过滤",
        "initial_cash": engine.INITIAL_CASH,
        "periods": {k: [str(v[0].date()), str(v[1].date())] for k, v in PERIODS.items()},
        "hard_constraint": "worst max drawdown across three independent periods <= 50%",
        "ranking": "0.70 * mean(three CAGR) + 0.30 * min(three CAGR)",
        "directions": len(DIRECTIONS),
        "stop_model": stop_meta,
        "top5": top[["variant", "name_cn", "balanced_growth_score", "worst_mdd"]].to_dict("records"),
        "warning": "2020-2024 participates in model training; 2025-2026/7 has been repeatedly used for validation.",
    }
    (OUT / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(frame[["rank", "variant", "name_cn", "train_2020_2024_cagr", "recent_2025_202607_cagr", "full_2020_202607_cagr", "worst_mdd", "balanced_growth_score"]].head(21).to_string(index=False))


if __name__ == "__main__":
    main()
