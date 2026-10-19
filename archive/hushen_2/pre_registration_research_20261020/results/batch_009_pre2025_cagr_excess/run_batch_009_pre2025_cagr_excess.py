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

_b8_path = PROJECT / "results" / "batch_008_pre2025_migration" / "run_batch_008_pre2025_migration.py"
_b8_spec = importlib.util.spec_from_file_location("batch8_runner", _b8_path)
batch8 = importlib.util.module_from_spec(_b8_spec)
assert _b8_spec and _b8_spec.loader
_b8_spec.loader.exec_module(batch8)

PROTOCOL = PROJECT / "protocol" / "BATCH_009_PRE2025_CAGR_EXCESS.json"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
YEARS = [2020, 2021, 2022, 2023, 2024]
HARD_MAX_DATE = pd.Timestamp("2024-12-31")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def geometric(values) -> float:
    a = np.asarray(list(values), dtype=float)
    if np.any(a <= -1):
        return -1.0
    return float(np.prod(1.0 + a) ** (1.0 / len(a)) - 1.0)


def validate_protocol() -> dict:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p.get("status") != "preregistered_before_batch_009_results":
        raise RuntimeError("Batch009 protocol is not preregistered")
    if p.get("instruction_boundary_version") != "public-pre2025-v1" or not p.get("post_2024_forbidden"):
        raise RuntimeError("Batch009 isolation boundary mismatch")
    if len(p.get("candidates", {})) != 13 or p.get("candidate_count") != 13:
        raise RuntimeError("Batch009 candidate count changed")
    if set(p["neighbors"]) != set(p["candidates"]):
        raise RuntimeError("Batch009 neighbor map incomplete")
    for name, neighbors in p["neighbors"].items():
        if not neighbors or any(x not in p["candidates"] for x in neighbors):
            raise RuntimeError(f"Invalid neighbor map: {name}")
    return p


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
        pool = np.array(sorted(d for d in calendar if pd.Timestamp(f"{year}-01-01") <= d <= pd.Timestamp(f"{year}-03-31")), dtype="datetime64[ns]")
        chosen = sorted(pd.Timestamp(pool[int(i)]) for i in rng.choice(len(pool), size=5, replace=False))
        rows.extend({"year": year, "start_rank": rank, "start_date": str(date.date())} for rank, date in enumerate(chosen, 1))
    out = pd.DataFrame(rows)
    if len(out) != 25 or out.groupby("year").start_date.nunique().ne(5).any():
        raise RuntimeError("Batch009 Q1 start sampling failed")
    return out


