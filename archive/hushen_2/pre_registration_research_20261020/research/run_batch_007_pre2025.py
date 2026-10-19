from __future__ import annotations

import hashlib
import json
import math
import sys
import traceback
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_batch as core  # noqa: E402
import audit_champion as prior_audit  # noqa: E402
import audit_batch_003 as batch3_audit  # noqa: E402
import audit_batch_004 as batch4_audit  # noqa: E402
import audit_batch_006 as batch6_audit  # noqa: E402


PROJECT = core.PROJECT
PROTOCOL = PROJECT / "protocol" / "BATCH_007_PRE2025.json"
RESULTS = PROJECT / "results" / "batch_007_pre2025_start_robustness"
OLD_AUDIT = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "audit" / "FINAL_AUDIT.json"
NEW_AUDIT = PROJECT / "results" / "batch_006_pre2025_active_objectives" / "audit" / "FINAL_AUDIT.json"
OLD_SIGNALS = PROJECT / "results" / "batch_004_pre2025_factor_tuning" / "champion_signals_screening.parquet"
NEW_SIGNALS = PROJECT / "results" / "batch_006_pre2025_active_objectives" / "defense_maximin_champion_signals_screening.parquet"
BATCH7_ACTIONS = RESULTS / "audit" / "eastmoney_actions.json"
HARD_MAX_DATE = pd.Timestamp("2024-12-31")
YEARS = list(range(2020, 2025))
SEED = 20261019
STARTS_PER_YEAR = 20
RAW_COLUMNS = ["date", "open", "high", "low", "close", "preclose", "volume", "amount", "tradestatus", "symbol"]
VERSION_SPECS = {
    "OLD": {
        "signals": OLD_SIGNALS,
        "factor": "P4_OUTER_030_030_040",
        "M_internal": [0.25, 0.75, 0.0],
        "T_internal": [0.5, 0.25, 0.25, 0.0],
        "H_internal": [0.25, 0.25, 0.25, 0.25],
        "outer": [0.3, 0.3, 0.4],
    },
    "NEW": {
        "signals": NEW_SIGNALS,
        "factor": "DEF_P4_OUTER_060_000_040",
        "M_internal": [0.5, 0.5, 0.0],
        "T_internal": [0.5, 0.0, 0.5, 0.0],
        "H_internal": [0.25, 0.25, 0.5, 0.0],
        "outer": [0.6, 0.0, 0.4],
    },
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_preregistration_and_frozen_sources() -> dict:
    protocol = json_load(PROTOCOL)
    if protocol["start_sampling"]["random_seed"] != SEED:
        raise RuntimeError("Batch007 random seed differs from preregistration")
    if protocol["run_counts"] != {
        "years": 5, "starts_per_year": 20, "runs_per_version": 100, "versions": 2, "total_runs": 200
    }:
        raise RuntimeError("Batch007 preregistered run counts changed")
    old = json_load(OLD_AUDIT)
    new = json_load(NEW_AUDIT)
    frozen = {
        "OLD": old["champion_spec"],
        "NEW": {
            "M_internal": [0.5, 0.5, 0.0],
            "T_internal": [0.5, 0.0, 0.5, 0.0],
            "H_internal": [0.25, 0.25, 0.5, 0.0],
            "outer": [0.6, 0.0, 0.4],
        },
    }
    defense = new["audited_champions"]["defense_maximin"]
    if defense["factor"] != VERSION_SPECS["NEW"]["factor"]:
        raise RuntimeError("Batch006 defense factor changed")
    for version in VERSION_SPECS:
        for key in ["M_internal", "T_internal", "H_internal", "outer"]:
            if list(map(float, frozen[version][key])) != list(map(float, VERSION_SPECS[version][key])):
                raise RuntimeError(f"{version} frozen {key} differs from Batch007 preregistration")
    old_candidate = old["audited_champion"]
    for candidate in [old_candidate, defense]:
        expected = {
            "entry_offset_atr": 0.0, "take_atr": 4.0, "stop_atr": 1.5,
            "hold_calendar_days": 30,
        }
        for key, value in expected.items():
            if float(candidate[key]) != value:
                raise RuntimeError(f"Frozen execution differs: {key}")
    return protocol


def load_frozen_signals() -> tuple[dict[str, pd.DataFrame], set[str]]:
    frames: dict[str, pd.DataFrame] = {}
    symbols: set[str] = set()
    for version, spec in VERSION_SPECS.items():
        d = pd.read_parquet(spec["signals"])
        d["date"] = pd.to_datetime(d["date"])
        if d.empty or d["date"].max() > pd.Timestamp("2024-11-22"):
            raise RuntimeError(f"{version} signal boundary violation")
        if set(d["factor"].astype(str).unique()) != {spec["factor"]}:
            raise RuntimeError(f"{version} frozen factor mismatch")
        if int(d.groupby("date").size().max()) > 3:
            raise RuntimeError(f"{version} exceeds daily top-3")
        frames[version] = d
        symbols.update(d["symbol"].astype(str))
    return frames, symbols


def subset_hash(frame: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update("|".join(frame.columns).encode("utf-8"))
    h.update("|".join(map(str, frame.dtypes)).encode("utf-8"))
    h.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return h.hexdigest()


def load_raw_pre2025(symbols: set[str]) -> tuple[dict[str, pd.DataFrame], list[pd.Timestamp], pd.DataFrame, pd.DataFrame]:
    rows: list[pd.DataFrame] = []
    manifest: list[dict] = []
    for i, symbol in enumerate(sorted(symbols), 1):
        path = prior_audit.RAW_ROOT / symbol[-2:] / f"{symbol}.parquet"
        if not path.exists():
            raise FileNotFoundError(path)
        d = pd.read_parquet(
            path,
            columns=RAW_COLUMNS,
            filters=[("date", ">=", pd.Timestamp("2020-01-01")), ("date", "<=", HARD_MAX_DATE)],
        )
        d["date"] = pd.to_datetime(d["date"])
        if d.empty or d["date"].max() > HARD_MAX_DATE:
            raise RuntimeError(f"Raw pre-2025 subset invalid for {symbol}")
        for col in ["open", "high", "low", "close", "preclose", "volume", "amount"]:
            d[col] = pd.to_numeric(d[col], errors="coerce")
        d = d.sort_values(["symbol", "date"]).reset_index(drop=True)
        manifest.append({
            "symbol": symbol,
            "relative_path": str(path.relative_to(core.ROOT)),
            "rows_read": int(len(d)),
            "minimum_date_read": str(d["date"].min().date()),
            "maximum_date_read": str(d["date"].max().date()),
            "pre2025_subset_sha256": subset_hash(d),
        })
        rows.append(d)
        if i % 250 == 0:
            print(f"raw pre-2025 inputs {i}/{len(symbols)}", flush=True)
    all_bars = pd.concat(rows, ignore_index=True).sort_values(["symbol", "date"]).reset_index(drop=True)
    if all_bars["date"].max() > HARD_MAX_DATE:
        raise RuntimeError("Raw execution input crossed 2024-12-31")
    by_symbol = {s: d.set_index("date").sort_index() for s, d in all_bars.groupby("symbol", sort=False)}
    calendar = sorted(all_bars["date"].drop_duplicates().tolist())
    return by_symbol, calendar, all_bars, pd.DataFrame(manifest)


def sample_starts(calendar: list[pd.Timestamp]) -> pd.DataFrame:
    rng = np.random.Generator(np.random.PCG64(SEED))
    rows = []
    for year in YEARS:
        candidates = np.array(sorted(d for d in calendar if pd.Timestamp(f"{year}-01-01") <= d <= pd.Timestamp(f"{year}-03-31")), dtype="datetime64[ns]")
        if len(candidates) < STARTS_PER_YEAR:
            raise RuntimeError(f"Insufficient Q1 trading dates for {year}: {len(candidates)}")
        positions = rng.choice(len(candidates), size=STARTS_PER_YEAR, replace=False)
        chosen = sorted(pd.Timestamp(candidates[int(p)]) for p in positions)
        for rank, date in enumerate(chosen, 1):
            rows.append({"year": year, "chronological_rank": rank, "start_date": str(date.date())})
    starts = pd.DataFrame(rows)
    if len(starts) != 100 or starts.groupby("year")["start_date"].nunique().ne(20).any():
        raise RuntimeError("Deterministic start sampling count/uniqueness failure")
    return starts


def merge_raw_signal_close(signals: pd.DataFrame, all_bars: pd.DataFrame) -> pd.DataFrame:
    raw_close = all_bars[["date", "symbol", "close"]].rename(columns={"close": "raw_close"})
    out = signals.drop(columns=["close"]).merge(raw_close, on=["date", "symbol"], how="left", validate="many_to_one")
    if out["raw_close"].isna().any():
        raise RuntimeError("Missing raw signal-date close")
    return out.rename(columns={"raw_close": "close"})


def load_actions_batch007() -> tuple[dict, set[str]]:
    actions, known = batch6_audit.load_actions()
    payload = json_load(BATCH7_ACTIONS)
    if payload.get("cutoff") != "2024-12-31" or set(payload.get("records", {})) != {
        f"{symbol}/{year}" for symbol, year in json_load(RESULTS / "audit" / "action_gaps.json")
    }:
        raise RuntimeError("Batch007 action response scope/cutoff differs from the 35 authorized keys")
    for key, records in payload["records"].items():
        symbol = key.split("/")[0]
        known.add(key)
        for item in records:
            if not item.get("dividOperateDate"):
                continue
            date = pd.Timestamp(item["dividOperateDate"]).normalize()
            if date > HARD_MAX_DATE:
                raise RuntimeError(f"Batch007 action response crossed pre-2025 boundary: {key} {date}")
            actions.setdefault((date, symbol), []).append({
                "cash": prior_audit.number(item.get("dividCashPsBeforeTax", 0)),
                "stock": prior_audit.number(item.get("dividStocksPs", 0)) + prior_audit.number(item.get("dividReserveToStockPs", 0)),
                "taxable_stock": prior_audit.number(item.get("dividStocksPs", 0)),
                "pay": pd.Timestamp(item.get("dividPayDate") or item["dividOperateDate"]).normalize(),
                "release": pd.Timestamp(item.get("dividStockMarketDate") or item["dividOperateDate"]).normalize(),
                "source": item.get("source", "Eastmoney stock_fhps_em via AkShare"),
            })
    return actions, known


def simulate_one(
    signals: pd.DataFrame,
    by_symbol: dict[str, pd.DataFrame],
    calendar: list[pd.Timestamp],
    factor: str,
    year: int,
    start_date: pd.Timestamp,
    actions: dict,
    known_action_keys: set[str],
    delistings: dict[str, pd.Timestamp],
) -> tuple[dict, pd.DataFrame, set[str]]:
    year_end = pd.Timestamp(f"{year}-12-31")
    year_calendar = [d for d in calendar if start_date <= d <= year_end]
    if not year_calendar:
        raise RuntimeError(f"No execution calendar for {year} start {start_date.date()}")
    last_session = max(year_calendar)
    signal_cutoff = year_end - pd.Timedelta(days=37)
    run_signals = signals[signals["date"].between(start_date, signal_cutoff)].copy()
    missing: set[str] = set()
    old_globals = (core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS)
    try:
        core.EVAL_START = start_date
        core.HARD_MAX_DATE = last_session
        core.LAST_SIGNAL_DATE = signal_cutoff
        core.YEARS = [year]
        row, trades = core.simulate(
            run_signals, by_symbol, year_calendar, factor,
            0.0, 30, "take4.00_stop1.50", 4.0, 1.5,
            keep_trades=True, actions=actions, known_action_keys=known_action_keys,
            coverage_sink=missing, delist_dates=delistings,
        )
    finally:
        core.EVAL_START, core.HARD_MAX_DATE, core.LAST_SIGNAL_DATE, core.YEARS = old_globals
    return row, trades, missing


def aggregate(group: pd.DataFrame) -> dict:
    returns = pd.to_numeric(group["return"], errors="coerce").dropna().to_numpy(dtype=float)
    trades = pd.to_numeric(group["completed_trades"], errors="coerce").dropna().to_numpy(dtype=float)
    std = float(np.std(returns, ddof=0)) if len(returns) else math.nan
    variance = float(np.var(returns, ddof=0)) if len(returns) else math.nan
    return {
        "run_count": int(len(group)),
        "valid_return_count": int(len(returns)),
        "mean_return": float(np.mean(returns)) if len(returns) else math.nan,
        "median_return": float(np.median(returns)) if len(returns) else math.nan,
        "std_return_ddof0": std,
        "variance_return_ddof0": variance,
        "std_squared_variance_check": std * std if len(returns) else math.nan,
        "variance_check_abs_difference": abs(variance - std * std) if len(returns) else math.nan,
        "minimum_return": float(np.min(returns)) if len(returns) else math.nan,
        "maximum_return": float(np.max(returns)) if len(returns) else math.nan,
        "positive_return_fraction": float(np.mean(returns > 0.0)) if len(returns) else math.nan,
        "mean_completed_trades": float(np.mean(trades)) if len(trades) else math.nan,
        "median_completed_trades": float(np.median(trades)) if len(trades) else math.nan,
        "failed_run_count": int(group["failed"].astype(bool).sum()),
    }


def main() -> int:
    protocol = validate_preregistration_and_frozen_sources()
    RESULTS.mkdir(parents=True, exist_ok=True)
    signals_by_version, symbols = load_frozen_signals()
    by_symbol, calendar, all_bars, raw_manifest = load_raw_pre2025(symbols)
    if max(calendar) > HARD_MAX_DATE:
        raise RuntimeError("Execution calendar crossed pre-2025 boundary")
    starts = sample_starts(calendar)
    starts.to_csv(RESULTS / "sampled_start_dates.csv", index=False, encoding="utf-8-sig")
    raw_manifest.to_csv(RESULTS / "raw_pre2025_input_manifest.csv", index=False, encoding="utf-8-sig")

    for version in signals_by_version:
        signals_by_version[version] = merge_raw_signal_close(signals_by_version[version], all_bars)
    actions, known_action_keys = load_actions_batch007()
    delistings = prior_audit.load_delistings()

    run_rows: list[dict] = []
    all_trades: list[pd.DataFrame] = []
    all_missing_action_keys: set[str] = set()
    action_sources_total: Counter[str] = Counter()
    for version in ["OLD", "NEW"]:
        spec = VERSION_SPECS[version]
        for item in starts.itertuples(index=False):
            start = pd.Timestamp(item.start_date)
            run_id = f"{version}_{item.year}_{int(item.chronological_rank):02d}_{item.start_date}"
            base = {
                "run_id": run_id,
                "version": version,
                "year": int(item.year),
                "start_rank": int(item.chronological_rank),
                "start_date": item.start_date,
                "signal_cutoff": str((pd.Timestamp(f"{item.year}-12-31") - pd.Timedelta(days=37)).date()),
                "year_last_trading_date": str(max(d for d in calendar if d.year == item.year).date()),
            }
            try:
                row, trades, missing = simulate_one(
                    signals_by_version[version], by_symbol, calendar, str(spec["factor"]),
                    int(item.year), start, actions, known_action_keys, delistings,
                )
                all_missing_action_keys.update(missing)
                residue = int(row["open_positions_at_end"]) + int(row["pending_orders_at_end"])
                reasons = []
                if int(row["open_positions_at_end"]):
                    reasons.append("open_positions_at_end")
                if int(row["pending_orders_at_end"]):
                    reasons.append("pending_orders_at_end")
                if missing:
                    reasons.append("missing_corporate_action_coverage")
                failed = bool(reasons)
                source_counts = {str(k): int(v) for k, v in row["corporate_action_source_counts"].items()}
                action_sources_total.update(source_counts)
                base.update({
                    "return": float(row[f"return_{item.year}"]),
                    "final_equity": float(row["final_equity"]),
                    "completed_trades": int(row["completed_trades"]),
                    "open_positions_at_end": int(row["open_positions_at_end"]),
                    "pending_orders_at_end": int(row["pending_orders_at_end"]),
                    "terminal_residue_count": residue,
                    "expired_entry_orders": int(row["expired_entry_orders"]),
                    "capacity_limited_orders": int(row["capacity_limited_orders"]),
                    "blocked_exit_attempts": int(row["blocked_exit_attempts"]),
                    "blocked_exit_reason_counts": json.dumps(row["blocked_exit_reason_counts"], ensure_ascii=False, sort_keys=True),
                    "corporate_action_events": int(row["corporate_action_events"]),
                    "corporate_action_source_counts": json.dumps(source_counts, ensure_ascii=False, sort_keys=True),
                    "delisting_freezes": int(row["delisting_freezes"]),
                    "unpaid_receivables": float(row["unpaid_receivables"]),
                    "missing_action_key_count": len(missing),
                    "failed": failed,
                    "failure_reasons": ";".join(reasons),
                    "exception": "",
                })
                if not trades.empty:
                    trades = trades.copy()
                    trades.insert(0, "run_id", run_id)
                    trades.insert(1, "version", version)
                    trades.insert(2, "run_start_date", item.start_date)
                    all_trades.append(trades)
            except Exception as exc:  # Preserve every preregistered run as an explicit failure.
                base.update({
                    "return": math.nan, "final_equity": math.nan, "completed_trades": math.nan,
                    "open_positions_at_end": math.nan, "pending_orders_at_end": math.nan,
                    "terminal_residue_count": math.nan, "expired_entry_orders": math.nan,
                    "capacity_limited_orders": math.nan, "blocked_exit_attempts": math.nan,
                    "blocked_exit_reason_counts": "{}", "corporate_action_events": math.nan,
                    "corporate_action_source_counts": "{}", "delisting_freezes": math.nan,
                    "unpaid_receivables": math.nan, "missing_action_key_count": math.nan,
                    "failed": True, "failure_reasons": "execution_exception",
                    "exception": f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}",
                })
            run_rows.append(base)
            if len(run_rows) % 20 == 0:
                print(f"completed {len(run_rows)}/200 runs", flush=True)

    runs = pd.DataFrame(run_rows)
    runs.to_csv(RESULTS / "run_details_200.csv", index=False, encoding="utf-8-sig")
    trades_out = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    trades_out.to_csv(RESULTS / "trades_all_runs.csv", index=False, encoding="utf-8-sig")

    annual_rows = []
    for (version, year), group in runs.groupby(["version", "year"], sort=True):
        annual_rows.append({"version": version, "year": int(year), **aggregate(group)})
    annual = pd.DataFrame(annual_rows)
    annual.to_csv(RESULTS / "annual_version_aggregates.csv", index=False, encoding="utf-8-sig")
    overall = pd.DataFrame([
        {"version": version, "aggregation_scope": "100 independent year/start runs; not CAGR", **aggregate(group)}
        for version, group in runs.groupby("version", sort=True)
    ])
    overall.to_csv(RESULTS / "overall_version_aggregates.csv", index=False, encoding="utf-8-sig")

    source_paths = {
        "BATCH_007_PRE2025.json": PROTOCOL,
        "run_batch_007_pre2025.py": Path(__file__),
        "run_batch.py": HERE / "run_batch.py",
        "audit_champion.py": HERE / "audit_champion.py",
        "audit_batch_003.py": HERE / "audit_batch_003.py",
        "audit_batch_004.py": HERE / "audit_batch_004.py",
        "audit_batch_006.py": HERE / "audit_batch_006.py",
        "fetch_actions_eastmoney.py": HERE / "fetch_actions_eastmoney.py",
        "batch004_FINAL_AUDIT.json": OLD_AUDIT,
        "batch006_FINAL_AUDIT.json": NEW_AUDIT,
        "old_champion_signals.parquet": OLD_SIGNALS,
        "new_defense_signals.parquet": NEW_SIGNALS,
        "actions_base": prior_audit.ACTIONS_BASE,
        "eastmoney_actions_batch002.json": prior_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch003.json": batch3_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch004.json": batch4_audit.EASTMONEY_ACTIONS,
        "eastmoney_actions_batch006.json": batch6_audit.EASTMONEY_ACTIONS,
        "action_gaps_batch007.json": RESULTS / "audit" / "action_gaps.json",
        "eastmoney_actions_batch007.json": BATCH7_ACTIONS,
        "historical_mainboard_universe.csv": prior_audit.METADATA,
    }
    source_hashes = {name: sha256(path) for name, path in source_paths.items() if path.exists()}
    raw_manifest_digest = hashlib.sha256(
        "\n".join(f"{r.symbol}|{r.pre2025_subset_sha256}" for r in raw_manifest.itertuples(index=False)).encode("utf-8")
    ).hexdigest()
    assertions = {
        "instruction_boundary_version": "public-pre2025-v1",
        "post_2024_access": False,
        "maximum_signal_date": str(max(d["date"].max() for d in signals_by_version.values()).date()),
        "maximum_signal_date_at_or_before_2024_11_22": all(d["date"].max() <= pd.Timestamp("2024-11-22") for d in signals_by_version.values()),
        "maximum_raw_date_read": str(all_bars["date"].max().date()),
        "maximum_execution_date": str(max(calendar).date()),
        "maximum_input_and_execution_date_at_or_before_2024_12_31": all_bars["date"].max() <= HARD_MAX_DATE and max(calendar) <= HARD_MAX_DATE,
        "sample_count_exact_100": len(starts) == 100,
        "twenty_unique_starts_each_year": bool(starts.groupby("year")["start_date"].nunique().eq(20).all()),
        "old_new_share_identical_starts": bool(runs.groupby(["year", "start_rank"])["start_date"].nunique().eq(1).all()),
        "run_count_exact_200": len(runs) == 200,
        "run_count_each_version_exact_100": bool(runs.groupby("version").size().eq(100).all()),
        "no_parameter_tuning_or_selection": True,
        "corporate_action_coverage_complete": len(all_missing_action_keys) == 0,
        "all_runs_end_empty": bool(
            pd.to_numeric(runs["open_positions_at_end"], errors="coerce").fillna(1).eq(0).all()
            and pd.to_numeric(runs["pending_orders_at_end"], errors="coerce").fillna(1).eq(0).all()
        ),
        "variance_checks_within_1e_15": bool(
            (annual["variance_check_abs_difference"].fillna(math.inf) <= 1e-15).all()
            and (overall["variance_check_abs_difference"].fillna(math.inf) <= 1e-15).all()
        ),
        "production_change": False,
        "prior_result_change": False,
    }
    coverage = {
        "known_action_stock_years": len(known_action_keys),
        "missing_action_keys": sorted(all_missing_action_keys),
        "corporate_action_source_counts_across_runs": dict(sorted(action_sources_total.items())),
        "runs_with_corporate_actions": int((pd.to_numeric(runs["corporate_action_events"], errors="coerce") > 0).sum()),
        "delisting_freezes_across_runs": int(pd.to_numeric(runs["delisting_freezes"], errors="coerce").fillna(0).sum()),
    }
    (RESULTS / "corporate_action_coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
    if all_missing_action_keys:
        (RESULTS / "action_gaps_requested.json").write_text(
            json.dumps({"requested_stock_year_keys": sorted(all_missing_action_keys)}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    required_assertions = [
        "maximum_signal_date_at_or_before_2024_11_22",
        "maximum_input_and_execution_date_at_or_before_2024_12_31",
        "sample_count_exact_100",
        "twenty_unique_starts_each_year",
        "old_new_share_identical_starts",
        "run_count_exact_200",
        "run_count_each_version_exact_100",
        "corporate_action_coverage_complete",
        "all_runs_end_empty",
        "variance_checks_within_1e_15",
    ]
    if not assertions["corporate_action_coverage_complete"]:
        status = "action_data_required"
    elif all(assertions[k] for k in required_assertions):
        status = "complete"
    else:
        status = "completed_with_failures"
    output = {
        "status": status,
        "protocol_id": protocol["protocol_id"],
        "random_seed": SEED,
        "versions": {k: {x: v for x, v in spec.items() if x != "signals"} for k, spec in VERSION_SPECS.items()},
        "annual_version_aggregates": annual.to_dict("records"),
        "overall_version_aggregates": overall.to_dict("records"),
        "overall_metric_note": "Each overall row aggregates 100 independent year/start returns with unequal holding lengths; it is not CAGR.",
        "failed_runs": runs.loc[runs["failed"], ["run_id", "failure_reasons", "exception"]].to_dict("records"),
        "corporate_action_coverage": coverage,
        "source_hashes": source_hashes,
        "raw_pre2025_subset_manifest_sha256": raw_manifest_digest,
        "assertions": assertions,
        "development_note": "All 2020-2024 runs are development robustness evidence, not blind or holdout evidence. No version was selected from these results.",
    }
    (RESULTS / "FINAL_REPORT.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": output["status"], "assertions": assertions}, ensure_ascii=False, indent=2))
    return 0 if output["status"] == "complete" else (2 if output["status"] == "action_data_required" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
