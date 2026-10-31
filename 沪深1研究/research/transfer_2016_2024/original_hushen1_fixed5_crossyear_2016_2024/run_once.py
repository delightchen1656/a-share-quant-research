from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import math
import os
import sys
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
INPUT = HERE.parent / "inputs_pre2025"
CONFIG_PATH = HERE / "frozen_config.json"
PROTOCOL_PATH = HERE / "PROTOCOL_BEFORE_RUN.md"
EXTENSION_PATH = HERE / "INPUT_EXTENSION_MANIFEST.json"
CORE_PATH = INPUT / "ORIGINAL_HUSHEN1_CORE_APPROVED.py"
CUTOFF = pd.Timestamp("2024-12-31")
EPS = 1e-8


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_json(path: Path, value: Any) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def mainboard(symbol: str) -> bool:
    return (
        symbol.endswith(".SH") and symbol[:3] in ("600", "601", "603", "605")
    ) or (
        symbol.endswith(".SZ") and symbol[:3] in ("000", "001", "002", "003")
    )


def load_approved_functions(instrument_batch: bool = False):
    """Compile only constants plus the two approved pure functions.

    No other reference body, imports, external path, platform API, or network code is
    executed. For the instrumented oracle, append the already-computed
    smooth/eligible locals to the approved function's original return value.
    """
    expected = next(
        x["sha256"]
        for x in json.loads(EXTENSION_PATH.read_text(encoding="utf-8"))["approved_extensions"]
        if Path(x["path"]).name == CORE_PATH.name
    )
    actual = sha256(CORE_PATH)
    if actual != expected:
        raise RuntimeError(f"approved core hash mismatch: {actual}")
    tree = ast.parse(CORE_PATH.read_text(encoding="utf-8"), filename=str(CORE_PATH))
    keep_assignments = {
        "SMOOTH",
        "MIN_SMOOTH",
        "INTERVAL",
        "BUFFER",
        "DRIFT",
        "COUNT",
        "EXPOSURE",
        "SLIP_ONE_SIDE",
        "PARTICIPATION",
        "COMMISSION_RATE",
        "MIN_COMMISSION",
        "MAX_ORDER_SHARES",
        "FIELDS",
    }
    body: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in keep_assignments for t in node.targets
        ):
            body.append(copy.deepcopy(node))
        elif isinstance(node, ast.FunctionDef) and node.name in ("mainboard", "compute_signals"):
            fn = copy.deepcopy(node)
            if instrument_batch and fn.name == "compute_signals":
                new_body: list[ast.stmt] = []
                inserted = False
                for statement in fn.body:
                    if isinstance(statement, ast.Return):
                        new_body.append(
                            ast.Return(
                                value=ast.Tuple(
                                    elts=[
                                        ast.Name(id="ranking", ctx=ast.Load()),
                                        ast.Name(id="info", ctx=ast.Load()),
                                        ast.Name(id="smooth", ctx=ast.Load()),
                                        ast.Name(id="eligible", ctx=ast.Load()),
                                    ],
                                    ctx=ast.Load(),
                                )
                            )
                        )
                        inserted = True
                    else:
                        new_body.append(statement)
                if not inserted:
                    raise RuntimeError("approved compute_signals boundary changed")
                fn.body = new_body
            body.append(fn)
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    namespace: dict[str, Any] = {"np": np, "pd": pd, "math": math}
    exec(compile(module, str(CORE_PATH), "exec"), namespace)
    return namespace["compute_signals"], namespace["mainboard"]


class MembershipMap:
    def __init__(self, symbols: list[str], ipo: dict[str, pd.Timestamp], out: dict[str, pd.Timestamp]):
        self.symbols = symbols
        self.ipo = ipo
        self.out = out

    def __getitem__(self, key: str) -> set[str]:
        d = pd.Timestamp(key)
        return {
            s
            for s in self.symbols
            if self.ipo[s] <= d and (s not in self.out or d < self.out[s])
        }