def load_audit_actions() -> tuple[dict, set[str]]:
    actions, known = batch8.load_audit_actions()
    action_file = RESULTS / "audit" / "eastmoney_actions.json"
    gap_file = RESULTS / "audit" / "action_gaps.json"
    if not action_file.exists() or not gap_file.exists():
        return actions, known
    payload = json.loads(action_file.read_text(encoding="utf-8"))
    gaps = json.loads(gap_file.read_text(encoding="utf-8"))
    expected = {f"{symbol}/{year}" for symbol, year in gaps}
    if payload.get("cutoff") != "2024-12-31" or set(payload.get("records", {})) != expected:
        raise RuntimeError("Batch009 supplemental action scope/cutoff mismatch")
    for key, records in payload["records"].items():
        symbol = key.split("/")[0]
        known.add(key)
        for item in records:
            date = pd.Timestamp(item["dividOperateDate"]).normalize()
            if date > HARD_MAX_DATE:
                raise RuntimeError("Batch009 supplemental action crossed pre-2025 boundary")
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
    last_session = max(d for d in calendar if d.year == year)
    cutoff = year_end - pd.Timedelta(days=37)
    selected = signals[signals.date.between(start, cutoff)].copy()
    old = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = start, last_session, cutoff, [year]
        return core.simulate(
            selected, bars, calendar, candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=keep_trades, actions=actions if raw else None, known_action_keys=known if raw else None,
            coverage_sink=coverage if raw else None, delist_dates=delistings if raw else None,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old


def base_gate_metrics(row: dict, start_group: pd.DataFrame, signal_counts: dict[int, int], benchmark: dict[int, float]) -> dict:
    returns = {y: float(row[f"return_{y}"]) for y in YEARS}
    active = {y: returns[y] - benchmark[y] for y in YEARS}
    loo_cagrs, loo_excess = [], []
    for omitted in YEARS:
        kept = [y for y in YEARS if y != omitted]
        s, b = geometric(returns[y] for y in kept), geometric(benchmark[y] for y in kept)
        loo_cagrs.append(s); loo_excess.append(s - b)
    expanding_cagrs, expanding_excess = [], []
    for end in [2022, 2023, 2024]:
        kept = [y for y in YEARS if y <= end]
        s, b = geometric(returns[y] for y in kept), geometric(benchmark[y] for y in kept)
        expanding_cagrs.append(s); expanding_excess.append(s - b)
    start_year_means = start_group.groupby("year").return_value.mean()
    benchmark_cagr = geometric(benchmark[y] for y in YEARS)
    metrics = {
        "benchmark_cagr": benchmark_cagr,
        "annualized_excess": float(row["cagr"]) - benchmark_cagr,
        "mean_annual_excess": float(np.mean(list(active.values()))),
        "worst_annual_excess": float(min(active.values())),
        "worst_annual_return": float(min(returns.values())),
        "min_annual_signals": int(min(signal_counts.values())),
        "min_annual_trades": int(min(int(row[f"trades_{y}"]) for y in YEARS)),
        "loo_min_cagr": float(min(loo_cagrs)),
        "loo_min_excess": float(min(loo_excess)),
        "expanding_min_cagr": float(min(expanding_cagrs)),
        "expanding_min_excess": float(min(expanding_excess)),
        "start_min_year_mean": float(start_year_means.min()),
        "start_positive_fraction": float((start_group.return_value > 0).mean()),
        "start_min_completed_trades": int(start_group.completed_trades.min()),
        "start_terminal_empty": bool(start_group.open_positions_at_end.eq(0).all() and start_group.pending_orders_at_end.eq(0).all()),
    }
    metrics["annual_gate"] = bool(
        metrics["worst_annual_return"] > 0 and metrics["min_annual_signals"] >= 180
        and metrics["min_annual_trades"] >= 150 and metrics["worst_annual_excess"] >= -0.10
        and metrics["mean_annual_excess"] > 0
    )
    metrics["loo_gate"] = bool(metrics["loo_min_cagr"] > 0 and metrics["loo_min_excess"] > 0)
    metrics["expanding_gate"] = bool(metrics["expanding_min_cagr"] > 0 and metrics["expanding_min_excess"] > 0)
    metrics["start_gate"] = bool(
        metrics["start_terminal_empty"] and metrics["start_min_completed_trades"] >= 120
        and metrics["start_min_year_mean"] > 0 and metrics["start_positive_fraction"] >= 0.80
    )
    metrics["base_gate"] = bool(metrics["annual_gate"] and metrics["loo_gate"] and metrics["expanding_gate"] and metrics["start_gate"])
    return metrics


def score(full: pd.DataFrame, starts: pd.DataFrame, signals: dict[str, pd.DataFrame], benchmark: dict[int, float], protocol: dict) -> pd.DataFrame:
    rows = []
    for item in full.to_dict("records"):
        name = item["candidate"]
        counts = signals[name].groupby(signals[name].date.dt.year).size().reindex(YEARS, fill_value=0).to_dict()
        metrics = base_gate_metrics(item, starts[starts.candidate == name], counts, benchmark)
        rows.append({**item, **metrics})
    out = pd.DataFrame(rows)
    base_map = dict(zip(out.candidate, out.base_gate))
    cagr_map = dict(zip(out.candidate, out.cagr))
    excess_map = dict(zip(out.candidate, out.annualized_excess))
    out["neighbor_members"] = out.candidate.map(lambda c: json.dumps([c] + protocol["neighbors"][c], ensure_ascii=False))
    out["neighbor_min_cagr"] = out.candidate.map(lambda c: min(cagr_map[x] for x in [c] + protocol["neighbors"][c]))
    out["neighbor_min_annualized_excess"] = out.candidate.map(lambda c: min(excess_map[x] for x in [c] + protocol["neighbors"][c]))
    out["neighborhood_gate"] = out.candidate.map(lambda c: all(base_map[x] for x in [c] + protocol["neighbors"][c])).astype(bool) & out.neighbor_min_cagr.gt(0) & out.neighbor_min_annualized_excess.gt(0)
    out["eligible"] = out.base_gate.astype(bool) & out.neighborhood_gate.astype(bool)
    eligible = out.eligible.astype(bool)
    out["rank_cagr"] = np.nan; out["rank_annualized_excess"] = np.nan; out["joint_score"] = np.nan
    out.loc[eligible, "rank_cagr"] = out.loc[eligible, "cagr"].rank(pct=True, method="average")
    out.loc[eligible, "rank_annualized_excess"] = out.loc[eligible, "annualized_excess"].rank(pct=True, method="average")
    out.loc[eligible, "joint_score"] = 0.5 * out.loc[eligible, "rank_cagr"] + 0.5 * out.loc[eligible, "rank_annualized_excess"]
    return out.sort_values(
        ["eligible", "joint_score", "mean_annual_excess", "worst_annual_excess", "start_min_year_mean", "candidate"],
        ascending=[False, False, False, False, False, True], kind="stable", na_position="last",
    ).reset_index(drop=True)


def main() -> int:
    protocol = validate_protocol()
    RESULTS.mkdir(parents=True, exist_ok=True)
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.max() > pd.Timestamp("2024-11-22"):
        raise RuntimeError("Batch009 signal panel boundary violation")
    candidates = protocol["candidates"]
    signals = {name: build_signals(panel, name, spec) for name, spec in candidates.items()}
    symbols = set().union(*(set(x.symbol.astype(str)) for x in signals.values()))
    bars, calendar = core.load_execution_bars(symbols, force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Batch009 execution data crossed 2024-12-31")
    benchmark, benchmark_audit = batch6.load_benchmark()
    starts = sample_starts(calendar, int(protocol["shared_q1_random_starts"]["seed"]))
    starts.to_csv(RESULTS / "sampled_start_dates.csv", index=False, encoding="utf-8-sig")
    full_rows, start_rows = [], []
    for i, (name, sig) in enumerate(signals.items(), 1):
        row, _ = core.simulate(sig, bars, calendar, name, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5)
        row["candidate"] = name; row["spec_json"] = json.dumps(candidates[name], ensure_ascii=False, sort_keys=True)
        full_rows.append(row)
        for start in starts.itertuples(index=False):
            r, _ = run_window(sig, bars, calendar, name, int(start.year), pd.Timestamp(start.start_date))
            start_rows.append({
                "candidate": name, "year": int(start.year), "start_rank": int(start.start_rank), "start_date": start.start_date,
                "return_value": float(r[f"return_{start.year}"]), "completed_trades": int(r["completed_trades"]),
                "open_positions_at_end": int(r["open_positions_at_end"]), "pending_orders_at_end": int(r["pending_orders_at_end"]),
            })
        print(f"batch009 screening {i}/13 {name}", flush=True)
    full, random_runs = pd.DataFrame(full_rows), pd.DataFrame(start_rows)
    if len(full) != 13 or len(random_runs) != 325:
        raise RuntimeError("Batch009 run count mismatch")
    ranked = score(full, random_runs, signals, benchmark, protocol)
    full.to_csv(RESULTS / "full_window_screening.csv", index=False, encoding="utf-8-sig")
    random_runs.to_csv(RESULTS / "shared_q1_random_start_runs_325.csv", index=False, encoding="utf-8-sig")
    ranked.to_csv(RESULTS / "candidate_ranking_all.csv", index=False, encoding="utf-8-sig")
    eligible = ranked[ranked.eligible.astype(bool)]
    if eligible.empty:
        (RESULTS / "NO_CHAMPION.json").write_text(json.dumps({"status": "no_candidate_passed_hard_gates", "protocol_sha256": sha256(PROTOCOL)}, indent=2), encoding="utf-8")
        return 2
    champion = str(eligible.iloc[0].candidate)
    signals[champion].to_parquet(RESULTS / "champion_signals_screening.parquet", index=False)
    selection = {
        "status": "unique_champion_frozen_pending_independent_raw_audit", "protocol_id": protocol["protocol_id"],
        "champion": champion, "champion_spec": candidates[champion], "selection_row": eligible.iloc[0].to_dict(),
        "qualified_candidate_count": int(len(eligible)), "candidate_count": 13, "random_start_runs": 325,
        "benchmark": benchmark_audit,
        "assertions": {"instruction_boundary_version": "public-pre2025-v1", "post_2024_access": False, "maximum_panel_date": str(panel.date.max().date()), "maximum_execution_date": str(max(calendar).date()), "no_candidate_expansion": True, "hard_gates_before_return_ranking": True, "production_change": False},
        "source_hashes": {"protocol": sha256(PROTOCOL), "base_panel": sha256(BASE_PANEL), "benchmark": sha256(batch6.BENCHMARK), "runner": sha256(Path(__file__))},
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Independent post-freeze audit on raw OHLC and complete known pre-2025 actions/delistings.
    audit_dir = RESULTS / "audit"; audit_dir.mkdir(parents=True, exist_ok=True)
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(signals[champion].symbol.astype(str)))
    raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    raw_signals = signals[champion].drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if raw_signals.raw_close.isna().any():
        raise RuntimeError("Raw audit signal close missing")
    raw_signals = raw_signals.rename(columns={"raw_close": "close"})
    actions, known = load_audit_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    audit_row, audit_trades = core.simulate(raw_signals, raw_bars, raw_calendar, champion, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5, keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing, delist_dates=delistings)
    audit_row.update(batch6.active_metrics(audit_row, benchmark))
    audit_trades.to_csv(audit_dir / "champion_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_start_rows, raw_start_trades = [], []
    for start in starts.itertuples(index=False):
        r, trades = run_window(raw_signals, raw_bars, raw_calendar, champion, int(start.year), pd.Timestamp(start.start_date), raw=True, actions=actions, known=known, coverage=missing, delistings=delistings, keep_trades=True)
        raw_start_rows.append({"candidate": champion, "year": int(start.year), "start_rank": int(start.start_rank), "start_date": start.start_date, "return_value": float(r[f"return_{start.year}"]), "completed_trades": int(r["completed_trades"]), "open_positions_at_end": int(r["open_positions_at_end"]), "pending_orders_at_end": int(r["pending_orders_at_end"])})
        if not trades.empty:
            trades = trades.copy(); trades.insert(0, "run_start_date", start.start_date); raw_start_trades.append(trades)
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(audit_dir / "champion_shared_q1_random_start_audit_25.csv", index=False, encoding="utf-8-sig")
    if raw_start_trades:
        pd.concat(raw_start_trades, ignore_index=True).to_csv(audit_dir / "champion_shared_q1_random_start_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(audit_dir / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")
    signal_counts = raw_signals.groupby(raw_signals.date.dt.year).size().reindex(YEARS, fill_value=0).to_dict()
    raw_metrics = base_gate_metrics(audit_row, raw_starts, signal_counts, benchmark)
    audit_pass = bool(not missing and raw_metrics["base_gate"] and audit_row["open_positions_at_end"] == 0 and audit_row["pending_orders_at_end"] == 0 and raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE)
    audit = {
        "status": "complete" if audit_pass else "audit_failed", "champion_frozen_before_audit": champion,
        "audit_did_not_trigger_reselection": True, "audited_champion": audit_row, "raw_hard_gate_metrics": raw_metrics,
        "missing_corporate_action_keys": sorted(missing),
        "assertions": {"maximum_raw_date": str(raw_all.date.max().date()), "maximum_execution_date": str(max(raw_calendar).date()), "pre2025_boundary_passed": raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE, "corporate_action_coverage_complete": not missing, "raw_hard_gates_passed": raw_metrics["base_gate"], "full_window_terminal_empty": audit_row["open_positions_at_end"] == 0 and audit_row["pending_orders_at_end"] == 0, "random_start_run_count_exact_25": len(raw_starts) == 25, "production_change": False},
        "source_hashes": {"protocol": sha256(PROTOCOL), "selection": sha256(RESULTS / "SELECTION.json"), "runner": sha256(Path(__file__))},
    }
    (audit_dir / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"champion": champion, "qualified": len(eligible), "audit_status": audit["status"]}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
