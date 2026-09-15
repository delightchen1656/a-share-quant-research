"""Ten structural, non-grid directions on top of the threshold-0.63 aggressive candidate."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import research_baseline2 as engine
from src.model import FEATURES


ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "archive" / "optimization_studies" / "baseline_1-2_structural10_20260910"
PERIODS = {
    "train_2020_2024": (pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31")),
    "recent_2025_202607": (pd.Timestamp("2025-01-01"), pd.Timestamp("2026-07-31")),
    "full_2020_202607": (pd.Timestamp("2020-01-01"), pd.Timestamp("2026-07-31")),
}
DIRECTIONS = [
    ("s01_time_to_target", "到达30%时间模型排序", {"time_to_target_rank"}),
    ("s02_expected_gain", "未来22日收益幅度模型排序", {"expected_gain_rank"}),
    ("s03_path_utility", "收益风险时间联合排序", {"path_utility_rank"}),
    ("s04_trend_confirmation", "短中趋势共同确认入场", {"trend_confirmation"}),
    ("s05_signal_persistence", "信号连续两日确认入场", {"signal_persistence"}),
    ("s06_gap_quality", "次日跳空质量过滤", {"gap_quality_entry"}),
    ("s07_stagnant_recycle", "横盘持仓提前回收资金", {"stagnant_recycle"}),
    ("s08_signal_decay_exit", "模型信号衰减提前退出", {"signal_decay_exit"}),
    ("s09_trend_adaptive_expiry", "强趋势持仓自适应延期", {"trend_adaptive_expiry"}),
    ("s10_stop_quarantine", "止损股票短期禁止重入", {"stop_reentry_quarantine"}),
]


def add_path_targets(frame: pd.DataFrame) -> pd.DataFrame:
    chunks = []
    for _, group in frame.groupby("symbol", sort=False):
        group = group.sort_values("date").copy()
        base = group.close.to_numpy(float)
        highs = group.high.to_numpy(float)
        gain = np.full(len(group), np.nan)
        days = np.full(len(group), np.nan)
        for i in range(len(group)):
            future = highs[i + 1:min(len(group), i + 23)] / base[i] - 1.0
            if len(future) < 22:
                continue
            gain[i] = float(np.max(future))
            hits = np.flatnonzero(future >= 0.30)
            days[i] = float(hits[0] + 1 if len(hits) else 30)
        group["future_gain22"] = gain
        group["hit_days30"] = days
        chunks.append(group)
    return pd.concat(chunks, ignore_index=True)


def enrich(prep: engine.Prepared) -> dict:
    data = add_path_targets(prep.feature_frame.copy())
    train = data[(data.date <= "2024-11-29") & data.future_gain22.notna()].copy()
    gain_model = HistGradientBoostingRegressor(
        max_iter=120, learning_rate=0.05, max_leaf_nodes=15,
        l2_regularization=3.0, random_state=91,
    )
    time_model = HistGradientBoostingRegressor(
        max_iter=120, learning_rate=0.05, max_leaf_nodes=15,
        l2_regularization=3.0, random_state=92,
    )
    gain_model.fit(train[FEATURES], train.future_gain22.clip(-0.20, 1.00))
    time_model.fit(train[FEATURES], train.hit_days30)
    data["predicted_gain22"] = gain_model.predict(data[FEATURES])
    data["predicted_hit_days"] = time_model.predict(data[FEATURES]).clip(1, 30)
    data = data.sort_values(["symbol", "date"])
    active = data.probability >= engine.SIGNAL_THRESHOLD
    data["signal_streak"] = active.groupby(data.symbol).transform(
        lambda values: values.groupby((~values).cumsum()).cumcount().add(1).where(values, 0)
    )
    cols = ["symbol", "probability", "stop_probability", "vol20", "ret5", "ret20",
            "predicted_gain22", "predicted_hit_days", "signal_streak"]
    prep.candidates_by_date = {
        date: group[group.probability >= engine.SIGNAL_THRESHOLD]
        .sort_values("probability", ascending=False)[cols]
        for date, group in data.groupby("date")
    }
    return {
        "training_end": "2024-11-29",
        "training_rows": int(len(train)),
        "gain_target": "next 22 sessions maximum high return, clipped to [-20%, 100%]",
        "time_target": "sessions to +30% within 22 sessions; otherwise 30",
    }


def evaluate(prep, variant: str, name: str, structural_modes: set[str]) -> dict:
    modes = {"stop_risk_filter"} | structural_modes
    row = {"variant": variant, "name_cn": name, "mechanism": "+".join(sorted(structural_modes)) or "baseline"}
    for period, (start, end) in PERIODS.items():
        result, _, _ = engine.simulate(prep, modes, start, end)
        row[f"{period}_cagr"] = result["annualized_return"]
        row[f"{period}_mdd"] = result["max_drawdown"]
        row[f"{period}_final"] = result["final_equity"]
        row[f"{period}_trades"] = result["closed_trades"]
    cagrs = [row[f"{period}_cagr"] for period in PERIODS]
    row["mean_cagr"] = float(np.mean(cagrs))
    row["min_cagr"] = float(np.min(cagrs))
    row["worst_mdd"] = max(abs(row[f"{period}_mdd"]) for period in PERIODS)
    row["eligible_mdd50"] = row["worst_mdd"] <= 0.50
    row["balanced_growth_score"] = 0.70 * row["mean_cagr"] + 0.30 * row["min_cagr"]
    return row


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    engine.THRESHOLD = 0.63
    engine.SIGNAL_THRESHOLD = 0.63
    prep, stop_meta = engine.prepare()
    auxiliary_meta = enrich(prep)
    checkpoint = OUT / "checkpoint.csv"
    rows = pd.read_csv(checkpoint).to_dict("records") if checkpoint.exists() else []
    completed = {row["variant"] for row in rows}
    jobs = [("aggressive063", "高进攻候选 阈值0.63", set())] + DIRECTIONS
    for index, (variant, name, modes) in enumerate(jobs, 1):
        if variant in completed:
            print(f"[{index:02d}/{len(jobs)}] EXISTS {variant}", flush=True)
            continue
        print(f"[{index:02d}/{len(jobs)}] RUN {variant} {name}", flush=True)
        rows.append(evaluate(prep, variant, name, modes))
        pd.DataFrame(rows).to_csv(checkpoint, index=False, encoding="utf-8-sig")
        print(f"[{index:02d}/{len(jobs)}] SAVED {variant}", flush=True)
    frame = pd.DataFrame(rows)
    frame["rank"] = frame.balanced_growth_score.where(frame.eligible_mdd50).rank(method="min", ascending=False)
    frame = frame.sort_values(["eligible_mdd50", "balanced_growth_score"], ascending=[False, False])
    frame.to_csv(OUT / "direction_ranking.csv", index=False, encoding="utf-8-sig")
    baseline = frame[frame.variant == "aggressive063"].iloc[0]
    for period in PERIODS:
        frame[f"{period}_beats_base"] = frame[f"{period}_cagr"] > baseline[f"{period}_cagr"]
    frame["beats_base_all3"] = frame[[f"{p}_beats_base" for p in PERIODS]].all(axis=1)
    frame.to_csv(OUT / "direction_ranking.csv", index=False, encoding="utf-8-sig")
    top = frame[frame.eligible_mdd50].head(5)
    meta = {
        "created_at": "2026-09-10", "base": "高进攻候选 阈值0.63",
        "directions": 10, "initial_cash": engine.INITIAL_CASH,
        "periods": {key: [str(value[0].date()), str(value[1].date())] for key, value in PERIODS.items()},
        "hard_constraint": "worst MDD across three independent periods <= 50%",
        "ranking": "0.70 * mean(three CAGR) + 0.30 * min(three CAGR)",
        "auxiliary_models": auxiliary_meta, "stop_model": stop_meta,
        "top5": top[["variant", "name_cn", "balanced_growth_score", "worst_mdd", "beats_base_all3"]].to_dict("records"),
        "warning": "2020-2024 is training replay; 2025-2026/7 is a repeatedly used validation period.",
    }
    (OUT / "summary.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(frame[["rank", "variant", "name_cn", "train_2020_2024_cagr", "recent_2025_202607_cagr",
                 "full_2020_202607_cagr", "worst_mdd", "balanced_growth_score", "beats_base_all3"]].to_string(index=False))


if __name__ == "__main__":
    main()
