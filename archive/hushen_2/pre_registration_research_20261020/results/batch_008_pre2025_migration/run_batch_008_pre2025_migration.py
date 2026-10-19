from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parents[2] / "research"
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import run_batch_004 as batch4  # noqa: E402
import run_batch_006 as batch6  # noqa: E402
import run_batch_007_pre2025 as batch7  # noqa: E402
import audit_champion as prior_audit  # noqa: E402

PROJECT = core.PROJECT
PROTOCOL = PROJECT / "protocol" / "BATCH_008_PRE2025_MIGRATION.json"
RESULTS = PROJECT / "results" / "batch_008_pre2025_migration"
BASE_PANEL = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "base_component_panel_pre2025.parquet"
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
YEARS = [2020, 2021, 2022, 2023, 2024]
EXECUTION = {"entry": 0.0, "hold": 30, "take": 4.0, "stop": 1.5}
SUPPLEMENTAL_ACTIONS = RESULTS / "audit" / "eastmoney_actions.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_protocol() -> dict:
    p = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if p.get("status") != "preregistered_before_batch_008_results":
        raise RuntimeError("Batch008 protocol status mismatch")
    if p.get("instruction_boundary_version") != "public-pre2025-v1" or not p.get("post_2024_forbidden"):
        raise RuntimeError("Batch008 isolation boundary mismatch")
    if len(p.get("candidates", {})) != 9 or p.get("candidate_count") != 9:
        raise RuntimeError("Batch008 fixed candidate count mismatch")
    expected = {
        "BATCH_004.json_sha256": PROJECT / "protocol" / "BATCH_004.json",
        "BATCH_006.json_sha256": PROJECT / "protocol" / "BATCH_006.json",
        "BATCH_007_PRE2025.json_sha256": PROJECT / "protocol" / "BATCH_007_PRE2025.json",
    }
    for key, path in expected.items():
        if p["prior_sources_reviewed"][key] != sha256(path):
            raise RuntimeError(f"Frozen prior source changed: {key}")
    return p


def build_signals(panel: pd.DataFrame, candidate: str, spec: dict) -> pd.DataFrame:
    weights = {k: tuple(float(x) for x in spec[k]) for k in ["M_internal", "T_internal", "H_internal", "outer"]}
    return batch4.candidate_signals(
        panel,
        candidate,
        batch4.component_m(panel, weights["M_internal"]),
        batch4.component_t(panel, weights["T_internal"]),
        batch4.component_h(panel, weights["H_internal"]),
        weights["outer"],
    )


def sample_starts(calendar: list[pd.Timestamp], seed: int, per_year: int) -> pd.DataFrame:
    rng = np.random.Generator(np.random.PCG64(seed))
    rows = []
    for year in YEARS:
        pool = np.array(
            sorted(d for d in calendar if pd.Timestamp(f"{year}-01-01") <= d <= pd.Timestamp(f"{year}-03-31")),
            dtype="datetime64[ns]",
        )
        positions = rng.choice(len(pool), size=per_year, replace=False)
        for rank, value in enumerate(sorted(pd.Timestamp(pool[int(i)]) for i in positions), 1):
            rows.append({"year": year, "start_rank": rank, "start_date": str(value.date())})
    out = pd.DataFrame(rows)
    if len(out) != len(YEARS) * per_year or out.groupby("year").start_date.nunique().ne(per_year).any():
        raise RuntimeError("Batch008 fixed-start sampling failed")
    return out


