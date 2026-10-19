from __future__ import annotations

import gc
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_002 as batch2  # noqa: E402
import run_batch_004 as batch4  # noqa: E402


PROJECT = core.PROJECT
RESULTS = PROJECT / "results" / "batch_006_pre2025_active_objectives"
INPUTS = RESULTS / "inputs"
PROTOCOL = PROJECT / "protocol" / "BATCH_006.json"
BENCHMARK = INPUTS / "sh000001_eastmoney_pre2025.parquet"
BENCHMARK_META = INPUTS / "sh000001_eastmoney_pre2025.metadata.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
EXECUTION = {"entry": 0.0, "hold": 30, "take": 4.0, "stop": 1.5, "top_k": 3}
DEFAULT_T = (0.35, 0.25, 0.20, 0.20)
DEFAULT_H = (0.35, 0.20, 0.25, 0.20)
OUTER_INITIAL = (0.25, 0.25, 0.50)
OBJECTIVES = ("defense_maximin", "stability_min_std")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_benchmark() -> tuple[dict[int, float], dict]:
    metadata = json.loads(BENCHMARK_META.read_text(encoding="utf-8"))
    required_identity = {
        "instrument_code": "000001.SH",
        "provider_request_symbol": "sh000001",
        "provider": "Eastmoney via AkShare stock_zh_index_daily_em",
        "boundary": "pre2025 only",
    }
    for key, value in required_identity.items():
        if metadata.get(key) != value:
            raise RuntimeError(f"Shanghai Composite metadata mismatch: {key}")
    data_hash = sha256(BENCHMARK)
    if metadata.get("data_sha256") != data_hash:
        raise RuntimeError("Shanghai Composite data hash does not match metadata")
    frame = pd.read_parquet(BENCHMARK)
    required = {"date", "open", "close", "high", "low", "volume", "amount"}
    if set(frame.columns) != required:
        raise RuntimeError(f"Unexpected Shanghai Composite columns: {frame.columns.tolist()}")
    frame["date"] = pd.to_datetime(frame.date)
    frame["close"] = pd.to_numeric(frame.close, errors="coerce")
    frame = frame.sort_values("date").drop_duplicates("date", keep="last")
    if frame.empty or frame.date.max() > core.HARD_MAX_DATE:
        raise RuntimeError("Shanghai Composite input is empty or crosses 2024-12-31")
    annual_closes = frame.assign(year=frame.date.dt.year).groupby("year", sort=True).tail(1)
    close_by_year = dict(zip(annual_closes.date.dt.year.astype(int), annual_closes.close.astype(float)))
    date_by_year = dict(zip(annual_closes.date.dt.year.astype(int), annual_closes.date.dt.strftime("%Y-%m-%d")))
    if 2019 not in close_by_year or not np.isfinite(close_by_year[2019]):
        raise RuntimeError("Missing valid 2019 year-end Shanghai Composite close")
    returns = {}
    records = []
    for year in core.YEARS:
        if year not in close_by_year or year - 1 not in close_by_year:
            raise RuntimeError(f"Missing benchmark year boundary for {year}")
        value = close_by_year[year] / close_by_year[year - 1] - 1.0
        returns[year] = float(value)
        records.append({
            "year": year,
            "prior_year_last_date": date_by_year[year - 1],
            "prior_year_last_close": close_by_year[year - 1],
            "year_last_date": date_by_year[year],
            "year_last_close": close_by_year[year],
            "price_index_return": float(value),
        })
    audit = {
        "instrument_name": metadata["instrument_name"],
        "instrument_code": metadata["instrument_code"],
        "provider_request_symbol": metadata["provider_request_symbol"],
        "provider": metadata["provider"],
        "data_sha256": data_hash,
        "metadata_sha256": sha256(BENCHMARK_META),
        "columns": frame.columns.tolist(),
        "minimum_date": str(frame.date.min().date()),
        "maximum_date": str(frame.date.max().date()),
        "annual_returns": records,
        "return_formula": "last close in calendar year / last close in prior calendar year - 1",
        "comparison_limitation": "This is an ordinary price index excluding dividends; the audited strategy account includes corporate-action cash dividends.",
        "rejected_unidentified_input": {
            "path": "strategies/hushen/backtest/data/benchmark.parquet",
            "reason": "Only date and close were present and neither columns nor parquet metadata established Shanghai Composite identity; it is not used for Batch006 returns.",
        },
    }
    return returns, audit


