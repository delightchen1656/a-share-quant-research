from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


RESULTS = Path(__file__).resolve().parent
PROJECT = RESULTS.parents[1]
RESEARCH = PROJECT / "research"
sys.path.insert(0, str(RESEARCH))
import run_batch as core  # noqa: E402
import run_batch_004 as batch4  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import run_batch_007_pre2025 as batch7  # noqa: E402
import audit_champion as prior_audit  # noqa: E402

_b9_path = PROJECT / "results" / "batch_009_pre2025_cagr_excess" / "run_batch_009_pre2025_cagr_excess.py"
_b9_spec = importlib.util.spec_from_file_location("batch9_runner_for_batch10", _b9_path)
batch9 = importlib.util.module_from_spec(_b9_spec)
assert _b9_spec and _b9_spec.loader
_b9_spec.loader.exec_module(batch9)

PROTOCOL = PROJECT / "protocol" / "BATCH_010_PRE2025_NEW_ACTIVE_FLOOR.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
YEARS = [2020, 2021, 2022, 2023, 2024]
HARD_MAX_DATE = pd.Timestamp("2024-12-31")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def geometric(values) -> float:
    array = np.asarray(list(values), dtype=float)
    if np.any(array <= -1):
        return -1.0
    return float(np.prod(1.0 + array) ** (1.0 / len(array)) - 1.0)


def validate_protocol() -> dict:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if protocol.get("status") != "preregistered_before_batch_010_results":
        raise RuntimeError("Batch010 protocol was not preregistered")
    if protocol.get("instruction_boundary_version") != "public-pre2025-v1" or not protocol.get("post_2024_forbidden"):
        raise RuntimeError("Batch010 isolation boundary mismatch")
    if protocol.get("candidate_count") != 15 or len(protocol.get("candidates", {})) != 15:
        raise RuntimeError("Batch010 fixed candidate count changed")
    if set(protocol["neighbors"]) != set(protocol["candidates"]):
        raise RuntimeError("Batch010 neighbor map incomplete")
    for name, neighbors in protocol["neighbors"].items():
        if not neighbors or any(item not in protocol["candidates"] for item in neighbors):
            raise RuntimeError(f"Invalid neighbor map for {name}")
    return protocol


def build_signals(panel: pd.DataFrame, name: str, spec: dict) -> pd.DataFrame:
    return batch4.candidate_signals(
        panel,
        name,
        batch4.component_m(panel, tuple(spec["M_internal"])),
        batch4.component_t(panel, tuple(spec["T_internal"])),
        batch4.component_h(panel, tuple(spec["H_internal"])),
        tuple(spec["outer"]),
    )


def sample_starts(calendar: list[pd.Timestamp], seed: int) -> pd.DataFrame:
    rng = np.random.Generator(np.random.PCG64(seed))
    rows = []
    for year in YEARS:
        pool = np.array(
            sorted(date for date in calendar if pd.Timestamp(f"{year}-01-01") <= date <= pd.Timestamp(f"{year}-03-31")),
            dtype="datetime64[ns]",
        )
        chosen = sorted(pd.Timestamp(pool[int(i)]) for i in rng.choice(len(pool), size=5, replace=False))
        rows.extend({"year": year, "start_rank": rank, "start_date": str(date.date())} for rank, date in enumerate(chosen, 1))
    result = pd.DataFrame(rows)
    if len(result) != 25 or result.groupby("year").start_date.nunique().ne(5).any():
        raise RuntimeError("Batch010 Q1 start sampling failed")
    return result