def run_window(signals: pd.DataFrame, bars: dict, calendar: list[pd.Timestamp], candidate: str,
               year: int, start: pd.Timestamp, *, raw: bool = False, actions=None, known=None,
               coverage=None, delistings=None, keep_trades: bool = False) -> tuple[dict, pd.DataFrame]:
    year_end = pd.Timestamp(f"{year}-12-31")
    last_session = max(d for d in calendar if d.year == year)
    cutoff = year_end - pd.Timedelta(days=37)
    selected = signals[signals.date.between(start, cutoff)].copy()
    old = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = start, last_session, cutoff, [year]
        return core.simulate(
            selected, bars, calendar, candidate, EXECUTION["entry"], EXECUTION["hold"],
            "take4.00_stop1.50", EXECUTION["take"], EXECUTION["stop"], keep_trades=keep_trades,
            actions=actions if raw else None, known_action_keys=known if raw else None,
            coverage_sink=coverage if raw else None, delist_dates=delistings if raw else None,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old


def rank_high(series: pd.Series) -> pd.Series:
    return series.rank(pct=True, method="average", ascending=True)


def differing_blocks(a: dict, b: dict) -> int:
    return sum(list(a[k]) != list(b[k]) for k in ["M_internal", "T_internal", "H_internal", "outer"])


def load_audit_actions() -> tuple[dict, set[str]]:
    actions, known = batch7.load_actions_batch007()
    payload = json.loads(SUPPLEMENTAL_ACTIONS.read_text(encoding="utf-8"))
    gaps = json.loads((RESULTS / "audit" / "action_gaps.json").read_text(encoding="utf-8"))
    expected = {f"{symbol}/{year}" for symbol, year in gaps}
    if payload.get("cutoff") != "2024-12-31" or set(payload.get("records", {})) != expected:
        raise RuntimeError("Batch008 supplemental action response scope/cutoff mismatch")
    for key, records in payload["records"].items():
        symbol = key.split("/")[0]
        known.add(key)
        for item in records:
            date = pd.Timestamp(item["dividOperateDate"]).normalize()
            if date > HARD_MAX_DATE:
                raise RuntimeError("Supplemental action crossed pre-2025 boundary")
            actions.setdefault((date, symbol), []).append({
                "cash": prior_audit.number(item.get("dividCashPsBeforeTax", 0)),
                "stock": prior_audit.number(item.get("dividStocksPs", 0)) + prior_audit.number(item.get("dividReserveToStockPs", 0)),
                "taxable_stock": prior_audit.number(item.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(item.get("dividPayDate") or item["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(item.get("dividStockMarketDate") or item["dividOperateDate"]).normalize(),
                "source": item.get("source", "Eastmoney stock_fhps_em via AkShare"),
            })
    return actions, known


def score_candidates(full: pd.DataFrame, starts: pd.DataFrame, benchmark: dict[int, float], candidates: dict) -> pd.DataFrame:
    scored = full.copy()
    for year in YEARS:
        scored[f"active_{year}"] = scored[f"return_{year}"] - benchmark[year]
    scored["annual_abs_min"] = scored[[f"return_{y}" for y in YEARS]].min(axis=1)
    scored["annual_abs_mean"] = scored[[f"return_{y}" for y in YEARS]].mean(axis=1)
    scored["annual_active_min"] = scored[[f"active_{y}" for y in YEARS]].min(axis=1)
    scored["annual_active_mean"] = scored[[f"active_{y}" for y in YEARS]].mean(axis=1)
    annual_rank_cols = []
    for col in ["annual_abs_min", "annual_abs_mean", "annual_active_min", "annual_active_mean"]:
        rcol = f"rank_{col}"
        scored[rcol] = rank_high(scored[col])
        annual_rank_cols.append(rcol)
    scored["annual_core"] = scored[annual_rank_cols].min(axis=1)

    loo_columns = []
    for omitted in YEARS:
        train = [y for y in YEARS if y != omitted]
        components = pd.DataFrame({
            "abs_min": scored[[f"return_{y}" for y in train]].min(axis=1),
            "abs_mean": scored[[f"return_{y}" for y in train]].mean(axis=1),
            "active_min": scored[[f"active_{y}" for y in train]].min(axis=1),
            "active_mean": scored[[f"active_{y}" for y in train]].mean(axis=1),
        })
        name = f"loo_core_omit_{omitted}"
        scored[name] = pd.concat([rank_high(components[c]) for c in components], axis=1).min(axis=1)
        loo_columns.append(name)
    scored["loo_floor"] = scored[loo_columns].min(axis=1)

    annual_start_means = starts.groupby(["candidate", "year"], sort=True).return_value.mean().unstack("year")
    annual_start_means = annual_start_means.reindex(scored.candidate)
    scored["start_worst_year_mean"] = annual_start_means.min(axis=1).to_numpy()
    scored["start_mean"] = annual_start_means.mean(axis=1).to_numpy()
    scored["start_positive_fraction"] = starts.groupby("candidate").return_value.apply(lambda x: float((x > 0).mean())).reindex(scored.candidate).to_numpy()
    scored["start_floor_rank"] = rank_high(scored["start_worst_year_mean"])

    annual_core_map = dict(zip(scored.candidate, scored.annual_core))
    neighbor_members = {}
    neighbor_floor = []
    for candidate in scored.candidate:
        members = [other for other in scored.candidate if differing_blocks(candidates[candidate], candidates[other]) <= 1]
        neighbor_members[candidate] = members
        neighbor_floor.append(min(annual_core_map[x] for x in members))
    scored["neighbor_members"] = scored.candidate.map(lambda x: json.dumps(neighbor_members[x], ensure_ascii=False))
    scored["neighbor_floor"] = neighbor_floor
    migration_cols = ["annual_core", "loo_floor", "start_floor_rank", "neighbor_floor"]
    scored["migration_floor"] = scored[migration_cols].min(axis=1)
    scored["migration_mean"] = scored[migration_cols].mean(axis=1)
    scored["eligible"] = (
        scored[[f"trades_{y}" for y in YEARS]].ge(20).all(axis=1)
        & scored[[f"return_{y}" for y in YEARS]].gt(0).sum(axis=1).ge(3)
        & scored.candidate.map(starts.groupby("candidate").failed.any()).eq(False)
    )
    return scored.sort_values(
        ["eligible", "migration_floor", "migration_mean", "annual_abs_min", "annual_active_min", "annual_abs_mean", "annual_active_mean", "candidate"],
        ascending=[False, False, False, False, False, False, False, True], kind="stable",
    ).reset_index(drop=True)


def main() -> int:
    protocol = validate_protocol()
    RESULTS.mkdir(parents=True, exist_ok=True)
    if not BASE_PANEL.exists():
        raise RuntimeError("Verified Batch004 pre-2025 component panel is missing")
    panel = pd.read_parquet(BASE_PANEL)
    panel["date"] = pd.to_datetime(panel.date)
    if panel.empty or panel.date.max() > pd.Timestamp("2024-11-22"):
        raise RuntimeError("Panel violates Batch008 signal boundary")
    candidates = protocol["candidates"]
    signals_by_candidate = {name: build_signals(panel, name, spec) for name, spec in candidates.items()}
    symbols = set().union(*(set(frame.symbol.astype(str)) for frame in signals_by_candidate.values()))
    bars, calendar = core.load_execution_bars(symbols, force=False)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("QFQ execution calendar crossed pre-2025 boundary")
    benchmark, benchmark_audit = batch6.load_benchmark()
    starts = sample_starts(calendar, int(protocol["random_start_screen"]["seed"]), 5)
    starts.to_csv(RESULTS / "sampled_start_dates.csv", index=False, encoding="utf-8-sig")

    full_rows, start_rows = [], []
    for index, (candidate, signals) in enumerate(signals_by_candidate.items(), 1):
        row, _ = core.simulate(signals, bars, calendar, candidate, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5)
        row["candidate"] = candidate
        row["spec_json"] = json.dumps(candidates[candidate], ensure_ascii=False, sort_keys=True)
        full_rows.append(row)
        for item in starts.itertuples(index=False):
            result, _ = run_window(signals, bars, calendar, candidate, int(item.year), pd.Timestamp(item.start_date))
            start_rows.append({
                "candidate": candidate, "year": int(item.year), "start_rank": int(item.start_rank),
                "start_date": item.start_date, "return_value": float(result[f"return_{item.year}"]),
                "completed_trades": int(result["completed_trades"]),
                "open_positions_at_end": int(result["open_positions_at_end"]),
                "pending_orders_at_end": int(result["pending_orders_at_end"]),
                "failed": bool(result["open_positions_at_end"] or result["pending_orders_at_end"]),
            })
        print(f"batch008 screening {index}/9 {candidate}", flush=True)
    full = pd.DataFrame(full_rows)
    random_runs = pd.DataFrame(start_rows)
    if len(full) != 9 or len(random_runs) != 225:
        raise RuntimeError("Batch008 screening run count mismatch")
    ranked = score_candidates(full, random_runs, benchmark, candidates)
    full.to_csv(RESULTS / "full_window_screening.csv", index=False, encoding="utf-8-sig")
    random_runs.to_csv(RESULTS / "random_start_screening_225.csv", index=False, encoding="utf-8-sig")
    ranked.to_csv(RESULTS / "candidate_ranking.csv", index=False, encoding="utf-8-sig")
    eligible = ranked[ranked.eligible.astype(bool)]
    if eligible.empty:
        raise RuntimeError("No preregistered Batch008 candidate passed eligibility")
    champion = str(eligible.iloc[0].candidate)
    champion_signals = signals_by_candidate[champion]
    champion_signals.to_parquet(RESULTS / "champion_signals_screening.parquet", index=False)

    selection = {
        "status": "unique_champion_frozen_pending_independent_raw_audit",
        "protocol_id": protocol["protocol_id"],
        "champion": champion,
        "champion_spec": candidates[champion],
        "selection_row": eligible.iloc[0].to_dict(),
        "candidate_count": len(full),
        "random_start_screening_runs": len(random_runs),
        "benchmark": benchmark_audit,
        "assertions": {
            "instruction_boundary_version": "public-pre2025-v1", "post_2024_access": False,
            "maximum_panel_date": str(panel.date.max().date()), "maximum_execution_date": str(max(calendar).date()),
            "candidate_count_exact_9": len(full) == 9, "random_start_runs_exact_225": len(random_runs) == 225,
            "no_candidate_expansion": True, "cagr_not_used_for_selection": True,
        },
        "source_hashes": {"protocol": sha256(PROTOCOL), "base_panel": sha256(BASE_PANEL), "benchmark": sha256(batch6.BENCHMARK)},
        "production_change": False,
    }
    (RESULTS / "SELECTION.json").write_text(json.dumps(selection, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # Independent raw-price and corporate-action audit after the unique champion is frozen.
    (RESULTS / "audit").mkdir(parents=True, exist_ok=True)
    raw_bars, raw_calendar, raw_all, raw_manifest = batch7.load_raw_pre2025(set(champion_signals.symbol.astype(str)))
    raw_close = raw_all[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    raw_signals = champion_signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if raw_signals.raw_close.isna().any():
        raise RuntimeError("Raw audit signal close missing")
    raw_signals = raw_signals.rename(columns={"raw_close": "close"})
    actions, known = load_audit_actions()
    delistings = prior_audit.load_delistings()
    missing: set[str] = set()
    audit_row, audit_trades = core.simulate(
        raw_signals, raw_bars, raw_calendar, champion, 0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
        keep_trades=True, actions=actions, known_action_keys=known, coverage_sink=missing, delist_dates=delistings,
    )
    audit_row.update(batch6.active_metrics(audit_row, benchmark))
    audit_trades.to_csv(RESULTS / "audit" / "champion_full_window_trades_raw.csv", index=False, encoding="utf-8-sig")

    raw_start_rows, raw_start_trades = [], []
    for item in starts.itertuples(index=False):
        result, trades = run_window(
            raw_signals, raw_bars, raw_calendar, champion, int(item.year), pd.Timestamp(item.start_date),
            raw=True, actions=actions, known=known, coverage=missing, delistings=delistings, keep_trades=True,
        )
        raw_start_rows.append({
            "candidate": champion, "year": int(item.year), "start_rank": int(item.start_rank), "start_date": item.start_date,
            "return_value": float(result[f"return_{item.year}"]), "completed_trades": int(result["completed_trades"]),
            "open_positions_at_end": int(result["open_positions_at_end"]), "pending_orders_at_end": int(result["pending_orders_at_end"]),
        })
        if not trades.empty:
            trades = trades.copy(); trades.insert(0, "run_start_date", item.start_date); raw_start_trades.append(trades)
    raw_starts = pd.DataFrame(raw_start_rows)
    raw_starts.to_csv(RESULTS / "audit" / "champion_random_start_audit_25.csv", index=False, encoding="utf-8-sig")
    pd.concat(raw_start_trades, ignore_index=True).to_csv(RESULTS / "audit" / "champion_random_start_trades_raw.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(RESULTS / "audit" / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")

    audit_pass = bool(
        not missing and audit_row["open_positions_at_end"] == 0
        and all(int(audit_row[f"trades_{y}"]) >= 20 for y in YEARS)
        and raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()
        and raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE
    )
    audit = {
        "status": "complete" if audit_pass else "audit_failed",
        "champion_frozen_before_audit": champion,
        "audit_did_not_trigger_reselection": True,
        "audited_champion": audit_row,
        "raw_random_start_summary": {
            "run_count": len(raw_starts), "mean_return": float(raw_starts.return_value.mean()),
            "minimum_return": float(raw_starts.return_value.min()),
            "positive_fraction": float((raw_starts.return_value > 0).mean()),
        },
        "missing_corporate_action_keys": sorted(missing),
        "assertions": {
            "maximum_raw_date": str(raw_all.date.max().date()), "maximum_execution_date": str(max(raw_calendar).date()),
            "pre2025_boundary_passed": raw_all.date.max() <= HARD_MAX_DATE and max(raw_calendar) <= HARD_MAX_DATE,
            "corporate_action_coverage_complete": not missing, "full_window_terminal_empty": audit_row["open_positions_at_end"] == 0,
            "random_start_run_count_exact_25": len(raw_starts) == 25,
            "all_random_start_runs_terminal_empty": bool(raw_starts.open_positions_at_end.eq(0).all() and raw_starts.pending_orders_at_end.eq(0).all()),
            "production_change": False,
        },
        "source_hashes": {"protocol": sha256(PROTOCOL), "selection": sha256(RESULTS / "SELECTION.json"), "runner": sha256(Path(__file__))},
    }
    (RESULTS / "audit" / "FINAL_AUDIT.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"champion": champion, "audit_status": audit["status"]}, ensure_ascii=False), flush=True)
    return 0 if audit_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