def active_metrics(row: dict, benchmark_returns: dict[int, float]) -> dict:
    values = []
    result = {}
    for year in core.YEARS:
        strategy_return = float(row[f"return_{year}"])
        active = strategy_return - benchmark_returns[year]
        result[f"benchmark_return_{year}"] = benchmark_returns[year]
        result[f"active_return_{year}"] = active
        values.append(active)
    array = np.asarray(values, dtype=float)
    std = float(np.std(array, ddof=0))
    result.update({
        "active_min": float(np.min(array)),
        "active_mean": float(np.mean(array)),
        "active_std_ddof0": std,
        "active_variance_check": std * std,
        "positive_active_years": int(np.sum(array > 0.0)),
    })
    return result


def simulate_candidate(signals: pd.DataFrame, bars, calendar, candidate_id: str, phase: str,
                       spec: dict, objective: str, benchmark_returns: dict[int, float]) -> dict:
    row, _ = core.simulate(
        signals, bars, calendar, candidate_id, EXECUTION["entry"], EXECUTION["hold"],
        "take4.00_stop1.50", EXECUTION["take"], EXECUTION["stop"],
    )
    row.update(active_metrics(row, benchmark_returns))
    row["candidate"] = candidate_id
    row["objective"] = objective
    row["phase"] = phase
    row["eligible_trade_count"] = all(int(row[f"trades_{year}"]) >= 20 for year in core.YEARS)
    row["eligible_profitable_years"] = int(row["profitable_years"]) >= 3
    common = bool(row["eligible_trade_count"] and row["eligible_profitable_years"])
    if objective == "defense_maximin":
        row["eligible"] = common
    elif objective == "stability_min_std":
        row["eligible"] = bool(common and row["active_mean"] > 0.0 and row["positive_active_years"] >= 3)
    else:
        raise ValueError(objective)
    row["spec_json"] = json.dumps(spec, sort_keys=True)
    return row


def ordered(frame: pd.DataFrame, objective: str) -> pd.DataFrame:
    if objective == "defense_maximin":
        columns = ["eligible", "active_min", "active_mean", "active_std_ddof0", "cagr", "candidate"]
        ascending = [False, False, False, True, False, True]
    elif objective == "stability_min_std":
        columns = ["eligible", "active_std_ddof0", "active_min", "active_mean", "cagr", "candidate"]
        ascending = [False, True, False, False, False, True]
    else:
        raise ValueError(objective)
    return frame.sort_values(columns, ascending=ascending, kind="stable").reset_index(drop=True)


def select_winner(rows: list[dict], objective: str) -> tuple[pd.DataFrame, dict]:
    grid = ordered(pd.DataFrame(rows), objective)
    eligible = grid[grid.eligible.astype(bool)]
    if eligible.empty:
        raise RuntimeError(f"No eligible candidate for {objective}")
    return grid, eligible.iloc[0].to_dict()


