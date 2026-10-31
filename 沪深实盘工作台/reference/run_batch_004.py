from __future__ import annotations

import gc
import json
import math
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_002 as batch2  # noqa: E402


PROJECT = core.PROJECT
RESULTS = PROJECT / "results" / "batch_004_pre2025_factor_tuning"
PROTOCOL = PROJECT / "protocol" / "BATCH_004.json"
BATCH3_SELECTION = PROJECT / "results" / "batch_003" / "SELECTION.json"
BASE_PANEL_CACHE = RESULTS / "base_component_panel_pre2025.parquet"

DEFAULT_T = (0.35, 0.25, 0.20, 0.20)
DEFAULT_H = (0.35, 0.20, 0.25, 0.20)
EXECUTION = {"entry": 0.0, "hold": 30, "take": 4.0, "stop": 1.5, "top_k": 3}


def grid_weights(dimensions: int, units: int) -> list[tuple[float, ...]]:
    def compositions(total: int, count: int, prefix: tuple[int, ...] = ()):
        if count == 1:
            yield prefix + (total,)
            return
        for value in range(total + 1):
            yield from compositions(total - value, count - 1, prefix + (value,))

    return [tuple(value / units for value in item) for item in compositions(units, dimensions)]


def rank_center(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    return frame.groupby("date", sort=False)[columns].rank(pct=True, method="average") - 0.5


def build_base_panel() -> pd.DataFrame:
    RESULTS.mkdir(parents=True, exist_ok=True)
    if BASE_PANEL_CACHE.exists():
        panel = pd.read_parquet(BASE_PANEL_CACHE)
        panel["date"] = pd.to_datetime(panel.date)
        if panel.empty or panel.date.max() > core.LAST_SIGNAL_DATE:
            raise RuntimeError("Batch004 component cache is empty or crosses the pre-2025 signal boundary")
        return panel

    model = batch2.build_model_panel().copy()
    technical = core.build_feature_panel()[
        ["date", "symbol", "overnight20", "intraday20", "vol60", "turn20"]
    ].copy()
    panel = model.merge(
        technical, on=["date", "symbol"], how="inner", validate="one_to_one", suffixes=("", "_tech")
    )
    if panel.empty or panel.date.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Component panel is empty or crosses the pre-2025 signal boundary")

    for name in ["utility", "pen025", "pen100"]:
        booster = lgb.Booster(model_file=str(batch2.MODEL_DIR / f"{name}.txt"))
        if booster.feature_name() != batch2.MODEL_FEATURES:
            raise RuntimeError(f"Feature mismatch for frozen model {name}")
        panel[name] = booster.predict(panel[batch2.MODEL_FEATURES], num_threads=4)

    panel["cap_proxy_log"] = panel["f_log_amount"] - np.log(panel["f_turn"].clip(lower=1e-6))
    ranks = rank_center(
        panel,
        ["mom120", "close_to_high60", "mom20", "vol60", "cap_proxy_log", "vol60_tech", "overnight20", "intraday20"],
    )
    panel["t_mom120_pos"] = ranks.mom120
    panel["t_high60_pos"] = ranks.close_to_high60
    panel["t_mom20_pos"] = ranks.mom20
    panel["t_vol60_neg"] = -ranks.vol60
    panel["h_size_neg"] = -ranks.cap_proxy_log
    panel["h_vol60_neg"] = -ranks.vol60_tech
    panel["h_overnight_pos"] = ranks.overnight20
    panel["h_intraday_neg"] = -ranks.intraday20
    keep = [
        "date", "symbol", "close", "atr_pct", "utility", "pen025", "pen100",
        "t_mom120_pos", "t_high60_pos", "t_mom20_pos", "t_vol60_neg",
        "h_size_neg", "h_vol60_neg", "h_overnight_pos", "h_intraday_neg",
    ]
    panel = panel[keep].replace([np.inf, -np.inf], np.nan).dropna().sort_values(["date", "symbol"]).reset_index(drop=True)
    panel.to_parquet(BASE_PANEL_CACHE, index=False)
    return panel


def component_m(panel: pd.DataFrame, weights: tuple[float, float, float]) -> pd.Series:
    raw = weights[0] * panel.utility + weights[1] * panel.pen025 + weights[2] * panel.pen100
    return panel.assign(_raw=raw).groupby("date", sort=False)["_raw"].rank(pct=True, method="average") - 0.5


def component_t(panel: pd.DataFrame, weights: tuple[float, float, float, float]) -> pd.Series:
    raw = (
        weights[0] * panel.t_mom120_pos + weights[1] * panel.t_high60_pos
        + weights[2] * panel.t_mom20_pos + weights[3] * panel.t_vol60_neg
    )
    return panel.assign(_raw=raw).groupby("date", sort=False)["_raw"].rank(pct=True, method="average") - 0.5


def component_h(panel: pd.DataFrame, weights: tuple[float, float, float, float]) -> pd.Series:
    raw = (
        weights[0] * panel.h_size_neg + weights[1] * panel.h_vol60_neg
        + weights[2] * panel.h_overnight_pos + weights[3] * panel.h_intraday_neg
    )
    work = panel[["date", "symbol"]].copy()
    work["_raw"] = raw
    work = work.sort_values(["symbol", "date"])
    work["_smooth"] = work.groupby("symbol", sort=False)._raw.transform(
        lambda values: values.rolling(5, min_periods=3).mean()
    )
    work = work.sort_index()
    return work.groupby("date", sort=False)["_smooth"].rank(pct=True, method="average") - 0.5


def candidate_signals(
    panel: pd.DataFrame,
    candidate_id: str,
    m: pd.Series,
    t: pd.Series,
    h: pd.Series,
    outer: tuple[float, float, float],
) -> pd.DataFrame:
    out = panel[["date", "symbol", "close", "atr_pct"]].copy()
    out["score"] = outer[0] * m + outer[1] * t + outer[2] * h
    out = out.dropna(subset=["score"])
    out = out.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")
    out = out.groupby("date", sort=False).head(EXECUTION["top_k"]).copy()
    out["factor"] = candidate_id
    return out.sort_values(["date", "score", "symbol"], ascending=[True, False, True], kind="stable")


def ordered(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.sort_values(
        ["eligible", "cagr", "worst_annual_return", "profitable_years", "annual_return_std", "trade_count_cv", "candidate"],
        ascending=[False, False, False, False, True, True, True],
        kind="stable",
    ).reset_index(drop=True)


def simulate_candidate(signals, bars, calendar, candidate_id: str, phase: str, spec: dict) -> dict:
    row, _ = core.simulate(
        signals, bars, calendar, candidate_id, EXECUTION["entry"], EXECUTION["hold"],
        "take4.00_stop1.50", EXECUTION["take"], EXECUTION["stop"],
    )
    row["candidate"] = candidate_id
    row["phase"] = phase
    row["eligible_trade_count"] = bool(row["eligible"])
    row["eligible"] = bool(row["eligible"] and row["profitable_years"] >= 3)
    row["spec_json"] = json.dumps(spec, sort_keys=True)
    return row


def subperiod_metrics(row: dict) -> dict:
    returns = [float(row[f"return_{year}"]) for year in [2022, 2023, 2024]]
    growth = math.prod(1.0 + value for value in returns)
    return {
        "cumulative_return_2022_2024": growth - 1.0,
        "cagr_2022_2024": growth ** (1.0 / 3.0) - 1.0,
        "profitable_years_2022_2024": sum(value > 0 for value in returns),
    }


def save_phase(number: int, name: str, rows: list[dict], spec: dict) -> dict:
    grid = ordered(pd.DataFrame(rows))
    grid.to_csv(RESULTS / f"phase{number}_{name}_grid.csv", index=False, encoding="utf-8-sig")
    winner = grid.iloc[0].to_dict()
    winner.update(subperiod_metrics(winner))
    output = {"phase": number, "name": name, "winner": winner, "winning_spec": spec, "candidate_count": len(grid)}
    (RESULTS / f"phase{number}_{name}_winner.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return output


def label(prefix: str, values: tuple[float, ...]) -> str:
    return prefix + "_" + "_".join(f"{int(round(value * 100)):03d}" for value in values)


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["total_screening_runs"] != 151 or not protocol["post_2024_forbidden"]:
        raise RuntimeError("Batch004 protocol mismatch")
    phase_counts = [item["candidate_count"] for item in protocol["sequential_phases"]]
    if phase_counts != [15, 35, 35, 66]:
        raise RuntimeError("Batch004 registered phase counts changed")
    reference = json.loads(BATCH3_SELECTION.read_text(encoding="utf-8"))["winners"]["30cal"]
    outer_current = tuple(float(reference["formula"][key]) for key in ["M", "T", "H"])
    if outer_current != (0.25, 0.25, 0.5) or int(reference["formula"]["daily_top_k"]) != 3:
        raise RuntimeError("Frozen batch003 30cal reference changed")
    if any(float(reference[key]) != expected for key, expected in [("entry_offset_atr", 0.0), ("take_atr", 4.0), ("stop_atr", 1.5)]):
        raise RuntimeError("Frozen 30cal execution reference changed")

    panel = build_base_panel()
    if panel.date.min() < core.EVAL_START or panel.date.max() > core.LAST_SIGNAL_DATE:
        raise RuntimeError("Panel date assertions failed")
    bars, calendar = core.load_execution_bars(set(panel.symbol.astype(str)), force=False)
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Execution calendar crosses 2024-12-31")

    all_rows: list[dict] = []
    m_default = component_m(panel, (1 / 3, 1 / 3, 1 / 3))
    t_default = component_t(panel, DEFAULT_T)
    h_default = component_h(panel, DEFAULT_H)

    rows1 = []
    m_specs = grid_weights(3, 4)
    for index, weights in enumerate(m_specs, 1):
        candidate_id = label("P1_M", weights)
        signals = candidate_signals(panel, candidate_id, component_m(panel, weights), t_default, h_default, outer_current)
        spec = {"M_internal": weights, "T_internal": DEFAULT_T, "H_internal": DEFAULT_H, "outer": outer_current}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "M_internal_weights", spec)
        rows1.append(row); all_rows.append(row)
        print(f"batch004 {index}/151 {candidate_id} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)
    grid1 = ordered(pd.DataFrame(rows1))
    win_m = tuple(json.loads(grid1.iloc[0].spec_json)["M_internal"])
    phase1 = save_phase(1, "M_internal", rows1, {"M_internal": win_m})
    m_winner = component_m(panel, win_m)

    rows2 = []
    t_specs = grid_weights(4, 4)
    for offset, weights in enumerate(t_specs, 16):
        candidate_id = label("P2_T", weights)
        signals = candidate_signals(panel, candidate_id, m_winner, component_t(panel, weights), h_default, outer_current)
        spec = {"M_internal": win_m, "T_internal": weights, "H_internal": DEFAULT_H, "outer": outer_current}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "T_internal_weights", spec)
        rows2.append(row); all_rows.append(row)
        print(f"batch004 {offset}/151 {candidate_id} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)
    grid2 = ordered(pd.DataFrame(rows2))
    win_t = tuple(json.loads(grid2.iloc[0].spec_json)["T_internal"])
    phase2 = save_phase(2, "T_internal", rows2, {"M_internal": win_m, "T_internal": win_t})
    t_winner = component_t(panel, win_t)

    rows3 = []
    h_specs = grid_weights(4, 4)
    for offset, weights in enumerate(h_specs, 51):
        candidate_id = label("P3_H", weights)
        signals = candidate_signals(panel, candidate_id, m_winner, t_winner, component_h(panel, weights), outer_current)
        spec = {"M_internal": win_m, "T_internal": win_t, "H_internal": weights, "outer": outer_current}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "H_internal_weights", spec)
        rows3.append(row); all_rows.append(row)
        print(f"batch004 {offset}/151 {candidate_id} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)
    grid3 = ordered(pd.DataFrame(rows3))
    win_h = tuple(json.loads(grid3.iloc[0].spec_json)["H_internal"])
    phase3 = save_phase(3, "H_internal", rows3, {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h})
    h_winner = component_h(panel, win_h)

    rows4 = []
    outer_specs = grid_weights(3, 10)
    champion_signals = None
    for offset, weights in enumerate(outer_specs, 86):
        candidate_id = label("P4_OUTER", weights)
        signals = candidate_signals(panel, candidate_id, m_winner, t_winner, h_winner, weights)
        spec = {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h, "outer": weights}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "outer_M_T_H_weights", spec)
        rows4.append(row); all_rows.append(row)
        print(f"batch004 {offset}/151 {candidate_id} cagr={row['cagr']:.4%} eligible={row['eligible']}", flush=True)
    grid4 = ordered(pd.DataFrame(rows4))
    win_outer = tuple(json.loads(grid4.iloc[0].spec_json)["outer"])
    final_id = str(grid4.iloc[0].candidate)
    champion_signals = candidate_signals(panel, final_id, m_winner, t_winner, h_winner, win_outer)
    champion_signals.to_parquet(RESULTS / "champion_signals_screening.parquet", index=False)
    phase4 = save_phase(
        4, "outer_M_T_H", rows4,
        {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h, "outer": win_outer},
    )

    if len(all_rows) != 151:
        raise RuntimeError(f"Expected 151 screening runs, got {len(all_rows)}")
    pd.DataFrame(all_rows).to_csv(RESULTS / "all_sequential_runs.csv", index=False, encoding="utf-8-sig")
    boundary = {
        "M_internal": any(value in {0.0, 1.0} for value in win_m),
        "T_internal": any(value in {0.0, 1.0} for value in win_t),
        "H_internal": any(value in {0.0, 1.0} for value in win_h),
        "outer": any(value in {0.0, 1.0} for value in win_outer),
    }
    hashes = {
        "BATCH_004.json": core.sha256(PROTOCOL),
        "run_batch_004.py": core.sha256(Path(__file__)),
        "run_batch.py": core.sha256(HERE / "run_batch.py"),
        "run_batch_002.py": core.sha256(HERE / "run_batch_002.py"),
        "batch003_SELECTION.json": core.sha256(BATCH3_SELECTION),
        "feature_panel_pre2025.parquet": core.sha256(core.CACHE / "feature_panel_pre2025.parquet"),
        "model_panel_batch002_pre2025.parquet": core.sha256(core.CACHE / "model_panel_batch002_pre2025.parquet"),
        "execution_bars_pre2025.parquet": core.sha256(core.CACHE / "execution_bars_pre2025.parquet"),
        **{f"model_{path.name}": core.sha256(path) for path in sorted(batch2.MODEL_DIR.glob("*.txt"))},
    }
    output = {
        "protocol_id": protocol["protocol_id"],
        "status": "unique_champion_frozen_pending_raw_action_audit",
        "completed_screening_runs": len(all_rows),
        "phase_winners": [phase1, phase2, phase3, phase4],
        "champion": phase4["winner"],
        "champion_spec": phase4["winning_spec"],
        "champion_on_grid_boundary": boundary,
        "assertions": {
            "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()),
            "maximum_execution_date": str(max(calendar).date()),
            "all_years_at_least_20_trades": bool(phase4["winner"]["eligible_trade_count"]),
            "at_least_3_profitable_years": int(phase4["winner"]["profitable_years"]) >= 3,
            "screening_run_count_exact": len(all_rows) == 151,
            "grid_expanded": False,
        },
        "source_hashes": hashes,
        "development_note": "All 2020-2024 results, including the 2022-2024 subperiod, are development results and are not blind or holdout evidence.",
        "production_change": False,
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    gc.collect()
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str), flush=True)


if __name__ == "__main__":
    main()