def benchmark_start_returns(starts: pd.DataFrame) -> dict[tuple[int, str], float]:
    frame = pd.read_parquet(batch6.BENCHMARK).sort_values("date")
    frame["date"] = pd.to_datetime(frame.date)
    frame["close"] = pd.to_numeric(frame.close, errors="raise")
    if frame.empty or frame.date.max() > HARD_MAX_DATE:
        raise RuntimeError("Batch010 benchmark boundary violation")
    result = {}
    for item in starts.itertuples(index=False):
        start = pd.Timestamp(item.start_date)
        before = frame.loc[frame.date < start, "close"]
        year_end = frame.loc[frame.date.dt.year.eq(int(item.year)), "close"]
        if before.empty or year_end.empty:
            raise RuntimeError(f"Benchmark start coverage missing for {item.start_date}")
        result[(int(item.year), item.start_date)] = float(year_end.iloc[-1] / before.iloc[-1] - 1.0)
    return result


def load_audit_actions() -> tuple[dict, set[str]]:
    actions, known = batch9.load_audit_actions()
    action_file = RESULTS / "audit" / "eastmoney_actions.json"
    gap_file = RESULTS / "audit" / "action_gaps.json"
    if not action_file.exists() or not gap_file.exists():
        return actions, known
    payload = json.loads(action_file.read_text(encoding="utf-8"))
    gaps = json.loads(gap_file.read_text(encoding="utf-8"))
    expected = {f"{symbol}/{year}" for symbol, year in gaps}
    if payload.get("cutoff") != "2024-12-31" or set(payload.get("records", {})) != expected:
        raise RuntimeError("Batch010 supplemental action scope/cutoff mismatch")
    for key, records in payload["records"].items():
        symbol = key.split("/")[0]
        known.add(key)
        for item in records:
            date = pd.Timestamp(item["dividOperateDate"]).normalize()
            if date > HARD_MAX_DATE:
                raise RuntimeError("Batch010 supplemental action crossed pre-2025 boundary")
            actions.setdefault((date, symbol), []).append({
                "cash": prior_audit.number(item.get("dividCashPsBeforeTax", 0)),
                "stock": prior_audit.number(item.get("dividStocksPs", 0)) + prior_audit.number(item.get("dividReserveToStockPs", 0)),
                "taxable_stock": prior_audit.number(item.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(item.get("dividPayDate") or item["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(item.get("dividStockMarketDate") or item["dividOperateDate"]).normalize(),
                "source": item.get("source", "Eastmoney stock_fhps_em via AkShare"),
            })
    return actions, known


def run_window(signals, bars, calendar, candidate, year, start, *, raw=False, actions=None, known=None, coverage=None, delistings=None, keep_trades=False):
    year_end = pd.Timestamp(f"{year}-12-31")
    last_session = max(date for date in calendar if date.year == year)
    cutoff = year_end - pd.Timedelta(days=37)
    selected = signals[signals.date.between(start, cutoff)].copy()
    old = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = start, last_session, cutoff, [year]
        return core.simulate(
            selected, bars, calendar, candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=keep_trades, actions=actions if raw else None,
            known_action_keys=known if raw else None, coverage_sink=coverage if raw else None,
            delist_dates=delistings if raw else None,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old


def base_gate_metrics(row: dict, start_group: pd.DataFrame, signal_counts: dict[int, int], benchmark: dict[int, float]) -> dict:
    returns = {year: float(row[f"return_{year}"]) for year in YEARS}
    active = {year: returns[year] - benchmark[year] for year in YEARS}
    loo_cagr, loo_excess = [], []
    for omitted in YEARS:
        kept = [year for year in YEARS if year != omitted]
        strategy_value = geometric(returns[year] for year in kept)
        benchmark_value = geometric(benchmark[year] for year in kept)
        loo_cagr.append(strategy_value)
        loo_excess.append(strategy_value - benchmark_value)
    expanding_cagr, expanding_excess = [], []
    for end in [2022, 2023, 2024]:
        kept = [year for year in YEARS if year <= end]
        strategy_value = geometric(returns[year] for year in kept)
        benchmark_value = geometric(benchmark[year] for year in kept)
        expanding_cagr.append(strategy_value)
        expanding_excess.append(strategy_value - benchmark_value)
    start_year_means = start_group.groupby("year", sort=True).return_value.mean()
    start_year_excess_means = start_group.groupby("year", sort=True).excess_return.mean()
    metrics = {
        "benchmark_cagr": geometric(benchmark[year] for year in YEARS),
        "annualized_excess": float(row["cagr"]) - geometric(benchmark[year] for year in YEARS),
        "mean_annual_excess": float(np.mean(list(active.values()))),
        "worst_annual_excess": float(min(active.values())),
        "worst_annual_return": float(min(returns.values())),
        "min_annual_signals": int(min(signal_counts.values())),
        "min_annual_trades": int(min(int(row[f"trades_{year}"]) for year in YEARS)),
        "loo_min_cagr": float(min(loo_cagr)),
        "loo_min_excess": float(min(loo_excess)),
        "expanding_min_cagr": float(min(expanding_cagr)),
        "expanding_min_excess": float(min(expanding_excess)),
        "start_min_year_mean": float(start_year_means.min()),
        "start_min_year_mean_excess": float(start_year_excess_means.min()),
        "start_positive_excess_fraction": float((start_group.excess_return > 0).mean()),
        "start_min_completed_trades": int(start_group.completed_trades.min()),
        "start_terminal_empty": bool(start_group.open_positions_at_end.eq(0).all() and start_group.pending_orders_at_end.eq(0).all()),
    }
    metrics["annual_gate"] = bool(
        metrics["worst_annual_return"] > 0 and metrics["worst_annual_excess"] > 0
        and metrics["min_annual_signals"] >= 180 and metrics["min_annual_trades"] >= 150
    )
    metrics["loo_gate"] = bool(metrics["loo_min_cagr"] > 0 and metrics["loo_min_excess"] > 0)
    metrics["expanding_gate"] = bool(metrics["expanding_min_cagr"] > 0 and metrics["expanding_min_excess"] > 0)
    metrics["start_gate"] = bool(
        metrics["start_terminal_empty"] and metrics["start_min_completed_trades"] >= 120
        and metrics["start_min_year_mean_excess"] > 0 and metrics["start_positive_excess_fraction"] >= 0.80
    )
    metrics["base_gate"] = bool(metrics["annual_gate"] and metrics["loo_gate"] and metrics["expanding_gate"] and metrics["start_gate"])
    return metrics


def score(full: pd.DataFrame, starts: pd.DataFrame, signals: dict[str, pd.DataFrame], benchmark: dict[int, float], protocol: dict) -> pd.DataFrame:
    rows = []
    for item in full.to_dict("records"):
        name = item["candidate"]
        counts = signals[name].groupby(signals[name].date.dt.year).size().reindex(YEARS, fill_value=0).to_dict()
        rows.append({**item, **base_gate_metrics(item, starts[starts.candidate.eq(name)], counts, benchmark)})
    output = pd.DataFrame(rows)
    base = dict(zip(output.candidate, output.base_gate))
    for metric in ["worst_annual_excess", "loo_min_excess", "expanding_min_excess", "start_min_year_mean_excess"]:
        lookup = dict(zip(output.candidate, output[metric]))
        output[f"neighbor_min_{metric}"] = output.candidate.map(
            lambda candidate: min(lookup[item] for item in [candidate] + protocol["neighbors"][candidate])
        )
    output["neighbor_members"] = output.candidate.map(
        lambda candidate: json.dumps([candidate] + protocol["neighbors"][candidate], ensure_ascii=False)
    )
    output["neighborhood_gate"] = output.candidate.map(
        lambda candidate: all(base[item] for item in [candidate] + protocol["neighbors"][candidate])
    ).astype(bool)
    for metric in ["worst_annual_excess", "loo_min_excess", "expanding_min_excess", "start_min_year_mean_excess"]:
        output["neighborhood_gate"] &= output[f"neighbor_min_{metric}"].gt(0)
    output["eligible"] = output.base_gate.astype(bool) & output.neighborhood_gate.astype(bool)
    return output.sort_values(
        [
            "eligible", "worst_annual_excess", "loo_min_excess", "start_min_year_mean_excess",
            "neighbor_min_worst_annual_excess", "neighbor_min_loo_min_excess",
            "neighbor_min_start_min_year_mean_excess", "mean_annual_excess", "annualized_excess", "cagr", "candidate",
        ],
        ascending=[False, False, False, False, False, False, False, False, False, False, True],
        kind="stable",
    ).reset_index(drop=True)


def make_start_row(candidate: str, item, run: dict, benchmark_start: dict[tuple[int, str], float]) -> dict:
    benchmark_return = benchmark_start[(int(item.year), item.start_date)]
    strategy_return = float(run[f"return_{item.year}"])
    return {
        "candidate": candidate,
        "year": int(item.year),
        "start_rank": int(item.start_rank),
        "start_date": item.start_date,
        "return_value": strategy_return,
        "benchmark_return": benchmark_return,
        "excess_return": strategy_return - benchmark_return,
        "completed_trades": int(run["completed_trades"]),
        "open_positions_at_end": int(run["open_positions_at_end"]),
        "pending_orders_at_end": int(run["pending_orders_at_end"]),
    }


def main() -> int:
    protocol = validate_protocol()
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.max() > pd.Timestamp("2024-11-22"):
        raise RuntimeError("Batch010 signal panel boundary violation")
    candidates = protocol["candidates"]
    signals = {name: build_signals(panel, name, spec) for name, spec in candidates.items()}
    symbols = set().union(*(set(frame.symbol.astype(str)) for frame in signals.values()))
    bars, calendar = core.load_execution_bars(symbols, force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch010 execution data crossed 2024-12-31")
    benchmark, benchmark_audit = batch6.load_benchmark()
    starts = sample_starts(calendar, int(protocol["shared_q1_random_starts"]["seed"]))
    benchmark_start = benchmark_start_returns(starts)
    starts = starts.assign(benchmark_return=starts.apply(lambda row: benchmark_start[(int(row.year), row.start_date)], axis=1))
    starts.to_csv(RESULTS / "sampled_start_dates.csv", index=False, encoding="utf-8-sig")
    full_rows, start_rows = [], []
    for index, (name, signal_frame) in enumerate(signals.items(), 1):
        row, _ = core.simulate(signal_frame, bars, calendar, name, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5)
        row["candidate"] = name
        row["spec_json"] = json.dumps(candidates[name], ensure_ascii=False, sort_keys=True)
        full_rows.append(row)
        for item in starts.itertuples(index=False):
            run, _ = run_window(signal_frame, bars, calendar, name, int(item.year), pd.Timestamp(item.start_date))
            start_rows.append(make_start_row(name, item, run, benchmark_start))
        print(f"batch010 screening {index}/15 {name}", flush=True)
    full = pd.DataFrame(full_rows)
    random_runs = pd.DataFrame(start_rows)
    if len(full) != 15 or len(random_runs) != 375:
        raise RuntimeError("Batch010 fixed run count mismatch")
    ranked = score(full, random_runs, signals, benchmark, protocol)
    full.to_csv(RESULTS / "full_window_screening.csv", index=False, encoding="utf-8-sig")
    random_runs.to_csv(RESULTS / "shared_q1_random_start_runs_375.csv", index=False, encoding="utf-8-sig")
    ranked.to_csv(RESULTS / "candidate_ranking_all.csv", index=False, encoding="utf-8-sig")
    eligible = ranked[ranked.eligible.astype(bool)]
    if eligible.empty:
        (RESULTS / "NO_CHAMPION.json").write_text(json.dumps({"status": "no_candidate_passed_hard_gates", "protocol_sha256": sha256(PROTOCOL)}, indent=2), encoding="utf-8")
        return 2
    champion = str(eligible.iloc[0].candidate)
    signals[champion].to_parquet(RESULTS / "champion_signals_screening.parquet", index=False)
    selection = {
        "status": "unique_champion_frozen_pending_independent_raw_audit",
        "protocol_id": protocol["protocol_id"],
        "champion": champion,
        "champion_spec": candidates[champion],
        "selection_row": eligible.iloc[0].to_dict(),
        "qualified_candidate_count": int(len(eligible)),
        "candidate_count": 15,
        "random_start_runs": 375,
        "benchmark": benchmark_audit,
        "assertions": {
            "instruction_boundary_version": "public-pre2025-v1", "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()), "maximum_execution_date": str(max(calendar).date()),
            "no_candidate_expansion": True, "active_floor_ranked_first": True, "production_change": False,
        },
        "source_hashes": {
            "protocol": sha256(PROTOCOL), "base_panel": sha256(BASE_PANEL),
            "benchmark": sha256(batch6.BENCHMARK), "runner": sha256(Path(__file__)),
        },
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    audit_dir = RESULTS / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(signals[champion].symbol.astype(str)))
    raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    raw_signals = signals[champion].drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if raw_signals.raw_close.isna().any():
        raise RuntimeError("Batch010 raw audit signal close missing")
    raw_signals = raw_signals.rename(columns={"raw_close": "close"})
    actions, known = load_audit_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    audit_row, audit_trades = core.simulate(
        raw_signals, raw_bars, raw_calendar, champion, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing, delist_dates=delistings,
    )
    audit_trades.to_csv(audit_dir / "champion_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_start_rows, raw_start_trades = [], []
    for item in starts.itertuples(index=False):
        run, trades = run_window(
            raw_signals, raw_bars, raw_calendar, champion, int(item.year), pd.Timestamp(item.start_date),
            raw=True, actions=actions, known=known, coverage=missing, delistings=delistings, keep_trades=True,
        )
        raw_start_rows.append(make_start_row(champion, item, run, benchmark_start))
        if not trades.empty:
            trades = trades.copy()
            trades.insert(0, "run_start_date", item.start_date)
            raw_start_trades.append(trades)
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(audit_dir / "champion_shared_q1_random_start_audit_25.csv", index=False, encoding="utf-8-sig")
    if raw_start_trades:
        pd.concat(raw_start_trades, ignore_index=True).to_csv(audit_dir / "champion_shared_q1_random_start_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
    signal_counts = raw_signals.groupby(raw_signals.date.dt.year).size().reindex(YEARS, fill_value=0).to_dict()
    raw_metrics = base_gate_metrics(audit_row, raw_starts, signal_counts, benchmark)
    audit_pass = bool(
        not missing and raw_metrics["base_gate"] and audit_row["open_positions_at_end"] == 0
        and audit_row["pending_orders_at_end"] == 0 and raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE
    )
    audit = {
        "status": "complete" if audit_pass else "audit_failed",
        "champion_frozen_before_audit": champion,
        "audit_did_not_trigger_reselection": True,
        "audited_champion": audit_row,
        "raw_hard_gate_metrics": raw_metrics,
        "missing_corporate_action_keys": sorted(missing),
        "assertions": {
            "maximum_raw_date": str(raw_all.date.max().date()), "maximum_execution_date": str(max(raw_calendar).date()),
            "pre2025_boundary_passed": raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE,
            "corporate_action_coverage_complete": not missing, "raw_hard_gates_passed": raw_metrics["base_gate"],
            "full_window_terminal_empty": audit_row["open_positions_at_end"] == 0 and audit_row["pending_orders_at_end"] == 0,
            "random_start_run_count_exact_25": len(raw_starts) == 25, "production_change": False,
        },
        "source_hashes": {"protocol": sha256(PROTOCOL), "selection": sha256(RESULTS / "SELECTION.json"), "runner": sha256(Path(__file__))},
    }
    (audit_dir / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"champion": champion, "qualified": len(eligible), "audit_status": audit["status"], "missing_actions": len(missing)}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