def save_phase(objective: str, number: int, name: str, rows: list[dict], spec: dict) -> dict:
    grid, winner = select_winner(rows, objective)
    grid.to_csv(RESULTS / f"{objective}_phase{number}_{name}_grid.csv", index=False, encoding="utf-8-sig")
    output = {
        "objective": objective,
        "phase": number,
        "name": name,
        "candidate_count": len(grid),
        "winner": winner,
        "winning_spec": spec,
    }
    (RESULTS / f"{objective}_phase{number}_{name}_winner.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    return output


def label(objective: str, prefix: str, values: tuple[float, ...]) -> str:
    short = "DEF" if objective == "defense_maximin" else "STAB"
    return short + "_" + prefix + "_" + "_".join(f"{int(round(value * 100)):03d}" for value in values)


def signal_frequency(signals: pd.DataFrame) -> dict:
    work = signals.assign(year=pd.to_datetime(signals.date).dt.year)
    output = {}
    for year in core.YEARS:
        part = work[work.year == year]
        per_day = part.groupby("date").size()
        output[str(year)] = {
            "signals": int(len(part)),
            "signal_days": int(part.date.nunique()),
            "maximum_signals_in_a_day": int(per_day.max()) if len(per_day) else 0,
            "mean_signals_per_signal_day": float(per_day.mean()) if len(per_day) else 0.0,
        }
    return output


def run_objective(objective: str, panel: pd.DataFrame, bars, calendar,
                  benchmark_returns: dict[int, float]) -> tuple[list[dict], list[dict], dict, pd.DataFrame]:
    all_rows: list[dict] = []
    phases: list[dict] = []
    t_default = batch4.component_t(panel, DEFAULT_T)
    h_default = batch4.component_h(panel, DEFAULT_H)

    rows1 = []
    for weights in batch4.grid_weights(3, 4):
        candidate_id = label(objective, "P1_M", weights)
        signals = batch4.candidate_signals(
            panel, candidate_id, batch4.component_m(panel, weights), t_default, h_default, OUTER_INITIAL
        )
        spec = {"M_internal": weights, "T_internal": DEFAULT_T, "H_internal": DEFAULT_H, "outer": OUTER_INITIAL}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "M_internal_weights", spec, objective, benchmark_returns)
        rows1.append(row); all_rows.append(row)
        print(f"batch006 {objective} {len(all_rows)}/151 {candidate_id}", flush=True)
    _, winner1 = select_winner(rows1, objective)
    win_m = tuple(json.loads(winner1["spec_json"])["M_internal"])
    phases.append(save_phase(objective, 1, "M_internal", rows1, {"M_internal": win_m}))
    m_winner = batch4.component_m(panel, win_m)

    rows2 = []
    for weights in batch4.grid_weights(4, 4):
        candidate_id = label(objective, "P2_T", weights)
        signals = batch4.candidate_signals(panel, candidate_id, m_winner, batch4.component_t(panel, weights), h_default, OUTER_INITIAL)
        spec = {"M_internal": win_m, "T_internal": weights, "H_internal": DEFAULT_H, "outer": OUTER_INITIAL}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "T_internal_weights", spec, objective, benchmark_returns)
        rows2.append(row); all_rows.append(row)
        print(f"batch006 {objective} {len(all_rows)}/151 {candidate_id}", flush=True)
    _, winner2 = select_winner(rows2, objective)
    win_t = tuple(json.loads(winner2["spec_json"])["T_internal"])
    phases.append(save_phase(objective, 2, "T_internal", rows2, {"M_internal": win_m, "T_internal": win_t}))
    t_winner = batch4.component_t(panel, win_t)

    rows3 = []
    for weights in batch4.grid_weights(4, 4):
        candidate_id = label(objective, "P3_H", weights)
        signals = batch4.candidate_signals(panel, candidate_id, m_winner, t_winner, batch4.component_h(panel, weights), OUTER_INITIAL)
        spec = {"M_internal": win_m, "T_internal": win_t, "H_internal": weights, "outer": OUTER_INITIAL}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "H_internal_weights", spec, objective, benchmark_returns)
        rows3.append(row); all_rows.append(row)
        print(f"batch006 {objective} {len(all_rows)}/151 {candidate_id}", flush=True)
    _, winner3 = select_winner(rows3, objective)
    win_h = tuple(json.loads(winner3["spec_json"])["H_internal"])
    phases.append(save_phase(objective, 3, "H_internal", rows3, {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h}))
    h_winner = batch4.component_h(panel, win_h)

    rows4 = []
    for weights in batch4.grid_weights(3, 10):
        candidate_id = label(objective, "P4_OUTER", weights)
        signals = batch4.candidate_signals(panel, candidate_id, m_winner, t_winner, h_winner, weights)
        spec = {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h, "outer": weights}
        row = simulate_candidate(signals, bars, calendar, candidate_id, "outer_M_T_H_weights", spec, objective, benchmark_returns)
        rows4.append(row); all_rows.append(row)
        print(f"batch006 {objective} {len(all_rows)}/151 {candidate_id}", flush=True)
    _, winner4 = select_winner(rows4, objective)
    win_outer = tuple(json.loads(winner4["spec_json"])["outer"])
    phases.append(save_phase(
        objective, 4, "outer_M_T_H", rows4,
        {"M_internal": win_m, "T_internal": win_t, "H_internal": win_h, "outer": win_outer},
    ))
    champion_id = str(winner4["candidate"])
    champion_signals = batch4.candidate_signals(panel, champion_id, m_winner, t_winner, h_winner, win_outer)
    champion_signals.to_parquet(RESULTS / f"{objective}_champion_signals_screening.parquet", index=False)
    final = {
        "objective": objective,
        "screening_champion": winner4,
        "champion_spec": phases[-1]["winning_spec"],
        "signal_frequency": signal_frequency(champion_signals),
        "boundary_flags": {
            "M_internal": any(v in {0.0, 1.0} for v in win_m),
            "T_internal": any(v in {0.0, 1.0} for v in win_t),
            "H_internal": any(v in {0.0, 1.0} for v in win_h),
            "outer": any(v in {0.0, 1.0} for v in win_outer),
        },
    }
    return all_rows, phases, final, champion_signals