def production_signal_batch(
    raw: dict[str, pd.DataFrame], members: MembershipMap, dates: pd.DatetimeIndex
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Independent batch lift of the approved D11 pure signal function."""
    dates = pd.DatetimeIndex(dates)
    symbols = sorted(raw)
    # Mathematical equivalent of assigning each existing DataFrame column in
    # the approved function, but collect columns first to avoid thousands of
    # object-downcast warnings and repeated block-manager work.
    matrix_columns: dict[str, dict[str, pd.Series]] = {
        k: {} for k in ("cap", "vol", "overnight", "intraday")
    }
    eligible_columns: dict[str, pd.Series] = {}
    fields = ["open", "close", "prev_close", "volume", "turnover", "turnover_rate", "is_paused", "is_st"]
    for s in symbols:
        x = raw[s].copy()
        x.index = pd.DatetimeIndex(x.index).normalize()
        x = x.loc[~x.index.duplicated(keep="last")].sort_index()
        x = x.loc[(x.index <= dates[-1]) & (x["close"] > 0)]
        if x.empty:
            continue
        x = x[fields].astype(float)
        r = (x.close / x.prev_close - 1).where((x.is_paused == 0) & (x.prev_close > 0), 0)
        vol = r.rolling(60).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            overnight = np.log(x.open / x.prev_close).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
            intraday = np.log(x.close / x.open).replace([np.inf, -np.inf], np.nan).fillna(0).rolling(20).sum()
        amount = x.turnover.rolling(20).mean()
        cap = x.close * x.volume / (x.turnover_rate / 100).replace(0, np.nan)
        age = pd.Series(np.arange(len(x)) + 1, index=x.index)
        ok = (
            (age >= 252)
            & (amount >= 1e7)
            & (x.close >= 2)
            & (x.is_st == 0)
            & (x.is_paused == 0)
            & (vol > 0.001)
            & (vol < 0.09)
        )
        for name, values in (("cap", cap), ("vol", vol), ("overnight", overnight), ("intraday", intraday)):
            matrix_columns[name][s] = values.astype(np.float32).reindex(dates)
        eligible_columns[s] = ok.reindex(dates).fillna(False).astype(bool)
    matrices = {
        name: pd.DataFrame(columns, index=dates, columns=symbols, dtype=float)
        for name, columns in matrix_columns.items()
    }
    eligible = pd.DataFrame(eligible_columns, index=dates, columns=symbols, dtype=bool)
    for d in dates:
        allowed = members[d.strftime("%Y-%m-%d")]
        eligible.loc[d] &= pd.Series([s in allowed for s in symbols], index=symbols)
    ranked = {
        k: v.where(eligible).rank(axis=1, pct=True, method="average").astype(np.float32)
        for k, v in matrices.items()
    }
    score = -0.35 * ranked["cap"] - 0.20 * ranked["vol"] + 0.25 * ranked["overnight"] - 0.20 * ranked["intraday"]
    smooth = score.rolling(5, min_periods=3).mean().astype(np.float32)
    return smooth, eligible


def parse_universe(symbols: list[str]) -> tuple[dict[str, pd.Timestamp], dict[str, pd.Timestamp], dict[str, Any]]:
    all_universe = pd.read_csv(INPUT / "universe.csv", dtype=str)
    all_ipo = pd.to_datetime(all_universe["ipoDate"], errors="coerce")
    all_future_ipo = int((all_ipo > CUTOFF).sum())
    universe = all_universe.loc[all_universe["symbol"].isin(symbols)].copy()
    universe["ipo"] = pd.to_datetime(universe["ipoDate"], errors="coerce")
    universe["out"] = pd.to_datetime(universe["outDate"], errors="coerce")
    future_ipo = int((universe["ipo"] > CUTOFF).sum())
    missing_ipo = int(universe["ipo"].isna().sum())
    if missing_ipo:
        raise RuntimeError(f"missing IPO dates for raw symbols: {missing_ipo}")
    # Out dates beyond the public boundary cannot affect membership before cutoff.
    future_out = int((universe["out"] > CUTOFF).sum())
    universe.loc[universe["out"] > CUTOFF, "out"] = pd.NaT
    ipo = dict(zip(universe["symbol"], universe["ipo"]))
    out = {r.symbol: r.out for r in universe.itertuples() if pd.notna(r.out)}
    missing_symbols = sorted(set(symbols) - set(ipo))
    if missing_symbols:
        raise RuntimeError(f"raw symbols absent from universe: {missing_symbols[:5]}")
    return ipo, out, {
        "raw_symbols": len(symbols),
        "all_universe_future_ipo_rows_quarantined_before_join": all_future_ipo,
        "future_ipo_rows_quarantined": future_ipo,
        "future_out_dates_coerced_unavailable": future_out,
        "missing_ipo_for_raw_symbols": missing_ipo,
    }


def manifest_records() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest_path = INPUT / "PUBLIC_INPUT_MANIFEST.json"
    extension = json.loads(EXTENSION_PATH.read_text(encoding="utf-8"))
    if sha256(manifest_path) != extension["base_manifest"]["sha256"]:
        raise RuntimeError("public input manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = [r for r in manifest["files"] if int(r.get("rows", 0)) > 0 and mainboard(r["symbol"])]
    records.sort(key=lambda r: r["symbol"])
    return manifest, records


def raw_path(symbol: str) -> Path:
    return INPUT / "raw" / symbol[-2:] / f"{symbol}.parquet"


def load_raw_for_signals(verify_hashes: bool = True) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    manifest, records = manifest_records()
    raw: dict[str, pd.DataFrame] = {}
    audit_rows: list[dict[str, Any]] = []
    started = time.monotonic()
    for n, record in enumerate(records, 1):
        symbol = record["symbol"]
        path = raw_path(symbol)
        actual_hash = sha256(path) if verify_hashes else "not_recomputed"
        if verify_hashes and actual_hash != record["sha256"]:
            raise RuntimeError(f"raw hash mismatch {symbol}")
        x = pd.read_parquet(path)
        required = {"date", "open", "close", "preclose", "volume", "amount", "turn", "tradestatus", "isST"}
        if not required.issubset(x.columns):
            raise RuntimeError(f"missing raw fields {symbol}: {sorted(required-set(x.columns))}")
        x["date"] = pd.to_datetime(x["date"])
        if x["date"].max() > CUTOFF:
            raise RuntimeError(f"post-boundary raw row {symbol}")
        x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        y = pd.DataFrame(index=x.index)
        y["open"] = pd.to_numeric(x["open"], errors="raise")
        y["close"] = pd.to_numeric(x["close"], errors="raise")
        y["prev_close"] = pd.to_numeric(x["preclose"], errors="raise")
        y["volume"] = pd.to_numeric(x["volume"], errors="raise")
        y["turnover"] = pd.to_numeric(x["amount"], errors="raise")
        y["turnover_rate"] = pd.to_numeric(x["turn"], errors="raise")
        y["is_paused"] = (pd.to_numeric(x["tradestatus"], errors="raise") != 1).astype(float)
        y["is_st"] = pd.to_numeric(x["isST"], errors="raise").astype(float)
        raw[symbol] = y
        audit_rows.append(
            {
                "symbol": symbol,
                "relative_path": f"raw/{symbol[-2:]}/{symbol}.parquet",
                "expected_sha256": record["sha256"],
                "actual_sha256": actual_hash,
                "match": actual_hash == record["sha256"] if verify_hashes else None,
                "rows": len(x),
                "start": str(x.index.min().date()),
                "end": str(x.index.max().date()),
            }
        )
        if n % 250 == 0 or n == len(records):
            print(f"INPUT_SIGNAL_LOAD {n}/{len(records)} elapsed={time.monotonic()-started:.1f}s", flush=True)
    atomic_csv(HERE / "RAW_INPUT_HASH_VERIFICATION.csv", pd.DataFrame(audit_rows))
    return raw, {
        "manifest_status": manifest.get("status"),
        "manifest_cutoff": manifest.get("cutoff"),
        "manifest_records_with_rows": len(records),
        "all_raw_hashes_verified": bool(verify_hashes),
    }


def trading_calendar() -> pd.DatetimeIndex:
    calendar = pd.read_csv(INPUT / "calendar.csv")
    dates = pd.DatetimeIndex(pd.to_datetime(calendar.loc[calendar["is_trading_day"].eq(1), "calendar_date"])).normalize()
    if dates.max() > CUTOFF:
        raise RuntimeError("post-boundary calendar date")
    return dates


def signal_date_window(calendar: pd.DatetimeIndex, cfg: dict[str, Any]) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    sessions = calendar[(calendar >= pd.Timestamp(cfg["research_start"])) & (calendar <= pd.Timestamp(cfg["research_end"]))]
    if sessions.empty:
        raise RuntimeError("empty research sessions")
    first_pos = calendar.get_loc(sessions[0])
    if first_pos < 5:
        raise RuntimeError("insufficient signal smoothing history")
    previous = pd.DatetimeIndex([calendar[calendar.get_loc(d) - 1] for d in sessions])
    start_pos = calendar.get_loc(previous[0]) - 4
    dates = calendar[start_pos : calendar.get_loc(previous[-1]) + 1]
    return dates, previous


def rankings_from_batch(
    smooth: pd.DataFrame, eligible: pd.DataFrame, signal_dates: pd.DatetimeIndex
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for n, d in enumerate(signal_dates, 1):
        last = smooth.loc[d].where(eligible.loc[d]).dropna()
        ordered = last.sort_values(ascending=False, kind="mergesort").iloc[:100]
        if ordered.empty:
            raise RuntimeError(f"no eligible ranking {d.date()}")
        for rank, (symbol, score) in enumerate(ordered.items(), 1):
            rows.append({"signal_date": d, "selection_rank": rank, "symbol": symbol, "score": float(score)})
        if n % 250 == 0 or n == len(signal_dates):
            print(f"RANK_CACHE {n}/{len(signal_dates)}", flush=True)
    return pd.DataFrame(rows)


def compare_preregistered_real_endpoints(
    production_smooth: pd.DataFrame,
    production_eligible: pd.DataFrame,
    raw: dict[str, pd.DataFrame],
    members: MembershipMap,
    batch_dates: pd.DatetimeIndex,
    signal_dates: pd.DatetimeIndex,
) -> dict[str, Any]:
    """Check the pre-registered first, median, and last real signal dates.

    The approved function is an AST-isolated same-source oracle.  This is an
    endpoint implementation check, not a claim of an independent full-date
    recomputation.
    """
    approved_batch, approved_mainboard = load_approved_functions(instrument_batch=True)
    symbols = sorted(raw)
    mainboard_equal = not any(mainboard(s) != bool(approved_mainboard(s)) for s in symbols)
    if not mainboard_equal:
        raise AssertionError("mainboard function mismatch")
    endpoint_positions = sorted({0, len(signal_dates) // 2, len(signal_dates) - 1})
    endpoints = [pd.Timestamp(signal_dates[i]) for i in endpoint_positions]
    checks: list[dict[str, Any]] = []
    all_passed = True
    for endpoint in endpoints:
        batch_pos = int(batch_dates.get_loc(endpoint))
        if batch_pos < 4:
            raise AssertionError(f"insufficient endpoint smoothing window: {endpoint.date()}")
        window = batch_dates[batch_pos - 4 : batch_pos + 1]
        # The approved implementation assigns thousands of DataFrame columns
        # one at a time.  Suppressing its pandas engineering warnings does not
        # change calculation order, dtype, or values.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)
            reference_ranking, _reference_info, reference_smooth, reference_eligible = approved_batch(
                raw, members, window
            )
        label_equal = bool(
            reference_smooth.columns.equals(production_smooth.columns)
            and reference_eligible.columns.equals(production_eligible.columns)
        )
        production_score = production_smooth.loc[endpoint].to_numpy(dtype=np.float32)
        reference_score = reference_smooth.iloc[-1].to_numpy(dtype=np.float32)
        production_ok = production_eligible.loc[endpoint].to_numpy(dtype=bool)
        reference_ok = reference_eligible.iloc[-1].to_numpy(dtype=bool)
        nan_pattern_equal = bool(np.array_equal(np.isnan(production_score), np.isnan(reference_score)))
        non_nan = ~np.isnan(production_score) & ~np.isnan(reference_score)
        score_exact = nan_pattern_equal and bool(
            np.array_equal(production_score[non_nan], reference_score[non_nan])
        )
        finite = np.isfinite(production_score) & np.isfinite(reference_score)
        max_abs = (
            float(np.max(np.abs(production_score[finite] - reference_score[finite])))
            if finite.any()
            else 0.0
        )
        eligible_exact = bool(np.array_equal(production_ok, reference_ok))
        production_ranking = (
            production_smooth.loc[endpoint]
            .where(production_eligible.loc[endpoint])
            .dropna()
            .sort_values(ascending=False, kind="mergesort")
            .index.tolist()[:100]
        )
        ranking_exact = production_ranking == reference_ranking
        passed = label_equal and score_exact and eligible_exact and ranking_exact
        all_passed = all_passed and passed
        checks.append(
            {
                "signal_date": str(endpoint.date()),
                "window_start": str(window[0].date()),
                "window_end": str(window[-1].date()),
                "column_labels_exact": label_equal,
                "smooth_nan_pattern_exact": nan_pattern_equal,
                "smooth_float32_exact": score_exact,
                "smooth_max_abs_difference": max_abs,
                "eligible_exact": eligible_exact,
                "eligible_count": int(production_ok.sum()),
                "top100_and_tie_order_exact": ranking_exact,
                "top100_count": len(production_ranking),
                "passed": passed,
            }
        )
    return {
        "method": (
            "Pre-registered first/median/last real signal-date endpoint comparison against the "
            "AST-isolated approved compute_signals function"
        ),
        "endpoint_rule_registered_before_results": "first, floor(N/2), last required signal date",
        "reference_limit": (
            "The oracle is extracted from the approved same-source function; this is not an "
            "independent full-date cross-validation"
        ),
        "full_date_independent_double_computation_performed": False,
        "full_cache_signal_dates": int(len(signal_dates)),
        "real_endpoint_dates_checked": len(checks),
        "mainboard_function_exact_on_raw_symbols": mainboard_equal,
        "checks": checks,
        "passed": bool(all_passed),
    }


def prepare_signals() -> None:
    if (HERE / "FROZEN_BEFORE_EVALUATION.json").exists() or (HERE / "RUN_STARTED.json").exists():
        raise RuntimeError("cannot prepare or change signal cache after evaluation freeze/start")
    cfg = load_config()
    extension = json.loads(EXTENSION_PATH.read_text(encoding="utf-8"))
    for item in extension["approved_extensions"]:
        path = (HERE / item["path"]).resolve()
        if INPUT.resolve() not in path.parents:
            raise RuntimeError(f"extension escapes whitelist: {path}")
        if sha256(path) != item["sha256"]:
            raise RuntimeError(f"extension hash mismatch: {path.name}")
    manifest, records = manifest_records()
    symbols = [r["symbol"] for r in records]
    ipo, out, universe_audit = parse_universe(symbols)
    calendar = trading_calendar()
    dates, signal_dates = signal_date_window(calendar, cfg)
    raw, raw_audit = load_raw_for_signals(verify_hashes=True)
    members = MembershipMap(symbols, ipo, out)
    print(f"SIGNAL_PRODUCTION begin dates={len(dates)} symbols={len(symbols)}", flush=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        production_smooth, production_eligible = production_signal_batch(raw, members, dates)
    print("SIGNAL_REFERENCE_ENDPOINTS begin", flush=True)
    equivalence = compare_preregistered_real_endpoints(
        production_smooth,
        production_eligible,
        raw,
        members,
        dates,
        signal_dates,
    )
    atomic_json(HERE / "SIGNAL_EQUIVALENCE.json", equivalence)
    if not equivalence["passed"]:
        raise AssertionError(f"signal equivalence failed: {equivalence}")
    rankings = rankings_from_batch(production_smooth, production_eligible, signal_dates)
    atomic_parquet(HERE / "signal_rankings.parquet", rankings)
    diag = (
        rankings.groupby("signal_date", as_index=False)
        .agg(eligible_top_count=("symbol", "size"), top_score=("score", "max"), rank100_score=("score", "min"))
    )
    atomic_csv(HERE / "signal_cache_diagnostics.csv", diag)
    index = pd.read_parquet(INPUT / "sse_price_index.parquet")
    index["date"] = pd.to_datetime(index["date"])
    if index["date"].max() > CUTOFF:
        raise RuntimeError("post-boundary benchmark row")
    audit = {
        "instruction_boundary_version": cfg["instruction_boundary_version"],
        "input_root": str(INPUT),
        "base_manifest_sha256": sha256(INPUT / "PUBLIC_INPUT_MANIFEST.json"),
        "manifest_declared_cutoff": manifest.get("cutoff"),
        "raw": raw_audit,
        "universe": universe_audit,
        "calendar_start": str(calendar.min().date()),
        "calendar_end": str(calendar.max().date()),
        "benchmark_start": str(index["date"].min().date()),
        "benchmark_end": str(index["date"].max().date()),
        "signal_batch_start": str(dates.min().date()),
        "signal_batch_end": str(dates.max().date()),
        "execution_signal_dates": len(signal_dates),
        "ranking_rows": len(rankings),
        "reference_hashes": {Path(x["path"]).name: x["sha256"] for x in extension["approved_extensions"]},
        "no_performance_computed": True,
    }
    atomic_json(HERE / "INPUT_AUDIT_BEFORE_PERFORMANCE.json", audit)
    cache_manifest = {
        "signal_rankings_sha256": sha256(HERE / "signal_rankings.parquet"),
        "signal_diagnostics_sha256": sha256(HERE / "signal_cache_diagnostics.csv"),
        "signal_equivalence_sha256": sha256(HERE / "SIGNAL_EQUIVALENCE.json"),
        "rows": len(rankings),
        "signal_dates": int(rankings["signal_date"].nunique()),
    }
    atomic_json(HERE / "SIGNAL_CACHE_MANIFEST.json", cache_manifest)
    print("SIGNAL_PREPARATION_COMPLETE", flush=True)


@dataclass(frozen=True)
class Action:
    cash: float
    stock: float
    taxable_stock: float
    pay: pd.Timestamp
    release: pd.Timestamp
    pay_fallback: bool
    release_fallback: bool


def _num(value: Any) -> float:
    return float(value) if str(value).strip() else 0.0


def load_actions(symbol_to_col: dict[str, int]) -> tuple[dict[tuple[int, pd.Timestamp], Action], dict[str, Any]]:
    path = INPUT / "actions_pre2025_repaired_20261024.json"
    expected = next(
        x["sha256"]
        for x in json.loads(EXTENSION_PATH.read_text(encoding="utf-8"))["approved_extensions"]
        if Path(x["path"]).name == path.name
    )
    if sha256(path) != expected:
        raise RuntimeError("repaired action snapshot hash mismatch")
    source = json.loads(path.read_text(encoding="utf-8"))
    result: dict[tuple[int, pd.Timestamp], Action] = {}
    missing_pay = 0
    missing_release = 0
    skipped_after_cutoff = 0
    for key in sorted(source):
        symbol = key.split("/", 1)[0]
        if symbol not in symbol_to_col:
            continue
        for record in source[key]:
            operate_raw = str(record.get("dividOperateDate", "")).strip()
            if not operate_raw:
                continue
            operate = pd.Timestamp(operate_raw).normalize()
            if operate > CUTOFF:
                skipped_after_cutoff += 1
                continue
            pay_raw = str(record.get("dividPayDate", "")).strip()
            release_raw = str(record.get("dividStockMarketDate", "")).strip()
            pay_fallback = not pay_raw
            release_fallback = not release_raw
            pay = pd.Timestamp(pay_raw).normalize() if pay_raw else operate
            release = pd.Timestamp(release_raw).normalize() if release_raw else operate
            if pay > CUTOFF or release > CUTOFF:
                raise RuntimeError(f"post-boundary action settlement metadata {symbol}/{operate.date()}")
            missing_pay += int(pay_fallback)
            missing_release += int(release_fallback)
            action = Action(
                cash=_num(record.get("dividCashPsBeforeTax", "")),
                stock=_num(record.get("dividStocksPs", "")) + _num(record.get("dividReserveToStockPs", "")),
                taxable_stock=_num(record.get("dividStocksPs", "")),
                pay=pay,
                release=release,
                pay_fallback=pay_fallback,
                release_fallback=release_fallback,
            )
            event_key = (symbol_to_col[symbol], operate)
            if event_key in result:
                raise RuntimeError(f"duplicate repaired action {symbol}/{operate.date()}")
            result[event_key] = action
    return result, {
        "events": len(result),
        "missing_pay_date_fallbacks": missing_pay,
        "missing_stock_market_date_fallbacks": missing_release,
        "post_cutoff_events_skipped": skipped_after_cutoff,
    }


class ExecutionMarket:
    FIELDS = ("open", "high", "low", "close", "preclose", "volume", "volume20", "prev_actual", "adjust_ratio")

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.calendar = trading_calendar()
        self.sessions = self.calendar[
            (self.calendar >= pd.Timestamp(cfg["research_start"]))
            & (self.calendar <= pd.Timestamp(cfg["research_end"]))
        ]
        first_pos = self.calendar.get_loc(self.sessions[0])
        self.dates = self.calendar[first_pos - 1 : self.calendar.get_loc(self.sessions[-1]) + 1]
        self.date_to_row = {d: i for i, d in enumerate(self.dates)}
        self.global_position = {d: i for i, d in enumerate(self.calendar)}
        anchor = pd.Timestamp(cfg["rebalance_anchor"])
        if anchor not in self.global_position:
            raise RuntimeError("rebalance anchor is not a trading day")
        self.anchor_position = self.global_position[anchor]
        _, records = manifest_records()
        self.symbols = [x["symbol"] for x in records]
        self.symbol_to_col = {s: i for i, s in enumerate(self.symbols)}
        self.ipo, self.out, self.universe_audit = parse_universe(self.symbols)
        shape = (len(self.dates), len(self.symbols))
        self.data = {k: np.full(shape, np.nan, dtype=np.float64) for k in self.FIELDS}
        self.present = np.zeros(shape, dtype=bool)
        self.status = np.full(shape, -1, dtype=np.int8)
        self.st = np.full(shape, -1, dtype=np.int8)
        started = time.monotonic()
        for n, record in enumerate(records, 1):
            symbol = record["symbol"]
            col = self.symbol_to_col[symbol]
            x = pd.read_parquet(raw_path(symbol))
            x["date"] = pd.to_datetime(x["date"])
            if x["date"].max() > CUTOFF:
                raise RuntimeError(f"post-boundary execution row {symbol}")
            x = x.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
            numeric = x[["open", "high", "low", "close", "preclose", "volume", "tradestatus", "isST"]].apply(
                pd.to_numeric, errors="raise"
            )
            numeric["volume20"] = numeric["volume"].rolling(20).mean()
            numeric["prev_actual"] = numeric["close"].shift()
            numeric["adjust_ratio"] = numeric["preclose"] / numeric["prev_actual"]
            loc = self.dates.get_indexer(numeric.index)
            keep = loc >= 0
            loc = loc[keep]
            values = numeric.iloc[np.flatnonzero(keep)]
            if len(loc):
                for field in self.FIELDS:
                    self.data[field][loc, col] = values[field].to_numpy(dtype=float)
                self.status[loc, col] = values["tradestatus"].to_numpy(dtype=np.int8)
                self.st[loc, col] = values["isST"].to_numpy(dtype=np.int8)
                self.present[loc, col] = True
            if n % 250 == 0 or n == len(records):
                print(f"EXECUTION_MARKET_LOAD {n}/{len(records)} elapsed={time.monotonic()-started:.1f}s", flush=True)
        self.actions, self.action_audit = load_actions(self.symbol_to_col)
        self.out_by_col = {self.symbol_to_col[s]: d for s, d in self.out.items() if s in self.symbol_to_col}
        index = pd.read_parquet(INPUT / "sse_price_index.parquet")
        index["date"] = pd.to_datetime(index["date"]).dt.normalize()
        index = index.set_index("date").sort_index()
        index = index.reindex(self.sessions)
        if index[["open", "close"]].isna().any().any():
            raise RuntimeError("benchmark missing research sessions")
        self.benchmark_open = pd.to_numeric(index["open"], errors="raise").to_numpy(dtype=float)
        self.benchmark_close = pd.to_numeric(index["close"], errors="raise").to_numpy(dtype=float)
        ranks = pd.read_parquet(HERE / "signal_rankings.parquet")
        ranks["signal_date"] = pd.to_datetime(ranks["signal_date"]).dt.normalize()
        self.rankings: dict[pd.Timestamp, list[int]] = {}
        for d, group in ranks.sort_values(["signal_date", "selection_rank"]).groupby("signal_date", sort=True):
            self.rankings[pd.Timestamp(d)] = [self.symbol_to_col[s] for s in group["symbol"]]
        required_previous = {self.previous_date(d) for d in self.sessions}
        missing = sorted(required_previous - set(self.rankings))
        if missing:
            raise RuntimeError(f"missing cached rankings: {missing[:5]}")

    def previous_date(self, date: pd.Timestamp) -> pd.Timestamp:
        pos = self.global_position[pd.Timestamp(date)]
        return self.calendar[pos - 1]

    def phase_due(self, date: pd.Timestamp) -> bool:
        i = self.global_position[pd.Timestamp(date)] - self.anchor_position
        return (i - 1) % int(self.cfg["rebalance_interval_trading_days"]) == 0

    def row(self, date: pd.Timestamp) -> int:
        return self.date_to_row[pd.Timestamp(date)]

    def limit_prices(self, row: int, col: int) -> tuple[float, float]:
        preclose = self.data["preclose"][row, col]
        pct = self.cfg["st_daily_limit"] if self.st[row, col] == 1 else self.cfg["normal_daily_limit"]
        high = math.floor(preclose * (1 + pct) * 100 + 0.5) / 100
        low = math.floor(preclose * (1 - pct) * 100 + 0.5) / 100
        return high, low

    def valid_bar(self, row: int, col: int) -> bool:
        if not self.present[row, col] or self.status[row, col] != 1:
            return False
        op = self.data["open"][row, col]
        preclose = self.data["preclose"][row, col]
        if not np.isfinite(op) or op <= 0 or not np.isfinite(preclose) or preclose <= 0:
            return False
        high, low = self.limit_prices(row, col)
        return np.isfinite(high) and np.isfinite(low) and 0 < low <= op <= high


class Account:
    def __init__(self, market: ExecutionMarket, start: pd.Timestamp, end: pd.Timestamp, commission_multiplier: int = 1):
        self.market = market
        self.cfg = market.cfg
        self.start = pd.Timestamp(start)
        self.end = pd.Timestamp(end)
        self.commission_multiplier = int(commission_multiplier)
        self.initial = float(self.cfg["initial_cash_cny"])
        self.cash = self.initial
        self.holdings: dict[int, dict[str, Any]] = {}
        self.receivables: list[tuple[pd.Timestamp, float, int]] = []
        self.targets: dict[int, int] = {}
        self.close_shares: dict[int, int] = {}
        self.first = True
        self.daily: list[dict[str, Any]] = []
        self.trades: list[dict[str, Any]] = []
        self.orders: list[dict[str, Any]] = []
        self.action_log: list[dict[str, Any]] = []
        self.rebalances: list[dict[str, Any]] = []
        self.issues: dict[str, Any] = {}
        self.reference_diffs: dict[str, Any] = {}
        self.capacity_hits = 0
        self.fees = 0.0
        self.dividend_tax = 0.0
        self.special_limit_observations: set[tuple[int, pd.Timestamp]] = set()

    def available(self, col: int, date: pd.Timestamp) -> int:
        return int(sum(lot["q"] for lot in self.holdings[col]["lots"] if lot["release"] <= date and lot["buy"] < date))

    def _commission(self, value: float) -> float:
        rate = float(self.cfg["commission_rate"]) * self.commission_multiplier
        minimum = float(self.cfg["minimum_commission_cny"]) * self.commission_multiplier
        return round(max(minimum, value * rate), 2)

    def _buy_cost(self, quantity: int, op: float) -> float:
        value = quantity * (op * (1 + float(self.cfg["slippage_one_side"])) + 0.01)
        rate = float(self.cfg["commission_rate"]) * self.commission_multiplier
        minimum = float(self.cfg["minimum_commission_cny"]) * self.commission_multiplier
        return value + max(minimum, value * rate) + value * float(self.cfg["transfer_rate_before_2022_04_29"])

    def _corporate(self, date: pd.Timestamp, row: int) -> None:
        pending: list[tuple[pd.Timestamp, float, int]] = []
        for pay, amount, col in self.receivables:
            if pay <= date:
                self.cash += amount
                self.action_log.append(
                    {"start": self.start, "date": date, "symbol": self.market.symbols[col], "event": "cash_payment", "amount": amount}
                )
            else:
                pending.append((pay, amount, col))
        self.receivables = pending
        for col, position in list(self.holdings.items()):
            action = self.market.actions.get((col, date))
            if action is not None:
                old = int(position["qty"])
                amount = old * action.cash
                if action.pay <= date:
                    self.cash += amount
                    paid = True
                else:
                    self.receivables.append((action.pay, amount, col))
                    paid = False
                additions: list[dict[str, Any]] = []
                remaining = int(math.floor(old * action.stock + EPS))
                original_lots = list(position["lots"])
                for j, lot in enumerate(original_lots):
                    bonus = min(remaining, int(math.floor(lot["q"] * action.stock + EPS)))
                    if j == len(original_lots) - 1:
                        bonus = remaining
                    remaining -= bonus
                    taxable = action.cash + action.taxable_stock if date <= lot["buy"] + pd.DateOffset(years=1) else 0.0
                    liability = lot["div"] + taxable
                    adjusted = liability * lot["q"] / (lot["q"] + bonus) if lot["q"] + bonus else 0.0
                    lot["div"] = adjusted
                    if bonus:
                        additions.append({"q": bonus, "buy": lot["buy"], "release": action.release, "div": adjusted})
                position["lots"].extend(additions)
                position["lots"].sort(key=lambda lot: (lot["buy"], lot["release"]))
                position["qty"] = int(sum(lot["q"] for lot in position["lots"]))
                if self.market.present[row, col]:
                    position["last"] = float(self.market.data["preclose"][row, col])
                self.action_log.append(
                    {
                        "start": self.start,
                        "date": date,
                        "symbol": self.market.symbols[col],
                        "event": "ex_date",
                        "old_shares": old,
                        "new_shares": position["qty"],
                        "cash_per_share": action.cash,
                        "cash_amount": amount,
                        "paid_immediately": paid,
                        "pay_date": action.pay,
                        "stock_ratio": action.stock,
                        "taxable_stock_ratio": action.taxable_stock,
                        "release_date": action.release,
                        "pay_date_fallback": action.pay_fallback,
                        "release_date_fallback": action.release_fallback,
                    }
                )
                prev_actual = self.market.data["prev_actual"][row, col]
                preclose = self.market.data["preclose"][row, col]
                reference = (prev_actual - action.cash) / (1 + action.stock) if 1 + action.stock else np.nan
                if np.isfinite(prev_actual) and np.isfinite(preclose) and abs(preclose - reference) > max(0.025, preclose * 0.0001):
                    self.reference_diffs[f"{self.market.symbols[col]}/{date.date()}"] = {
                        "previous_actual_close": prev_actual,
                        "preclose": preclose,
                        "action_reference": reference,
                    }
            adjust_ratio = self.market.data["adjust_ratio"][row, col]
            if action is None and np.isfinite(adjust_ratio) and abs(adjust_ratio - 1) > 1e-5:
                self.issues[f"{self.market.symbols[col]}/{date.date()}"] = {"unexplained_adjust_ratio": float(adjust_ratio)}
            out = self.market.out_by_col.get(col)
            if out is not None and date >= out:
                self.issues[f"{self.market.symbols[col]}/{date.date()}"] = "delisting zero-recovery assumption"
                del self.holdings[col]

    def _open_nav(self, row: int) -> float:
        value = self.cash + sum(amount for _, amount, _ in self.receivables)
        for col, position in self.holdings.items():
            if self.market.valid_bar(row, col):
                price = float(self.market.data["open"][row, col])
            else:
                price = float(position["last"])
            value += position["qty"] * price
        return value

    def _limit_price(self, row: int, col: int, buy: bool) -> float:
        op = float(self.market.data["open"][row, col])
        high, low = self.market.limit_prices(row, col)
        slip = float(self.cfg["slippage_one_side"])
        if buy:
            value = min(high, op * (1 + slip))
            return min(high, math.ceil(value * 100 - EPS) / 100)
        value = max(low, op * (1 - slip))
        return max(low, math.floor(value * 100 + EPS) / 100)

    def _order(self, date: pd.Timestamp, row: int, col: int, quantity: int, limit: float) -> bool:
        symbol = self.market.symbols[col]
        base = {"start": self.start, "end": self.end, "date": date, "symbol": symbol, "quantity": quantity, "limit": limit}

        def reject(reason: str) -> bool:
            self.orders.append({**base, "status": reason, "price": np.nan})
            return False

        if not self.market.present[row, col] or self.market.status[row, col] != 1 or self.market.data["volume"][row, col] <= 0:
            return reject("not_tradable")
        high_limit, low_limit = self.market.limit_prices(row, col)
        op = float(self.market.data["open"][row, col])
        high = float(self.market.data["high"][row, col])
        low = float(self.market.data["low"][row, col])
        cap = int(self.market.data["volume"][row, col] * float(self.cfg["daily_fill_capacity"]) / 100) * 100
        if abs(quantity) > cap:
            self.capacity_hits += 1
            return reject("daily_capacity")
        if quantity > 0:
            if op >= high_limit - 0.000001 or limit < op - EPS:
                return reject("buy_limit_not_marketable_at_open")
            proposed = min(limit, op * 1.001, high, high_limit)
            if proposed < max(low, low_limit) - EPS:
                return reject("invalid_open_fill")
        else:
            if op <= low_limit + 0.000001 or limit > op + EPS:
                return reject("sell_limit_not_marketable_at_open")
            proposed = max(limit, op * 0.999, low, low_limit)
            if proposed > min(high, high_limit) + EPS:
                return reject("invalid_open_fill")
        price = round(float(proposed), 2)
        if quantity > 0 and price > limit + EPS:
            return reject("buy_rounding_limit")
        if quantity < 0 and price < limit - EPS:
            return reject("sell_rounding_limit")
        value = round(abs(quantity) * price, 2)
        commission = self._commission(value)
        transfer_rate = (
            float(self.cfg["transfer_rate_before_2022_04_29"])
            if date < pd.Timestamp("2022-04-29")
            else float(self.cfg["transfer_rate_from_2022_04_29"])
        )
        transfer = round(value * transfer_rate, 2)
        stamp_rate = (
            float(self.cfg["stamp_rate_before_2023_08_28"])
            if date < pd.Timestamp("2023-08-28")
            else float(self.cfg["stamp_rate_from_2023_08_28"])
        )
        stamp = round(value * stamp_rate, 2) if quantity < 0 else 0.0
        fees = commission + transfer + stamp
        divtax = 0.0
        if quantity > 0:
            if value + fees > self.cash + 1e-6:
                return reject("cash")
            if quantity % int(self.cfg["board_lot_shares"]) != 0:
                raise AssertionError("buy quantity is not a board lot")
            self.cash -= value + fees
            position = self.holdings.setdefault(col, {"qty": 0, "last": price, "lots": []})
            position["qty"] += quantity
            position["last"] = price
            position["lots"].append({"q": quantity, "buy": date, "release": date + pd.Timedelta(days=1), "div": 0.0})
        else:
            sell = -quantity
            if col not in self.holdings or sell > self.available(col, date):
                return reject("t_plus_one_or_position")
            position = self.holdings[col]
            remaining = sell
            for lot in position["lots"]:
                if lot["release"] > date or lot["buy"] >= date:
                    continue
                q = min(remaining, lot["q"])
                remaining -= q
                lot["q"] -= q
                rate = 0.2 if date <= lot["buy"] + pd.DateOffset(months=1) else (0.1 if date <= lot["buy"] + pd.DateOffset(years=1) else 0.0)
                divtax += q * lot["div"] * rate
                if remaining == 0:
                    break
            if remaining:
                raise AssertionError("FIFO availability mismatch")
            divtax = round(divtax, 2)
            position["lots"] = [lot for lot in position["lots"] if lot["q"]]
            position["qty"] += quantity
            self.cash += value - fees - divtax
            if position["qty"] == 0:
                del self.holdings[col]
        self.fees += fees
        self.dividend_tax += divtax
        trade = {
            **base,
            "price": price,
            "commission": commission,
            "transfer": transfer,
            "stamp": stamp,
            "dividend_tax": divtax,
            "value": value,
        }
        self.trades.append(trade)
        self.orders.append({**base, "status": "filled", "price": price})
        return True

    def step(self, date: pd.Timestamp) -> None:
        row = self.market.row(date)
        previous = self.market.previous_date(date)
        previous_row = self.market.row(previous)
        self._corporate(date, row)
        for col, old_amount in self.close_shares.items():
            now = int(self.holdings.get(col, {}).get("qty", 0))
            if old_amount > 0 and now > 0 and now != old_amount and col in self.targets:
                self.targets[col] = int(math.floor(self.targets[col] * now / old_amount + EPS))
        due = self.first or self.market.phase_due(date)
        ranks = self.market.rankings[previous] if due else []
        needed = set(self.holdings) | set(self.targets) | set(ranks)
        for col in needed:
            if self.market.present[row, col] and self.market.status[row, col] == 1:
                op = self.market.data["open"][row, col]
                preclose = self.market.data["preclose"][row, col]
                if np.isfinite(op) and np.isfinite(preclose) and op > 0 and preclose > 0:
                    high_limit, low_limit = self.market.limit_prices(row, col)
                    if op < low_limit - EPS or op > high_limit + EPS:
                        self.special_limit_observations.add((col, date))
        open_nav = self._open_nav(row)
        if due:
            budget = open_nav * float(self.cfg["exposure"]) / int(self.cfg["holding_count"])
            keep_depth = int(int(self.cfg["holding_count"]) * float(self.cfg["buffer"]))
            keep = set(ranks[:keep_depth])

            def can_select(col: int) -> bool:
                if not self.market.valid_bar(row, col) or self.market.st[row, col] == 1:
                    return False
                op = float(self.market.data["open"][row, col])
                high_limit, _ = self.market.limit_prices(row, col)
                return op < high_limit - EPS and self._buy_cost(100, op) <= budget

            selected = [col for col in ranks if col in self.holdings and col in keep and can_select(col)][
                : int(self.cfg["holding_count"])
            ]
            for col in ranks:
                if len(selected) >= int(self.cfg["holding_count"]):
                    break
                if col not in selected and can_select(col):
                    selected.append(col)
            targets = {col: 0 for col in self.holdings if col not in selected}
            for col in selected:
                op = float(self.market.data["open"][row, col])
                targets[col] = int(budget / op / int(self.cfg["board_lot_shares"])) * int(self.cfg["board_lot_shares"])
            self.targets = targets
            self.rebalances.append(
                {
                    "start": self.start,
                    "end": self.end,
                    "date": date,
                    "signal_date": previous,
                    "forced_first": self.first,
                    "phase_due": self.market.phase_due(date),
                    "open_nav": open_nav,
                    "budget_per_stock": budget,
                    "selected": json.dumps([self.market.symbols[c] for c in selected], ensure_ascii=False),
                    "targets": json.dumps({self.market.symbols[c]: q for c, q in sorted(targets.items())}, ensure_ascii=False),
                    "top10": json.dumps([self.market.symbols[c] for c in ranks[:10]], ensure_ascii=False),
                }
            )
            self.first = False
        for col in list(self.holdings):
            if self.market.present[previous_row, col] and self.market.st[previous_row, col] == 1:
                self.targets[col] = 0
        cash_budget = self.cash
        keys = sorted(
            self.targets,
            key=lambda col: (
                self.targets[col] - int(self.holdings.get(col, {}).get("qty", 0)) >= 0,
                self.market.symbols[col],
            ),
        )
        for col in keys:
            current = int(self.holdings.get(col, {}).get("qty", 0))
            delta = int(self.targets[col] - current)
            if delta == 0:
                continue
            base = {
                "start": self.start,
                "end": self.end,
                "date": date,
                "symbol": self.market.symbols[col],
                "quantity": delta,
                "limit": np.nan,
                "price": np.nan,
            }
            if not self.market.valid_bar(row, col):
                self.orders.append({**base, "status": "invalid_bar"})
                continue
            volume20 = self.market.data["volume20"][previous_row, col] if self.market.present[previous_row, col] else np.nan
            if not np.isfinite(volume20):
                self.orders.append({**base, "status": "missing_volume20"})
                continue
            cap = int(volume20 * float(self.cfg["participation_of_volume20"]) / 100) * 100
            quantity = min(abs(delta), cap, int(self.cfg["maximum_order_shares"]))
            if delta < 0:
                _, low_limit = self.market.limit_prices(row, col)
                op = float(self.market.data["open"][row, col])
                if op <= low_limit + EPS:
                    self.orders.append({**base, "status": "sell_at_low_limit"})
                    continue
                quantity = min(quantity, self.available(col, date))
                if quantity != current:
                    quantity = int(quantity // 100) * 100
                if quantity <= 0:
                    self.orders.append({**base, "status": "no_available_or_capacity"})
                    continue
                before = self.cash
                self._order(date, row, col, -int(quantity), self._limit_price(row, col, False))
                cash_budget += max(0.0, self.cash - before)
            else:
                high_limit, _ = self.market.limit_prices(row, col)
                op = float(self.market.data["open"][row, col])
                if self.market.st[row, col] == 1 or op >= high_limit - EPS:
                    self.orders.append({**base, "status": "buy_st_or_high_limit"})
                    continue
                quantity = int(quantity // 100) * 100
                available = min(cash_budget, self.cash)
                while quantity > 0 and self._buy_cost(quantity, op) > available:
                    quantity -= 100
                if quantity <= 0:
                    self.orders.append({**base, "status": "cash_or_capacity_below_board_lot"})
                    continue
                accepted = self._order(date, row, col, int(quantity), self._limit_price(row, col, True))
                if accepted:
                    cash_budget -= self._buy_cost(quantity, op)
        market_value = 0.0
        for col, position in self.holdings.items():
            if self.market.present[row, col] and self.market.data["close"][row, col] > 0:
                position["last"] = float(self.market.data["close"][row, col])
            if position["qty"] != sum(lot["q"] for lot in position["lots"]):
                raise AssertionError("lot quantity does not equal position quantity")
            market_value += position["qty"] * position["last"]
        if self.cash < -0.01:
            raise AssertionError(f"negative cash {self.cash}")
        receivables = sum(amount for _, amount, _ in self.receivables)
        equity = self.cash + market_value + receivables
        self.daily.append(
            {
                "start": self.start,
                "end": self.end,
                "commission_multiplier": self.commission_multiplier,
                "date": date,
                "equity": equity,
                "cash": self.cash,
                "market_value": market_value,
                "receivables": receivables,
                "exposure": market_value / equity if equity else np.nan,
                "holdings": len(self.holdings),
                "transaction_fees_to_date": self.fees,
                "dividend_tax_to_date": self.dividend_tax,
            }
        )
        self.close_shares = {col: int(position["qty"]) for col, position in self.holdings.items()}

    def run(self) -> "SimulationResult":
        sessions = self.market.sessions[(self.market.sessions >= self.start) & (self.market.sessions <= self.end)]
        if sessions.empty or sessions[0] != self.start:
            raise RuntimeError(f"invalid simulation start {self.start}")
        for date in sessions:
            self.step(date)
        daily = pd.DataFrame(self.daily)
        equity = daily["equity"].to_numpy(dtype=float)
        daily["strategy_return"] = equity / np.r_[self.initial, equity[:-1]] - 1
        start_pos = self.market.sessions.get_loc(self.start)
        end_pos = self.market.sessions.get_loc(self.end)
        bench_close = self.market.benchmark_close[start_pos : end_pos + 1]
        bench_open = self.market.benchmark_open[start_pos : end_pos + 1]
        bench_ret = np.empty(len(bench_close), dtype=float)
        bench_ret[0] = bench_close[0] / bench_open[0] - 1
        if len(bench_close) > 1:
            bench_ret[1:] = bench_close[1:] / bench_close[:-1] - 1
        daily["benchmark_return"] = bench_ret
        daily["benchmark_nav"] = np.cumprod(1 + bench_ret)
        for col, date in sorted(self.special_limit_observations, key=lambda x: (x[1], self.market.symbols[x[0]])):
            self.issues.setdefault(f"{self.market.symbols[col]}/{date.date()}", "computed 10%/5% limit inconsistent with observed open; special no-limit status unavailable")
        return SimulationResult(
            daily=daily,
            trades=pd.DataFrame(self.trades),
            orders=pd.DataFrame(self.orders),
            actions=pd.DataFrame(self.action_log),
            rebalances=pd.DataFrame(self.rebalances),
            issues=self.issues,
            reference_diffs=self.reference_diffs,
            capacity_hits=self.capacity_hits,
            initial=self.initial,
            total_fees=self.fees,
            dividend_tax=self.dividend_tax,
        )


@dataclass
class SimulationResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    orders: pd.DataFrame
    actions: pd.DataFrame
    rebalances: pd.DataFrame
    issues: dict[str, Any]
    reference_diffs: dict[str, Any]
    capacity_hits: int
    initial: float
    total_fees: float
    dividend_tax: float


def _safe_sharpe(returns: np.ndarray) -> float | None:
    if len(returns) < 2:
        return None
    std = float(np.std(returns, ddof=1))
    return float(np.mean(returns) / std * math.sqrt(252)) if std > 0 else None


def metrics_from_returns(
    dates: pd.DatetimeIndex,
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    label: str,
    annualization_days: float | None = None,
) -> dict[str, Any]:
    if len(dates) == 0:
        raise ValueError("empty metric period")
    strategy_curve = np.cumprod(1 + np.asarray(strategy_returns, dtype=float))
    benchmark_curve = np.cumprod(1 + np.asarray(benchmark_returns, dtype=float))
    strategy_growth = float(strategy_curve[-1])
    benchmark_growth = float(benchmark_curve[-1])
    days = float(annualization_days if annualization_days is not None else (dates[-1] - dates[0]).days + 1)
    strategy_cagr = strategy_growth ** (365.25 / days) - 1 if strategy_growth > 0 else -1.0
    benchmark_cagr = benchmark_growth ** (365.25 / days) - 1 if benchmark_growth > 0 else -1.0
    strategy_peak = np.maximum.accumulate(np.r_[1.0, strategy_curve])[1:]
    benchmark_peak = np.maximum.accumulate(np.r_[1.0, benchmark_curve])[1:]
    return {
        "period": label,
        "start": str(dates[0].date()),
        "end": str(dates[-1].date()),
        "trading_days": len(dates),
        "annualization_calendar_days": days,
        "strategy_growth": strategy_growth,
        "benchmark_growth": benchmark_growth,
        "strategy_period_return": strategy_growth - 1,
        "benchmark_period_return": benchmark_growth - 1,
        "period_excess_difference": strategy_growth - benchmark_growth,
        "strategy_cagr": strategy_cagr,
        "benchmark_cagr": benchmark_cagr,
        "annualized_excess_difference": strategy_cagr - benchmark_cagr,
        "geometric_active_cagr": (strategy_growth / benchmark_growth) ** (365.25 / days) - 1 if benchmark_growth > 0 else None,
        "strategy_max_drawdown": float(np.max(1 - strategy_curve / strategy_peak)),
        "benchmark_max_drawdown": float(np.max(1 - benchmark_curve / benchmark_peak)),
        "strategy_sharpe": _safe_sharpe(np.asarray(strategy_returns, dtype=float)),
    }


def slice_metrics(daily: pd.DataFrame, start: str, end: str, label: str) -> dict[str, Any]:
    d = daily.loc[(daily["date"] >= pd.Timestamp(start)) & (daily["date"] <= pd.Timestamp(end))]
    return metrics_from_returns(
        pd.DatetimeIndex(d["date"]),
        d["strategy_return"].to_numpy(dtype=float),
        d["benchmark_return"].to_numpy(dtype=float),
        label,
    )


def main_diagnostics(result: SimulationResult) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    daily = result.daily
    periods = pd.DataFrame(
        [
            slice_metrics(daily, "2016-01-01", "2019-12-31", "2016-2019"),
            slice_metrics(daily, "2020-01-01", "2024-12-31", "2020-2024"),
            slice_metrics(daily, "2016-01-01", "2024-12-31", "2016-2024"),
        ]
    )
    yearly_rows = []
    for year in range(2016, 2025):
        yearly_rows.append(slice_metrics(daily, f"{year}-01-01", f"{year}-12-31", str(year)))
    yearly = pd.DataFrame(yearly_rows)
    loo_rows = []
    for omitted in range(2016, 2025):
        keep = daily.loc[daily["date"].dt.year.ne(omitted)].copy()
        included_years = sorted(keep["date"].dt.year.unique())
        effective_days = float(
            sum(
                (keep.loc[keep["date"].dt.year.eq(year), "date"].max() - keep.loc[keep["date"].dt.year.eq(year), "date"].min()).days + 1
                for year in included_years
            )
        )
        row = metrics_from_returns(
            pd.DatetimeIndex(keep["date"]),
            keep["strategy_return"].to_numpy(dtype=float),
            keep["benchmark_return"].to_numpy(dtype=float),
            f"omit_{omitted}",
            annualization_days=effective_days,
        )
        row["omitted_year"] = omitted
        loo_rows.append(row)
    loo = pd.DataFrame(loo_rows)
    stability = {
        "annualized_excess_by_year": dict(zip(yearly["period"], yearly["annualized_excess_difference"])),
        "yearly_excess_floor": float(yearly["annualized_excess_difference"].min()),
        "yearly_excess_sample_std": float(yearly["annualized_excess_difference"].std(ddof=1)),
        "loo_excess_floor": float(loo["annualized_excess_difference"].min()),
        "positive_excess_years": int((yearly["annualized_excess_difference"] > 0).sum()),
        "nonpositive_excess_years": int((yearly["annualized_excess_difference"] <= 0).sum()),
    }
    return periods, yearly, loo, stability


def add_scenario_columns(frame: pd.DataFrame, scenario_id: str, horizon: str) -> pd.DataFrame:
    result = frame.copy()
    result.insert(0, "scenario_id", scenario_id)
    result.insert(1, "horizon", horizon)
    return result


def simulation_metric(result: SimulationResult, label: str) -> dict[str, Any]:
    daily = result.daily
    row = metrics_from_returns(
        pd.DatetimeIndex(daily["date"]),
        daily["strategy_return"].to_numpy(dtype=float),
        daily["benchmark_return"].to_numpy(dtype=float),
        label,
    )
    row.update(
        initial_cash=result.initial,
        final_equity=float(daily["equity"].iloc[-1]),
        trades=len(result.trades),
        orders=len(result.orders),
        transaction_fees=result.total_fees,
        dividend_tax=result.dividend_tax,
        total_cost=result.total_fees + result.dividend_tax,
        average_exposure=float(daily["exposure"].mean()),
        unresolved_actions=len(result.issues),
        reference_differences=len(result.reference_diffs),
        capacity_hits=result.capacity_hits,
    )
    return row


def save_simulation(prefix: str, result: SimulationResult) -> dict[str, str]:
    outputs = {
        "daily": HERE / f"{prefix}_daily.parquet",
        "trades": HERE / f"{prefix}_trades.parquet",
        "orders": HERE / f"{prefix}_orders.parquet",
        "actions": HERE / f"{prefix}_actions.parquet",
        "rebalances": HERE / f"{prefix}_rebalances.parquet",
        "audit": HERE / f"{prefix}_account_audit.json",
    }
    atomic_parquet(outputs["daily"], result.daily)
    atomic_parquet(outputs["trades"], result.trades if len(result.trades.columns) else pd.DataFrame({"empty": []}))
    atomic_parquet(outputs["orders"], result.orders if len(result.orders.columns) else pd.DataFrame({"empty": []}))
    atomic_parquet(outputs["actions"], result.actions if len(result.actions.columns) else pd.DataFrame({"empty": []}))
    atomic_parquet(outputs["rebalances"], result.rebalances if len(result.rebalances.columns) else pd.DataFrame({"empty": []}))
    atomic_json(
        outputs["audit"],
        {
            "issues": result.issues,
            "reference_differences": result.reference_diffs,
            "capacity_hits": result.capacity_hits,
            "total_transaction_fees": result.total_fees,
            "dividend_tax": result.dividend_tax,
        },
    )
    return {k: sha256(v) for k, v in outputs.items()}


def prefix_result(result: SimulationResult, end: pd.Timestamp) -> SimulationResult:
    def before(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty or "date" not in frame.columns:
            return frame.copy()
        return frame.loc[pd.to_datetime(frame["date"]) <= end].copy()

    daily = before(result.daily)
    trades = before(result.trades)
    actions = before(result.actions)
    orders = before(result.orders)
    rebalances = before(result.rebalances)
    fees = float(trades[[c for c in ("commission", "transfer", "stamp") if c in trades]].sum().sum()) if not trades.empty else 0.0
    tax = float(trades["dividend_tax"].sum()) if not trades.empty and "dividend_tax" in trades else 0.0
    end_text = str(end.date())
    issues = {k: v for k, v in result.issues.items() if k.rsplit("/", 1)[-1] <= end_text}
    refs = {k: v for k, v in result.reference_diffs.items() if k.rsplit("/", 1)[-1] <= end_text}
    return SimulationResult(
        daily=daily,
        trades=trades,
        orders=orders,
        actions=actions,
        rebalances=rebalances,
        issues=issues,
        reference_diffs=refs,
        capacity_hits=int((orders["status"] == "daily_capacity").sum()) if not orders.empty else 0,
        initial=result.initial,
        total_fees=fees,
        dividend_tax=tax,
    )


def concat_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    nonempty = [x for x in frames if len(x.columns)]
    return pd.concat(nonempty, ignore_index=True) if nonempty else pd.DataFrame({"empty": []})


def run_main(market: ExecutionMarket) -> tuple[SimulationResult, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    start = market.sessions[0]
    end = market.sessions[-1]
    print(f"MAIN_PATH begin {start.date()} {end.date()}", flush=True)
    result = Account(market, start, end, 1).run()
    hashes = save_simulation("main", result)
    periods, yearly, loo, stability = main_diagnostics(result)
    atomic_csv(HERE / "period_metrics.csv", periods)
    atomic_csv(HERE / "yearly_metrics.csv", yearly)
    atomic_csv(HERE / "leave_one_year_out_metrics.csv", loo)
    atomic_json(HERE / "stability_diagnostics_partial.json", stability)
    marker = {
        "status": "complete",
        "stage": "main_path",
        "start": str(start.date()),
        "end": str(end.date()),
        "daily_rows": len(result.daily),
        "hashes": {
            **hashes,
            "period_metrics": sha256(HERE / "period_metrics.csv"),
            "yearly_metrics": sha256(HERE / "yearly_metrics.csv"),
            "leave_one_year_out_metrics": sha256(HERE / "leave_one_year_out_metrics.csv"),
        },
    }
    atomic_json(HERE / "MAIN_PATH_COMPLETE.json", marker)
    for row in periods.itertuples():
        print(
            f"MAIN_METRIC {row.period} cagr={row.strategy_cagr:.8f} benchmark={row.benchmark_cagr:.8f} excess={row.annualized_excess_difference:.8f} dd={row.strategy_max_drawdown:.8f} sharpe={row.strategy_sharpe:.8f}",
            flush=True,
        )
    return result, periods, yearly, loo, stability


def q1_starts(market: ExecutionMarket, year: int) -> pd.DatetimeIndex:
    return market.sessions[(market.sessions.year == year) & (market.sessions.month <= 3)]


def run_q1_batches(market: ExecutionMarket) -> tuple[pd.DataFrame, pd.DataFrame]:
    checkpoint_dir = HERE / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    all_metrics: list[pd.DataFrame] = []
    for year in range(2016, 2025):
        marker = checkpoint_dir / f"q1_{year}_COMPLETE.json"
        if marker.exists():
            raise RuntimeError(f"unexpected pre-existing Q1 checkpoint before unique run: {marker.name}")
        starts = q1_starts(market, year)
        metric_rows: list[dict[str, Any]] = []
        daily_frames: list[pd.DataFrame] = []
        trade_frames: list[pd.DataFrame] = []
        order_frames: list[pd.DataFrame] = []
        action_frames: list[pd.DataFrame] = []
        rebalance_frames: list[pd.DataFrame] = []
        audit_rows: list[dict[str, Any]] = []
        batch_started = time.monotonic()
        for n, start in enumerate(starts, 1):
            full = Account(market, start, market.sessions[-1], 1).run()
            variants: list[tuple[str, SimulationResult]] = [("to_2024_end", full)]
            if year <= 2019:
                variants.insert(0, ("to_2019_segment_end", prefix_result(full, pd.Timestamp("2019-12-31"))))
            for horizon, result in variants:
                scenario_id = f"q1_{year}_{start.date()}_{horizon}"
                row = simulation_metric(result, scenario_id)
                row.update(scenario_id=scenario_id, start_year=year, requested_start=str(start.date()), horizon=horizon)
                metric_rows.append(row)
                daily_frames.append(add_scenario_columns(result.daily, scenario_id, horizon))
                trade_frames.append(add_scenario_columns(result.trades, scenario_id, horizon) if len(result.trades.columns) else pd.DataFrame())
                order_frames.append(add_scenario_columns(result.orders, scenario_id, horizon) if len(result.orders.columns) else pd.DataFrame())
                action_frames.append(add_scenario_columns(result.actions, scenario_id, horizon) if len(result.actions.columns) else pd.DataFrame())
                rebalance_frames.append(add_scenario_columns(result.rebalances, scenario_id, horizon) if len(result.rebalances.columns) else pd.DataFrame())
                audit_rows.append(
                    {
                        "scenario_id": scenario_id,
                        "issues": len(result.issues),
                        "reference_differences": len(result.reference_diffs),
                        "capacity_hits": result.capacity_hits,
                    }
                )
            if n % 10 == 0 or n == len(starts):
                print(
                    f"Q1_BATCH year={year} starts={n}/{len(starts)} elapsed={time.monotonic()-batch_started:.1f}s",
                    flush=True,
                )
        metrics = pd.DataFrame(metric_rows)
        paths = {
            "metrics": checkpoint_dir / f"q1_{year}_metrics.csv",
            "daily": checkpoint_dir / f"q1_{year}_daily.parquet",
            "trades": checkpoint_dir / f"q1_{year}_trades.parquet",
            "orders": checkpoint_dir / f"q1_{year}_orders.parquet",
            "actions": checkpoint_dir / f"q1_{year}_actions.parquet",
            "rebalances": checkpoint_dir / f"q1_{year}_rebalances.parquet",
            "audit": checkpoint_dir / f"q1_{year}_audit.csv",
        }
        atomic_csv(paths["metrics"], metrics)
        atomic_parquet(paths["daily"], concat_frames(daily_frames))
        atomic_parquet(paths["trades"], concat_frames(trade_frames))
        atomic_parquet(paths["orders"], concat_frames(order_frames))
        atomic_parquet(paths["actions"], concat_frames(action_frames))
        atomic_parquet(paths["rebalances"], concat_frames(rebalance_frames))
        atomic_csv(paths["audit"], pd.DataFrame(audit_rows))
        atomic_json(
            marker,
            {
                "status": "complete",
                "year": year,
                "q1_starts": len(starts),
                "scenario_rows": len(metrics),
                "prefix_sharing": "Each early start ran once to 2024; its 2019 horizon is the exact saved prefix.",
                "hashes": {k: sha256(v) for k, v in paths.items()},
            },
        )
        all_metrics.append(metrics)
        print(f"Q1_YEAR_COMPLETE {year} scenarios={len(metrics)}", flush=True)
    combined = pd.concat(all_metrics, ignore_index=True)
    atomic_csv(HERE / "q1_all_start_metrics.csv", combined)
    summary = (
        combined.groupby(["start_year", "horizon"], as_index=False)
        .agg(
            starts=("requested_start", "nunique"),
            mean_strategy_cagr=("strategy_cagr", "mean"),
            mean_annualized_excess=("annualized_excess_difference", "mean"),
            worst_annualized_excess=("annualized_excess_difference", "min"),
            mean_max_drawdown=("strategy_max_drawdown", "mean"),
            worst_max_drawdown=("strategy_max_drawdown", "max"),
            mean_sharpe=("strategy_sharpe", "mean"),
            worst_sharpe=("strategy_sharpe", "min"),
        )
    )
    overall = (
        combined.groupby("horizon", as_index=False)
        .agg(
            starts=("requested_start", "nunique"),
            mean_strategy_cagr=("strategy_cagr", "mean"),
            mean_annualized_excess=("annualized_excess_difference", "mean"),
            worst_annualized_excess=("annualized_excess_difference", "min"),
            mean_max_drawdown=("strategy_max_drawdown", "mean"),
            worst_max_drawdown=("strategy_max_drawdown", "max"),
            mean_sharpe=("strategy_sharpe", "mean"),
            worst_sharpe=("strategy_sharpe", "min"),
        )
    )
    overall.insert(0, "start_year", "ALL")
    summary = pd.concat([summary, overall], ignore_index=True)
    atomic_csv(HERE / "q1_summary.csv", summary)
    atomic_json(
        HERE / "Q1_ALL_COMPLETE.json",
        {
            "status": "complete",
            "unique_starts": int(combined["requested_start"].nunique()),
            "scenario_rows": len(combined),
            "metrics_sha256": sha256(HERE / "q1_all_start_metrics.csv"),
            "summary_sha256": sha256(HERE / "q1_summary.csv"),
        },
    )
    return combined, summary


def run_fee_stress(market: ExecutionMarket, baseline: SimulationResult) -> pd.DataFrame:
    metrics: list[dict[str, Any]] = []
    daily_frames = [add_scenario_columns(baseline.daily, "fee_1x", "full_period")]
    trade_frames = [add_scenario_columns(baseline.trades, "fee_1x", "full_period")]
    order_frames = [add_scenario_columns(baseline.orders, "fee_1x", "full_period")]
    action_frames = [add_scenario_columns(baseline.actions, "fee_1x", "full_period")]
    rebalance_frames = [add_scenario_columns(baseline.rebalances, "fee_1x", "full_period")]
    row = simulation_metric(baseline, "fee_1x")
    row["commission_multiplier"] = 1
    metrics.append(row)
    for multiplier in (2, 3):
        print(f"FEE_STRESS begin {multiplier}x", flush=True)
        result = Account(market, market.sessions[0], market.sessions[-1], multiplier).run()
        scenario = f"fee_{multiplier}x"
        row = simulation_metric(result, scenario)
        row["commission_multiplier"] = multiplier
        metrics.append(row)
        daily_frames.append(add_scenario_columns(result.daily, scenario, "full_period"))
        trade_frames.append(add_scenario_columns(result.trades, scenario, "full_period"))
        order_frames.append(add_scenario_columns(result.orders, scenario, "full_period"))
        action_frames.append(add_scenario_columns(result.actions, scenario, "full_period"))
        rebalance_frames.append(add_scenario_columns(result.rebalances, scenario, "full_period"))
    table = pd.DataFrame(metrics)
    atomic_csv(HERE / "fee_stress_metrics.csv", table)
    atomic_parquet(HERE / "fee_stress_daily.parquet", concat_frames(daily_frames))
    atomic_parquet(HERE / "fee_stress_trades.parquet", concat_frames(trade_frames))
    atomic_parquet(HERE / "fee_stress_orders.parquet", concat_frames(order_frames))
    atomic_parquet(HERE / "fee_stress_actions.parquet", concat_frames(action_frames))
    atomic_parquet(HERE / "fee_stress_rebalances.parquet", concat_frames(rebalance_frames))
    atomic_json(
        HERE / "FEE_STRESS_COMPLETE.json",
        {
            "status": "complete",
            "multipliers": [1, 2, 3],
            "metrics_sha256": sha256(HERE / "fee_stress_metrics.csv"),
        },
    )
    return table


def pretest_lock() -> None:
    if (HERE / "RUN_STARTED.json").exists() or (HERE / "FROZEN_BEFORE_EVALUATION.json").exists():
        raise RuntimeError("pretest lock cannot be changed after evaluation freeze/start")
    files = [PROTOCOL_PATH, CONFIG_PATH, EXTENSION_PATH, Path(__file__).resolve()]
    atomic_json(
        HERE / "PRETEST_LOCK.json",
        {
            "status": "protocol_input_and_code_locked_before_tests",
            "files": {p.name: sha256(p) for p in files},
            "performance_computed": False,
        },
    )
    print("PRETEST_LOCK_COMPLETE", flush=True)


def verify_pretest_lock() -> None:
    path = HERE / "PRETEST_LOCK.json"
    if not path.exists():
        raise RuntimeError("PRETEST_LOCK.json missing")
    lock = json.loads(path.read_text(encoding="utf-8"))
    for name, expected in lock["files"].items():
        actual = sha256(HERE / name)
        if actual != expected:
            raise RuntimeError(f"pretest-locked file changed: {name}")


def synthetic_raw() -> tuple[dict[str, pd.DataFrame], MembershipMap, pd.DatetimeIndex]:
    dates = pd.bdate_range("2013-01-02", periods=290)
    symbols = [f"6000{i:02d}.SH" for i in range(12)]
    raw: dict[str, pd.DataFrame] = {}
    for j, symbol in enumerate(symbols):
        t = np.arange(len(dates), dtype=float)
        close = 8.0 + j * 0.3 + 0.006 * t + 0.12 * np.sin(t / (7.0 + j / 3.0))
        prev = np.r_[close[0] / 1.001, close[:-1]]
        op = prev * (1 + 0.0015 * np.cos(t / (5.0 + j / 5.0)))
        frame = pd.DataFrame(
            {
                "open": op,
                "close": close,
                "prev_close": prev,
                "volume": 2_000_000 + j * 20_000 + t * 100,
                "turnover": 30_000_000 + j * 100_000 + t * 1000,
                "turnover_rate": 0.8 + j * 0.03 + 0.01 * np.sin(t / 9),
                "is_paused": np.zeros(len(t)),
                "is_st": np.zeros(len(t)),
            },
            index=dates,
        )
        if j == 10:
            frame.loc[dates[-2], "is_paused"] = 1
        if j == 11:
            frame.loc[dates[-1], "is_st"] = 1
        raw[symbol] = frame
    ipo = {s: dates[0] for s in symbols}
    out = {symbols[-1]: dates[-1] + pd.Timedelta(days=1)}
    return raw, MembershipMap(symbols, ipo, out), dates


class FakeMarket:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.symbols = ["600000.SH"]
        dates = pd.DatetimeIndex([pd.Timestamp("2021-06-01"), pd.Timestamp("2021-06-02"), pd.Timestamp("2021-06-03")])
        self.dates = dates
        self.present = np.ones((3, 1), dtype=bool)
        self.status = np.ones((3, 1), dtype=np.int8)
        self.st = np.zeros((3, 1), dtype=np.int8)
        self.data = {k: np.full((3, 1), np.nan, dtype=float) for k in ExecutionMarket.FIELDS}
        for i in range(3):
            self.data["open"][i, 0] = 10.0
            self.data["high"][i, 0] = 10.2
            self.data["low"][i, 0] = 9.8
            self.data["close"][i, 0] = 10.0
            self.data["preclose"][i, 0] = 10.0
            self.data["volume"][i, 0] = 1_000_000
            self.data["volume20"][i, 0] = 1_000_000
            self.data["prev_actual"][i, 0] = 10.0
            self.data["adjust_ratio"][i, 0] = 1.0
        self.actions: dict[tuple[int, pd.Timestamp], Action] = {}
        self.out_by_col: dict[int, pd.Timestamp] = {}

    def limit_prices(self, row: int, col: int) -> tuple[float, float]:
        pct = self.cfg["st_daily_limit"] if self.st[row, col] == 1 else self.cfg["normal_daily_limit"]
        preclose = self.data["preclose"][row, col]
        return (
            math.floor(preclose * (1 + pct) * 100 + 0.5) / 100,
            math.floor(preclose * (1 - pct) * 100 + 0.5) / 100,
        )


def self_test() -> None:
    verify_pretest_lock()
    checks: dict[str, Any] = {}
    approved, _ = load_approved_functions(instrument_batch=False)
    approved_batch, _ = load_approved_functions(instrument_batch=True)
    raw, members, dates = synthetic_raw()
    signal_checks = []
    for end_index in (270, 280, 289):
        window = dates[end_index - 4 : end_index + 1]
        approved_ranking, approved_info = approved(raw, members, window)
        smooth, eligible = production_signal_batch(raw, members, window)
        production = smooth.iloc[-1].where(eligible.iloc[-1]).dropna().sort_values(ascending=False, kind="mergesort").index.tolist()[:100]
        ref_ranking, _ref_info, ref_smooth, ref_eligible = approved_batch(raw, members, window)
        ref_rank = ref_smooth.iloc[-1].where(ref_eligible.iloc[-1]).dropna().sort_values(ascending=False, kind="mergesort").index.tolist()[:100]
        exact = approved_ranking == production == ref_ranking == ref_rank
        if not exact:
            raise AssertionError(f"synthetic approved ranking mismatch at {window[-1]}")
        last_symbol = sorted(raw)[0]
        expected_volume20 = float(raw[last_symbol]["volume"].rolling(20).mean().loc[window[-1]])
        if not math.isclose(approved_info[last_symbol]["volume20"], expected_volume20, rel_tol=0, abs_tol=1e-12):
            raise AssertionError("approved info volume20 mismatch")
        signal_checks.append({"end": str(window[-1].date()), "ranking_count": len(production), "exact": exact})
    checks["signal"] = signal_checks
    cfg = load_config()
    fake = FakeMarket(cfg)
    account = Account(fake, fake.dates[0], fake.dates[-1], 1)
    buy = account._order(fake.dates[0], 0, 0, 100, 10.01)
    same_day_sell = account._order(fake.dates[0], 0, 0, -100, 9.99)
    next_day_sell = account._order(fake.dates[1], 1, 0, -100, 9.99)
    if not buy or same_day_sell or not next_day_sell:
        raise AssertionError("T+1 synthetic test failed")
    checks["t_plus_one"] = {"buy_filled": buy, "same_day_sell_rejected": not same_day_sell, "next_day_sell_filled": next_day_sell}
    action_account = Account(fake, fake.dates[0], fake.dates[-1], 1)
    action_account.holdings[0] = {
        "qty": 100,
        "last": 10.0,
        "lots": [{"q": 100, "buy": pd.Timestamp("2021-01-04"), "release": pd.Timestamp("2021-01-05"), "div": 0.0}],
    }
    action = Action(0.1, 0.1, 0.05, fake.dates[2], fake.dates[2], False, False)
    fake.actions[(0, fake.dates[1])] = action
    fake.data["prev_actual"][1, 0] = 10.1
    fake.data["preclose"][1, 0] = (10.1 - 0.1) / 1.1
    action_account._corporate(fake.dates[1], 1)
    if action_account.holdings[0]["qty"] != 110 or not math.isclose(sum(x[1] for x in action_account.receivables), 10.0):
        raise AssertionError("corporate action synthetic test failed")
    if action_account.available(0, fake.dates[1]) != 100 or action_account.available(0, fake.dates[2]) != 110:
        raise AssertionError("bonus share release synthetic test failed")
    checks["corporate_action"] = {"shares_after_bonus": 110, "cash_receivable": 10.0, "release_enforced": True}
    calendar = trading_calendar()
    anchor = pd.Timestamp(cfg["rebalance_anchor"])
    anchor_pos = calendar.get_loc(anchor)
    due_next = (1 - 1) % 20 == 0
    due_anchor = (0 - 1) % 20 == 0
    due_back = ((calendar.get_loc(calendar[anchor_pos - 19]) - anchor_pos - 1) % 20) == 0
    if due_anchor or not due_next or not due_back:
        raise AssertionError("rebalance phase synthetic test failed")
    checks["phase"] = {"anchor_due_without_force": due_anchor, "next_session_due": due_next, "backward_extension_due": due_back}
    result = {"passed": True, "checks": checks, "performance_computed": False}
    atomic_json(HERE / "SYNTHETIC_TEST.json", result)
    print("SYNTHETIC_TEST_COMPLETE", flush=True)


def freeze_before_evaluation() -> None:
    verify_pretest_lock()
    required = [
        HERE / "SYNTHETIC_TEST.json",
        HERE / "SIGNAL_EQUIVALENCE.json",
        HERE / "SIGNAL_CACHE_MANIFEST.json",
        HERE / "INPUT_AUDIT_BEFORE_PERFORMANCE.json",
        HERE / "RAW_INPUT_HASH_VERIFICATION.csv",
        HERE / "signal_rankings.parquet",
        HERE / "signal_cache_diagnostics.csv",
    ]
    for path in required:
        if not path.exists():
            raise RuntimeError(f"pre-evaluation artifact missing: {path.name}")
    if not json.loads((HERE / "SYNTHETIC_TEST.json").read_text(encoding="utf-8"))["passed"]:
        raise RuntimeError("synthetic test did not pass")
    if not json.loads((HERE / "SIGNAL_EQUIVALENCE.json").read_text(encoding="utf-8"))["passed"]:
        raise RuntimeError("signal equivalence did not pass")
    locked = [PROTOCOL_PATH, CONFIG_PATH, EXTENSION_PATH, Path(__file__).resolve(), HERE / "PRETEST_LOCK.json", *required]
    atomic_json(
        HERE / "FROZEN_BEFORE_EVALUATION.json",
        {
            "status": "frozen_before_any_performance_calculation",
            "locked_files": {p.name: sha256(p) for p in locked},
            "formula_or_parameter_search": False,
            "performance_computed": False,
        },
    )
    print("EVALUATION_FREEZE_COMPLETE", flush=True)


def verify_evaluation_freeze() -> dict[str, Any]:
    path = HERE / "FROZEN_BEFORE_EVALUATION.json"
    if not path.exists():
        raise RuntimeError("evaluation freeze missing")
    lock = json.loads(path.read_text(encoding="utf-8"))
    for name, expected in lock["locked_files"].items():
        actual = sha256(HERE / name)
        if actual != expected:
            raise RuntimeError(f"evaluation-locked file changed: {name}")
    return lock


def _pct(value: Any) -> str:
    return "NA" if value is None or pd.isna(value) else f"{float(value) * 100:.2f}%"


def _numfmt(value: Any) -> str:
    return "NA" if value is None or pd.isna(value) else f"{float(value):.3f}"


def write_final_reports(
    periods: pd.DataFrame,
    yearly: pd.DataFrame,
    loo: pd.DataFrame,
    stability: dict[str, Any],
    q1_metrics: pd.DataFrame,
    q1_summary: pd.DataFrame,
    fees: pd.DataFrame,
    main: SimulationResult,
    market: ExecutionMarket,
) -> tuple[dict[str, Any], dict[str, Any]]:
    primary_rows = periods.set_index("period").loc[["2016-2019", "2020-2024", "2016-2024"]]
    primary_pass = bool((primary_rows["annualized_excess_difference"] > 0).all())
    gate = {
        "definition": "2016-2019, 2020-2024 and 2016-2024 annualized excess differences must each be strictly positive",
        "period_excess": primary_rows["annualized_excess_difference"].to_dict(),
        "passed": primary_pass,
        "formula_changed_after_results": False,
    }
    atomic_json(HERE / "STRICT_TRANSFER_GATE.json", gate)
    expected_starts = sum(len(q1_starts(market, year)) for year in range(2016, 2025))
    expected_rows = expected_starts + sum(len(q1_starts(market, year)) for year in range(2016, 2020))
    raw_verification = pd.read_csv(HERE / "RAW_INPUT_HASH_VERIFICATION.csv")
    integrity = {
        "evaluation_lock_verified": True,
        "raw_hash_rows": len(raw_verification),
        "all_raw_hashes_match": bool(raw_verification["match"].eq(True).all()),
        "main_daily_rows": len(main.daily),
        "expected_main_daily_rows": len(market.sessions),
        "main_dates_exact": bool(pd.DatetimeIndex(main.daily["date"]).equals(market.sessions)),
        "main_null_equity": int(main.daily["equity"].isna().sum()),
        "main_min_cash": float(main.daily["cash"].min()),
        "main_max_actual_holdings": int(main.daily["holdings"].max()),
        "q1_unique_starts": int(q1_metrics["requested_start"].nunique()),
        "expected_q1_unique_starts": expected_starts,
        "q1_scenario_rows": len(q1_metrics),
        "expected_q1_scenario_rows": expected_rows,
        "q1_checkpoints": {str(y): (HERE / "checkpoints" / f"q1_{y}_COMPLETE.json").exists() for y in range(2016, 2025)},
        "fee_multipliers": sorted(fees["commission_multiplier"].astype(int).tolist()),
        "latest_evaluation_date": str(pd.to_datetime(main.daily["date"]).max().date()),
        "action_input_audit": market.action_audit,
        "main_unresolved_action_or_adjustment_issues": len(main.issues),
        "main_action_reference_differences": len(main.reference_diffs),
        "special_limit_semantics_limitation": "The whitelist cannot identify listing/special no-limit sessions; observed opens outside computed 10%/5% limits are invalid bars and are recorded, not reclassified.",
        "intraday_limitation": "Authorized strict daily fill approximation; minute order queue is unavailable.",
    }
    integrity["passed"] = bool(
        integrity["all_raw_hashes_match"]
        and integrity["main_daily_rows"] == integrity["expected_main_daily_rows"]
        and integrity["main_dates_exact"]
        and integrity["main_null_equity"] == 0
        and integrity["main_min_cash"] >= -0.01
        and integrity["q1_unique_starts"] == integrity["expected_q1_unique_starts"]
        and integrity["q1_scenario_rows"] == integrity["expected_q1_scenario_rows"]
        and all(integrity["q1_checkpoints"].values())
        and integrity["fee_multipliers"] == [1, 2, 3]
        and integrity["latest_evaluation_date"] == "2024-12-31"
    )
    atomic_json(HERE / "INTEGRITY_REPORT.json", integrity)
    stability.update(
        {
            "q1_mean_excess_floor_across_groups": float(q1_summary["mean_annualized_excess"].min()),
            "q1_worst_start_excess": float(q1_metrics["annualized_excess_difference"].min()),
            "fee_stress_full_period_excess": dict(
                zip(fees["commission_multiplier"].astype(str), fees["annualized_excess_difference"])
            ),
        }
    )
    atomic_json(HERE / "stability_diagnostics.json", stability)
    lines = [
        "# 原沪深1固定5只：2016—2024跨年份稳定性结果",
        "",
        "本报告来自预注册后唯一一次真实评估。公式、过滤、20交易日相位、5只持仓和执行常数均未依据结果调整。",
        "",
        "## 主路径",
        "",
        "| 区间 | 策略CAGR | 上证CAGR | 年化超额差 | 最大回撤 | Sharpe |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in periods.itertuples():
        lines.append(
            f"| {row.period} | {_pct(row.strategy_cagr)} | {_pct(row.benchmark_cagr)} | {_pct(row.annualized_excess_difference)} | {_pct(row.strategy_max_drawdown)} | {_numfmt(row.strategy_sharpe)} |"
        )
    lines.extend(
        [
            "",
            "## 逐年主路径切片",
            "",
            "| 年份 | 策略CAGR | 上证CAGR | 年化超额差 | 最大回撤 | Sharpe |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in yearly.itertuples():
        lines.append(
            f"| {row.period} | {_pct(row.strategy_cagr)} | {_pct(row.benchmark_cagr)} | {_pct(row.annualized_excess_difference)} | {_pct(row.strategy_max_drawdown)} | {_numfmt(row.strategy_sharpe)} |"
        )
    lines.extend(
        [
            "",
            f"逐年年化超额下限：{_pct(stability['yearly_excess_floor'])}；跨年样本标准差：{_pct(stability['yearly_excess_sample_std'])}。",
            "",
            "## Q1全交易日起点",
            "",
            "| 起点年 | 终点 | 起点数 | 平均策略CAGR | 平均年化超额 | 最差年化超额 | 最差回撤 | 平均Sharpe | 最差Sharpe |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in q1_summary.itertuples():
        lines.append(
            f"| {row.start_year} | {row.horizon} | {int(row.starts)} | {_pct(row.mean_strategy_cagr)} | {_pct(row.mean_annualized_excess)} | {_pct(row.worst_annualized_excess)} | {_pct(row.worst_max_drawdown)} | {_numfmt(row.mean_sharpe)} | {_numfmt(row.worst_sharpe)} |"
        )
    lines.extend(
        [
            "",
            "## Leave-one-year-out",
            "",
            "| 遗漏年份 | 策略CAGR | 上证CAGR | 年化超额差 | 最大回撤 | Sharpe |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in loo.itertuples():
        lines.append(
            f"| {int(row.omitted_year)} | {_pct(row.strategy_cagr)} | {_pct(row.benchmark_cagr)} | {_pct(row.annualized_excess_difference)} | {_pct(row.strategy_max_drawdown)} | {_numfmt(row.strategy_sharpe)} |"
        )
    lines.extend(
        [
            "",
            "## 佣金压力",
            "",
            "| 佣金倍数 | 策略CAGR | 上证CAGR | 年化超额差 | 最大回撤 | Sharpe | 总成本 |",
            "|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for row in fees.itertuples():
        lines.append(
            f"| {int(row.commission_multiplier)}x | {_pct(row.strategy_cagr)} | {_pct(row.benchmark_cagr)} | {_pct(row.annualized_excess_difference)} | {_pct(row.strategy_max_drawdown)} | {_numfmt(row.strategy_sharpe)} | {float(row.total_cost):.2f} |"
        )
    lines.extend(
        [
            "",
            "## 审计结论",
            "",
            f"- 两段与全期超额均严格为正：{'通过' if primary_pass else '未通过'}。",
            f"- 完整性检查：{'通过' if integrity['passed'] else '未通过'}。",
            f"- 主路径未解释公司行动/复权问题数：{len(main.issues)}；除权参考差异数：{len(main.reference_diffs)}。",
            "- 日线撮合是批准的严格近似；白名单不能识别特殊无涨跌停状态，相关开盘越界按不可交易处理并留痕。",
        ]
    )
    atomic_text(HERE / "RESULTS.md", "\n".join(lines) + "\n")
    if primary_pass:
        conclusion = (
            "# 失败结论记录\n\n"
            "预注册的‘2016—2019、2020—2024、全期年化超额均严格为正’判断没有触发失败。"
            "这不消除逐年、Q1起点、LOO、费用及日线近似中显示的风险；详见 RESULTS.md。\n"
        )
    else:
        failed = [str(idx) for idx, value in primary_rows["annualized_excess_difference"].items() if value <= 0]
        conclusion = (
            "# 失败结论\n\n"
            "原沪深1固定5只基线未通过预注册的两段与全期均为正判断。"
            f"未通过区间：{', '.join(failed)}。本结论原样保留，不修改公式、常数或重跑挑选。\n"
        )
    atomic_text(HERE / "FAILURE_CONCLUSION.md", conclusion)
    return gate, integrity


def output_manifest() -> None:
    rows = []
    for path in sorted(HERE.rglob("*")):
        if not path.is_file() or path.name == "OUTPUT_MANIFEST_SHA256.json" or path.suffix == ".tmp":
            continue
        rows.append({"path": path.relative_to(HERE).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    atomic_json(HERE / "OUTPUT_MANIFEST_SHA256.json", {"files": rows})


def execute_evaluation() -> None:
    lock = verify_evaluation_freeze()
    if (HERE / "RUN_STARTED.json").exists():
        raise RuntimeError("unique evaluation already started; do not rerun")
    atomic_json(
        HERE / "RUN_STARTED.json",
        {
            "status": "started",
            "frozen_lock_sha256": sha256(HERE / "FROZEN_BEFORE_EVALUATION.json"),
            "unique_real_evaluation": True,
        },
    )
    market = ExecutionMarket(load_config())
    main, periods, yearly, loo, stability = run_main(market)
    q1_metrics, q1_summary = run_q1_batches(market)
    fees = run_fee_stress(market, main)
    gate, integrity = write_final_reports(periods, yearly, loo, stability, q1_metrics, q1_summary, fees, main, market)
    summary = {
        "strategy": "original Hushen1 D11 fixed five",
        "initial_cash_cny": load_config()["initial_cash_cny"],
        "period_metrics": periods.to_dict("records"),
        "yearly_excess_floor": stability["yearly_excess_floor"],
        "yearly_excess_sample_std": stability["yearly_excess_sample_std"],
        "loo_excess_floor": stability["loo_excess_floor"],
        "q1_scenarios": len(q1_metrics),
        "transfer_gate": gate,
        "integrity": integrity,
        "formula_or_parameter_search": False,
    }
    atomic_json(HERE / "SUMMARY.json", summary)
    atomic_json(
        HERE / "RUN_COMPLETE.json",
        {
            "status": "complete",
            "unique_real_evaluation": True,
            "frozen_lock_sha256": sha256(HERE / "FROZEN_BEFORE_EVALUATION.json"),
            "integrity_passed": integrity["passed"],
            "transfer_gate_passed": gate["passed"],
        },
    )
    output_manifest()
    print("EVALUATION_COMPLETE", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pretest-lock", action="store_true")
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--prepare-signals", action="store_true")
    group.add_argument("--freeze", action="store_true")
    group.add_argument("--execute-frozen", action="store_true")
    args = parser.parse_args()
    if args.pretest_lock:
        pretest_lock()
    elif args.self_test:
        self_test()
    elif args.prepare_signals:
        verify_pretest_lock()
        prepare_signals()
    elif args.freeze:
        freeze_before_evaluation()
    elif args.execute_frozen:
        try:
            execute_evaluation()
        except Exception as exc:
            atomic_json(HERE / "RUN_FAILED.json", {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)})
            raise


if __name__ == "__main__":
    main()