def main() -> None:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol["screening_counts"] != {"per_objective": 151, "objective_count": 2, "total": 302,
                                         "reuse_batch004_ordering_only": False, "grid_expansion_after_results": False}:
        raise RuntimeError("Batch006 screening counts changed")
    counts = [phase["candidate_count"] for phase in protocol["independent_sequential_grid_per_objective"]]
    if counts != [15, 35, 35, 66]:
        raise RuntimeError("Batch006 phase counts changed")
    benchmark_returns, benchmark_audit = load_benchmark()
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "BENCHMARK_ANNUAL_RETURNS.json").write_text(
        json.dumps(benchmark_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not BASE_PANEL.exists():
        raise FileNotFoundError("The whitelisted Batch004 pre-2025 component panel is required; refusing to rebuild old results")
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.min() < core.EVAL_START or panel.date.max() > pd.Timestamp("2024-11-22"):
        raise RuntimeError("Component panel violates Batch006 boundaries")
    bars, calendar = core.load_execution_bars(set(panel.symbol.astype(str)), force=False)
    if max(calendar) > core.HARD_MAX_DATE:
        raise RuntimeError("Execution bars cross 2024-12-31")

    all_rows = []
    phase_results = {}
    champions = {}
    maximum_signal_date = pd.Timestamp.min
    for objective in OBJECTIVES:
        rows, phases, champion, signals = run_objective(objective, panel, bars, calendar, benchmark_returns)
        if len(rows) != 151:
            raise RuntimeError(f"Expected 151 runs for {objective}, got {len(rows)}")
        all_rows.extend(rows)
        phase_results[objective] = phases
        champions[objective] = champion
        maximum_signal_date = max(maximum_signal_date, signals.date.max())
    if len(all_rows) != 302:
        raise RuntimeError(f"Expected 302 runs, got {len(all_rows)}")
    all_frame = pd.DataFrame(all_rows)
    if all_frame.candidate.nunique() != 302:
        raise RuntimeError("Candidate identifiers are not unique across both independent paths")
    all_frame.to_csv(RESULTS / "ALL_302_RESULTS.csv", index=False, encoding="utf-8-sig")
    active_columns = ["objective", "phase", "candidate", "eligible", "active_min", "active_mean",
                      "active_std_ddof0", "active_variance_check", "positive_active_years"]
    active_columns += [f"active_return_{year}" for year in core.YEARS]
    all_frame[active_columns].to_csv(RESULTS / "ALL_302_ANNUAL_ACTIVE_RETURNS.csv", index=False, encoding="utf-8-sig")
    hashes = {
        "BATCH_006.json": sha256(PROTOCOL),
        "run_batch_006.py": sha256(Path(__file__)),
        "run_batch.py": sha256(HERE / "run_batch.py"),
        "run_batch_002.py": sha256(HERE / "run_batch_002.py"),
        "run_batch_004.py": sha256(HERE / "run_batch_004.py"),
        "base_component_panel_pre2025.parquet": sha256(BASE_PANEL),
        "feature_panel_pre2025.parquet": sha256(core.CACHE / "feature_panel_pre2025.parquet"),
        "model_panel_batch002_pre2025.parquet": sha256(core.CACHE / "model_panel_batch002_pre2025.parquet"),
        "execution_bars_pre2025.parquet": sha256(core.CACHE / "execution_bars_pre2025.parquet"),
        "sh000001_eastmoney_pre2025.parquet": sha256(BENCHMARK),
        "sh000001_eastmoney_pre2025.metadata.json": sha256(BENCHMARK_META),
        **{f"model_{path.name}": sha256(path) for path in sorted(batch2.MODEL_DIR.glob("*.txt"))},
    }
    output = {
        "protocol_id": protocol["protocol_id"],
        "status": "two_unique_champions_frozen_pending_raw_action_audit",
        "completed_screening_runs": len(all_rows),
        "independent_runs_per_objective": {objective: 151 for objective in OBJECTIVES},
        "phase_results": phase_results,
        "champions": champions,
        "benchmark": benchmark_audit,
        "source_hashes": hashes,
        "assertions": {
            "screening_run_count_exact_302": len(all_rows) == 302,
            "unique_candidate_count_exact_302": all_frame.candidate.nunique() == 302,
            "maximum_signal_date": str(maximum_signal_date.date()),
            "maximum_signal_date_at_or_before_2024_11_22": maximum_signal_date <= pd.Timestamp("2024-11-22"),
            "maximum_execution_date": str(max(calendar).date()),
            "maximum_execution_date_at_or_before_2024_12_31": max(calendar) <= core.HARD_MAX_DATE,
            "post_2024_access": False,
            "grid_expanded": False,
            "production_change": False,
        },
        "development_note": "All 2020-2024 outcomes are development evidence, not blind or holdout evidence.",
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    gc.collect()
    print(json.dumps({"status": output["status"], "completed_screening_runs": len(all_rows),
                      "assertions": output["assertions"]}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
