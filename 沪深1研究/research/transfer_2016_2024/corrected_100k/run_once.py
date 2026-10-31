from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
INPUT = HERE.parent / "inputs_pre2025"
CONFIG_PATH = HERE / "frozen_config.json"
PROTOCOL_PATH = HERE / "PROTOCOL_FROZEN.md"
LOCK_PATH = HERE / "FROZEN_BEFORE_EVALUATION.json"
START_MARKER = HERE / "RUN_STARTED.json"
COMPLETE_MARKER = HERE / "RUN_COMPLETE.json"
FAILED_MARKER = HERE / "RUN_FAILED.json"

CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
CUTOFF = pd.Timestamp(CONFIG["cutoff"])
RESEARCH_START = pd.Timestamp(CONFIG["research_start"])
RESEARCH_END = pd.Timestamp(CONFIG["research_end"])


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def finite_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def parse_date(value: Any) -> pd.Timestamp | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = pd.Timestamp(text).normalize()
    if parsed > CUTOFF:
        raise ValueError(f"Boundary violation in dated input: {parsed.date()}")
    return parsed


def parse_after_tax_cash(value: Any, before_tax: float) -> float:
    numbers = [float(item) for item in re.findall(r"\d+(?:\.\d+)?", str(value or ""))]
    if numbers:
        return min(numbers)
    return before_tax * float(CONFIG["fallback_cash_dividend_net_fraction"])


def verify_freeze() -> dict[str, Any]:
    if not LOCK_PATH.exists():
        raise RuntimeError("Frozen lock file is missing")
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    for relative, expected in lock["frozen_files"].items():
        actual = sha256_file(HERE / relative)
        if actual.lower() != expected.lower():
            raise RuntimeError(f"Frozen file hash mismatch: {relative}")
    for relative, expected in lock["input_files"].items():
        actual = sha256_file(INPUT / relative)
        if actual.lower() != expected.lower():
            raise RuntimeError(f"Input file hash mismatch: {relative}")
    if lock["instruction_boundary_version"] != "public-pre2025-v2":
        raise RuntimeError("Unexpected instruction boundary version")
    return lock


def load_manifest_and_verify_raw() -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = INPUT / "PUBLIC_INPUT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("cutoff") != CONFIG["cutoff"]:
        raise RuntimeError("Manifest cutoff does not match frozen cutoff")
    if manifest.get("isolation_rule") != (
        "No row, metadata outcome, action, benchmark value or result after 2024-12-31 is included."
    ):
        raise RuntimeError("Unexpected manifest isolation declaration")

    raw_paths: dict[str, Path] = {}
    verification_rows: list[dict[str, Any]] = []
    for entry in manifest["files"]:
        if "path" not in entry:
            continue
        relative = Path(entry["path"])
        if not relative.parts or relative.parts[0] != "inputs_pre2025":
            raise RuntimeError(f"Unexpected manifest path: {relative}")
        path = INPUT.joinpath(*relative.parts[1:]).resolve()
        if INPUT.resolve() not in path.parents:
            raise RuntimeError(f"Manifest path escapes whitelist: {path}")
        actual = sha256_file(path)
        matches = actual.lower() == entry["sha256"].lower()
        verification_rows.append(
            {
                "symbol": entry["symbol"],
                "path": str(relative).replace("\\", "/"),
                "manifest_sha256": entry["sha256"].lower(),
                "actual_sha256": actual.lower(),
                "matches": matches,
                "rows_in_manifest": int(entry["rows"]),
                "start_in_manifest": entry["start"],
                "end_in_manifest": entry["end"],
            }
        )
        if not matches:
            raise RuntimeError(f"Raw input hash mismatch: {entry['symbol']}")
        if pd.Timestamp(entry["end"]) > CUTOFF:
            raise RuntimeError(f"Raw manifest end date exceeds cutoff: {entry['symbol']}")
        raw_paths[entry["symbol"]] = path

    pd.DataFrame(verification_rows).to_csv(HERE / "RAW_INPUT_HASH_VERIFICATION.csv", index=False)
    if len(raw_paths) != int(manifest["symbols_with_rows"]):
        raise RuntimeError("Raw manifest symbol count mismatch")
    return manifest, raw_paths


def load_universe(raw_symbols: set[str]) -> tuple[dict[str, pd.Timestamp | None], dict[str, Any]]:
    retained: dict[str, pd.Timestamp | None] = {}
    quarantined_future_rows = 0
    ignored_non_manifest_rows = 0
    with (INPUT / "universe.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"ipoDate", "outDate", "symbol", "board", "status"}
        if not required.issubset(reader.fieldnames or []):
            raise RuntimeError("Universe schema is missing required fields")
        for row in reader:
            ipo_text = str(row.get("ipoDate") or "").strip()
            if not ipo_text:
                ignored_non_manifest_rows += 1
                continue
            ipo_date = pd.Timestamp(ipo_text).normalize()
            if ipo_date > CUTOFF:
                quarantined_future_rows += 1
                continue
            symbol = str(row["symbol"]).strip()
            if symbol not in raw_symbols:
                ignored_non_manifest_rows += 1
                continue
            if row.get("board") != "main":
                raise RuntimeError(f"Non-main-board symbol entered whitelist: {symbol}")
            out_date = parse_date(row.get("outDate"))
            if symbol in retained:
                raise RuntimeError(f"Duplicate retained universe symbol: {symbol}")
            retained[symbol] = out_date

    if set(retained) != raw_symbols:
        missing = sorted(raw_symbols - set(retained))
        raise RuntimeError(f"Manifest symbols missing from boundary-safe universe: {missing[:5]}")
    audit = {
        "retained_boundary_safe_symbols": len(retained),
        "quarantined_universe_rows_with_ipo_after_cutoff": quarantined_future_rows,
        "ignored_non_manifest_or_missing_ipo_rows": ignored_non_manifest_rows,
        "status_field_used": False,
        "outDate_use": "only on or after the dated event in simulation",
    }
    return retained, audit


def load_calendar_and_index() -> tuple[pd.DatetimeIndex, pd.DataFrame, dict[str, Any]]:
    calendar = pd.read_csv(INPUT / "calendar.csv")
    calendar["calendar_date"] = pd.to_datetime(calendar["calendar_date"]).dt.normalize()
    if calendar["calendar_date"].max() > CUTOFF:
        raise RuntimeError("Calendar crosses cutoff")
    trading = pd.DatetimeIndex(
        calendar.loc[calendar["is_trading_day"].astype(int) == 1, "calendar_date"].sort_values().unique()
    )
    if trading.empty or trading.max() != RESEARCH_END:
        raise RuntimeError("Unexpected trading calendar range")

    index = pd.read_parquet(INPUT / "sse_price_index.parquet")
    index["date"] = pd.to_datetime(index["date"]).dt.normalize()
    if index["date"].max() > CUTOFF or index["date"].duplicated().any():
        raise RuntimeError("Benchmark date boundary or uniqueness failure")
    index = index.set_index("date").reindex(trading)
    if index[["open", "close"]].isna().any().any() or (index[["open", "close"]] <= 0).any().any():
        raise RuntimeError("Benchmark is incomplete on the trading calendar")
    audit = {
        "calendar_first_trading_day": str(trading.min().date()),
        "calendar_last_trading_day": str(trading.max().date()),
        "calendar_trading_days": len(trading),
        "benchmark_rows": len(index),
        "benchmark_after_cutoff_rows": 0,
    }
    return trading, index, audit


def load_actions() -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    path = INPUT / "actions_pre2025_repaired_20261024.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    events: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[Any, ...]] = set()
    duplicates_removed = 0
    pay_dates_clamped = 0
    market_dates_clamped = 0
    missing_pay_dates = 0
    missing_market_dates = 0

    date_fields = (
        "dividPreNoticeDate",
        "dividAgmPumDate",
        "dividPlanAnnounceDate",
        "dividPlanDate",
        "dividRegistDate",
        "dividOperateDate",
        "dividPayDate",
        "dividStockMarketDate",
    )
    for key, rows in raw.items():
        symbol = key.split("/", 1)[0]
        for row in rows:
            for field in date_fields:
                if str(row.get(field) or "").strip():
                    parse_date(row[field])
            signature = (symbol,) + tuple(str(row.get(field) or "") for field in sorted(row))
            if signature in seen:
                duplicates_removed += 1
                continue
            seen.add(signature)

            before_tax = finite_float(row.get("dividCashPsBeforeTax"))
            stock_ratio = finite_float(row.get("dividStocksPs")) + finite_float(
                row.get("dividReserveToStockPs")
            )
            if before_tax < 0 or stock_ratio < 0:
                raise RuntimeError("Negative company-action amount")
            if before_tax == 0 and stock_ratio == 0:
                continue
            ex_date = parse_date(row.get("dividOperateDate"))
            if ex_date is None:
                raise RuntimeError(f"Economic company action lacks ex-date: {symbol}")
            pay_date = parse_date(row.get("dividPayDate"))
            market_date = parse_date(row.get("dividStockMarketDate"))
            if pay_date is not None and pay_date < ex_date:
                pay_date = ex_date
                pay_dates_clamped += 1
            if market_date is not None and market_date < ex_date:
                market_date = ex_date
                market_dates_clamped += 1
            if before_tax > 0 and pay_date is None:
                missing_pay_dates += 1
            if stock_ratio > 0 and market_date is None:
                missing_market_dates += 1
            events[symbol].append(
                {
                    "symbol": symbol,
                    "ex_date": ex_date,
                    "pay_date": pay_date,
                    "market_date": market_date,
                    "cash_before_tax": before_tax,
                    "cash_after_tax": parse_after_tax_cash(
                        row.get("dividCashPsAfterTax"), before_tax
                    ),
                    "stock_ratio": stock_ratio,
                }
            )

    for symbol in events:
        events[symbol].sort(key=lambda item: (item["ex_date"], item["pay_date"] or pd.Timestamp.max))
    audit = {
        "source": path.name,
        "source_sha256": sha256_file(path),
        "economic_events_after_exact_deduplication": sum(map(len, events.values())),
        "exact_duplicate_events_removed": duplicates_removed,
        "pay_dates_clamped_to_ex_date": pay_dates_clamped,
        "market_dates_clamped_to_ex_date": market_dates_clamped,
        "positive_cash_events_missing_pay_date": missing_pay_dates,
        "positive_stock_events_missing_market_date": missing_market_dates,
        "latest_ex_date": str(max(e["ex_date"] for rows in events.values() for e in rows).date()),
    }
    return events, audit


def read_raw_frame(path: Path, trading: pd.DatetimeIndex) -> pd.DataFrame:
    columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "amount",
        "adjustflag",
        "tradestatus",
        "pctChg",
        "isST",
    ]
    frame = pd.read_parquet(path, columns=columns)
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    if frame["date"].max() > CUTOFF or frame["date"].duplicated().any():
        raise RuntimeError(f"Raw date boundary or uniqueness failure: {path.name}")
    if set(frame["adjustflag"].astype(str).unique()) != {"3"}:
        raise RuntimeError(f"Unexpected adjustment flag: {path.name}")
    frame = frame.set_index("date").reindex(trading)
    return frame


def build_execution_dates(trading: pd.DatetimeIndex) -> list[pd.Timestamp]:
    research_days = trading[(trading >= RESEARCH_START) & (trading <= RESEARCH_END)]
    monthly = pd.Series(research_days, index=research_days).groupby(
        [research_days.year, research_days.month]
    ).first()
    q1 = research_days[research_days <= pd.Timestamp(CONFIG["q1_start_end"])]
    return sorted(set(pd.Timestamp(x) for x in monthly.tolist()) | set(pd.Timestamp(x) for x in q1))


def build_signals(
    trading: pd.DatetimeIndex,
    raw_paths: dict[str, Path],
    actions: dict[str, list[dict[str, Any]]],
) -> tuple[pd.DataFrame, dict[pd.Timestamp, list[str]], dict[pd.Timestamp, pd.Timestamp]]:
    execution_dates = build_execution_dates(trading)
    calendar_position = {date: idx for idx, date in enumerate(trading)}
    signal_to_execution: dict[pd.Timestamp, pd.Timestamp] = {}
    for execution in execution_dates:
        idx = calendar_position[execution]
        if idx == 0:
            raise RuntimeError("Execution date lacks a prior signal date")
        signal = trading[idx - 1]
        if signal in signal_to_execution and signal_to_execution[signal] != execution:
            raise RuntimeError("Signal date maps to multiple execution dates")
        signal_to_execution[signal] = execution

    signal_indices = {date: calendar_position[date] for date in signal_to_execution}
    action_lookup: dict[str, dict[pd.Timestamp, tuple[float, float]]] = {}
    for symbol, rows in actions.items():
        aggregated: dict[pd.Timestamp, list[float]] = defaultdict(lambda: [0.0, 0.0])
        for event in rows:
            aggregated[event["ex_date"]][0] += event["cash_before_tax"]
            aggregated[event["ex_date"]][1] += event["stock_ratio"]
        action_lookup[symbol] = {date: (vals[0], vals[1]) for date, vals in aggregated.items()}

    momentum_long = int(CONFIG["momentum_long_days"])
    momentum_skip = int(CONFIG["momentum_skip_days"])
    volatility_days = int(CONFIG["volatility_days"])
    liquidity_days = int(CONFIG["liquidity_days"])
    min_amount = float(CONFIG["minimum_median_amount_cny"])
    records: list[dict[str, Any]] = []

    for number, (symbol, path) in enumerate(sorted(raw_paths.items()), start=1):
        frame = read_raw_frame(path, trading)
        close_raw = pd.to_numeric(frame["close"], errors="coerce").to_numpy(float)
        present = np.isfinite(close_raw) & (close_raw > 0)
        if not present.any():
            continue
        first = int(np.flatnonzero(present)[0])
        last = int(np.flatnonzero(present)[-1])
        close_mark = pd.Series(close_raw).ffill().to_numpy(float)
        tri = np.full(len(trading), np.nan, dtype=float)
        tri[first] = 1.0
        previous_close = close_mark[first]
        previous_tri = 1.0
        symbol_actions = action_lookup.get(symbol, {})
        for idx in range(first + 1, last + 1):
            current_close = close_mark[idx]
            cash, stock = symbol_actions.get(trading[idx], (0.0, 0.0))
            ratio = (current_close * (1.0 + stock) + cash) / previous_close
            if not math.isfinite(ratio) or ratio <= 0:
                raise RuntimeError(f"Invalid total-return ratio for {symbol} at {trading[idx].date()}")
            previous_tri *= ratio
            tri[idx] = previous_tri
            previous_close = current_close
        log_tri = np.log(tri)
        daily_log_return = np.empty(len(trading), dtype=float)
        daily_log_return[:] = np.nan
        daily_log_return[first + 1 : last + 1] = np.diff(log_tri[first : last + 1])
        amount = pd.to_numeric(frame["amount"], errors="coerce").to_numpy(float)
        status = frame["tradestatus"].astype(str).to_numpy()
        is_st = frame["isST"].astype(str).to_numpy()

        for signal_date, idx in signal_indices.items():
            if idx - momentum_long < first or idx > last or not present[idx]:
                continue
            endpoints = (idx - momentum_skip, idx - momentum_long)
            if not all(math.isfinite(tri[pos]) and tri[pos] > 0 for pos in endpoints):
                continue
            if status[idx] != "1" or is_st[idx] != "0":
                continue
            liquidity_window = amount[idx - liquidity_days + 1 : idx + 1]
            if len(liquidity_window) != liquidity_days or not np.isfinite(liquidity_window).all():
                continue
            median_amount = float(np.median(liquidity_window))
            if median_amount < min_amount:
                continue
            volatility_window = daily_log_return[idx - volatility_days + 1 : idx + 1]
            if len(volatility_window) != volatility_days or not np.isfinite(volatility_window).all():
                continue
            momentum = float(log_tri[idx - momentum_skip] - log_tri[idx - momentum_long])
            volatility = float(np.std(volatility_window, ddof=1) * math.sqrt(252.0))
            records.append(
                {
                    "signal_date": signal_date,
                    "execution_date": signal_to_execution[signal_date],
                    "symbol": symbol,
                    "momentum_12_1_log": momentum,
                    "volatility_63_annualized": volatility,
                    "median_amount_20": median_amount,
                }
            )
        if number % 500 == 0:
            print(f"signal scan {number}/{len(raw_paths)}", flush=True)

    scores = pd.DataFrame.from_records(records)
    if scores.empty:
        raise RuntimeError("No eligible signal observations")
    ranked_parts: list[pd.DataFrame] = []
    for signal_date, group in scores.groupby("signal_date", sort=True):
        group = group.copy()
        group["momentum_percentile"] = group["momentum_12_1_log"].rank(
            method="average", pct=True, ascending=True
        )
        group["low_volatility_percentile"] = (-group["volatility_63_annualized"]).rank(
            method="average", pct=True, ascending=True
        )
        group["score"] = (
            float(CONFIG["score_momentum_weight"]) * group["momentum_percentile"]
            + float(CONFIG["score_low_volatility_weight"])
            * group["low_volatility_percentile"]
        )
        group = group.sort_values(["score", "symbol"], ascending=[False, True]).reset_index(drop=True)
        group["selection_rank"] = np.arange(1, len(group) + 1)
        group["selected"] = group["selection_rank"] <= int(CONFIG["slots"])
        group["eligible_count"] = len(group)
        ranked_parts.append(group)
    ranked = pd.concat(ranked_parts, ignore_index=True).sort_values(
        ["signal_date", "selection_rank"]
    )

    targets: dict[pd.Timestamp, list[str]] = {}
    selected = ranked[ranked["selected"]]
    for execution, group in selected.groupby("execution_date", sort=True):
        targets[pd.Timestamp(execution)] = group.sort_values("selection_rank")["symbol"].tolist()
    missing_targets = sorted(set(execution_dates) - set(targets))
    if missing_targets:
        raise RuntimeError(f"Execution dates without selections: {missing_targets[:5]}")
    return ranked, targets, signal_to_execution


def load_selected_market(
    selected_symbols: set[str], raw_paths: dict[str, Path], trading: pd.DatetimeIndex
) -> dict[str, pd.DataFrame]:
    market: dict[str, pd.DataFrame] = {}
    for symbol in sorted(selected_symbols):
        frame = read_raw_frame(raw_paths[symbol], trading)
        frame["close_mark"] = pd.to_numeric(frame["close"], errors="coerce").ffill()
        market[symbol] = frame
    return market


def is_one_price_limit(row: pd.Series, side: str) -> bool:
    try:
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        pct = float(row["pctChg"])
    except (TypeError, ValueError):
        return True
    if not all(math.isfinite(x) for x in (open_price, high, low, pct)):
        return True
    same = math.isclose(open_price, high, rel_tol=0.0, abs_tol=1e-8) and math.isclose(
        open_price, low, rel_tol=0.0, abs_tol=1e-8
    )
    threshold = (
        float(CONFIG["st_one_price_limit_threshold_pct"])
        if str(row.get("isST")) == "1"
        else float(CONFIG["non_st_one_price_limit_threshold_pct"])
    )
    if side == "buy":
        return same and pct >= threshold
    return same and pct <= -threshold


def can_trade(frame: pd.DataFrame, date: pd.Timestamp, side: str) -> bool:
    row = frame.loc[date]
    try:
        valid = (
            str(row["tradestatus"]) == "1"
            and math.isfinite(float(row["open"]))
            and float(row["open"]) > 0
        )
    except (TypeError, ValueError):
        return False
    return valid and not is_one_price_limit(row, side)


def trade_cost(gross: float, side: str, fee_multiplier: float) -> tuple[float, float, float]:
    commission = max(
        float(CONFIG["base_minimum_commission_cny"]) * fee_multiplier,
        gross * float(CONFIG["base_commission_rate_each_side"]) * fee_multiplier,
    )
    transfer = gross * float(CONFIG["base_transfer_handling_rate_each_side"]) * fee_multiplier
    stamp = gross * float(CONFIG["sell_stamp_duty_rate"]) if side == "sell" else 0.0
    return commission, transfer, stamp


def metric_block(strategy_returns: pd.Series, benchmark_returns: pd.Series) -> dict[str, float]:
    strategy = pd.Series(strategy_returns, dtype=float).dropna()
    benchmark = pd.Series(benchmark_returns, dtype=float).reindex(strategy.index)
    if strategy.empty or benchmark.isna().any():
        raise RuntimeError("Metric input is empty or misaligned")
    n = len(strategy)
    strategy_growth = float(np.prod(1.0 + strategy.to_numpy()))
    benchmark_growth = float(np.prod(1.0 + benchmark.to_numpy()))
    annualization = float(CONFIG["annualization_trading_days"]) / n
    strategy_cagr = strategy_growth**annualization - 1.0
    benchmark_cagr = benchmark_growth**annualization - 1.0
    active_cagr = (strategy_growth / benchmark_growth) ** annualization - 1.0
    curve = np.concatenate([[1.0], np.cumprod(1.0 + strategy.to_numpy())])
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    std = float(strategy.std(ddof=1))
    sharpe = (
        float(strategy.mean()) / std * math.sqrt(float(CONFIG["annualization_trading_days"]))
        if std > 0
        else float("nan")
    )
    years = strategy.index.year
    annual_returns = pd.Series(strategy.to_numpy(), index=strategy.index).groupby(years).apply(
        lambda values: float(np.prod(1.0 + values.to_numpy()) - 1.0)
    )
    return {
        "trading_days": n,
        "strategy_growth": strategy_growth,
        "benchmark_growth": benchmark_growth,
        "strategy_period_return": strategy_growth - 1.0,
        "benchmark_period_return": benchmark_growth - 1.0,
        "period_excess_difference": strategy_growth - benchmark_growth,
        "strategy_cagr": strategy_cagr,
        "benchmark_cagr": benchmark_cagr,
        "annualized_excess_difference": strategy_cagr - benchmark_cagr,
        "geometric_active_cagr": active_cagr,
        "mean_calendar_return": float(annual_returns.mean()),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
    }


def simulate(
    start_date: pd.Timestamp,
    fee_multiplier: float,
    trading: pd.DatetimeIndex,
    benchmark: pd.DataFrame,
    market: dict[str, pd.DataFrame],
    actions: dict[str, list[dict[str, Any]]],
    targets_by_execution: dict[pd.Timestamp, list[str]],
    out_dates: dict[str, pd.Timestamp | None],
) -> dict[str, pd.DataFrame]:
    start_date = pd.Timestamp(start_date)
    end_date = RESEARCH_END
    dates = trading[(trading >= start_date) & (trading <= end_date)]
    first_month_dates = set(
        pd.Series(trading[(trading >= RESEARCH_START) & (trading <= RESEARCH_END)])
        .groupby([trading[(trading >= RESEARCH_START) & (trading <= RESEARCH_END)].year,
                  trading[(trading >= RESEARCH_START) & (trading <= RESEARCH_END)].month])
        .first()
        .tolist()
    )
    rebalance_dates = {start_date} | {pd.Timestamp(x) for x in first_month_dates if x > start_date}

    events_by_ex: dict[pd.Timestamp, list[dict[str, Any]]] = defaultdict(list)
    for symbol in market:
        for event in actions.get(symbol, []):
            if start_date <= event["ex_date"] <= end_date:
                events_by_ex[event["ex_date"]].append(event)

    delist_effective: dict[pd.Timestamp, list[str]] = defaultdict(list)
    for symbol, out_date in out_dates.items():
        if symbol not in market or out_date is None or out_date < start_date or out_date > end_date:
            continue
        pos = int(trading.searchsorted(out_date, side="left"))
        if pos < len(trading) and trading[pos] <= end_date:
            delist_effective[trading[pos]].append(symbol)

    cash = float(CONFIG["initial_cash_cny"])
    initial_cash = cash
    tradable: dict[str, float] = defaultdict(float)
    pending: list[dict[str, Any]] = []
    receivables: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    previous_nav = initial_cash
    benchmark_nav = 1.0

    def pending_shares(symbol: str) -> float:
        return sum(item["shares"] for item in pending if item["symbol"] == symbol)

    def total_shares(symbol: str) -> float:
        return tradable.get(symbol, 0.0) + pending_shares(symbol)

    def mark_price(symbol: str, date: pd.Timestamp, field: str) -> float:
        frame = market[symbol]
        row = frame.loc[date]
        candidate = row[field]
        if pd.notna(candidate) and finite_float(candidate) > 0:
            return float(candidate)
        marked = row["close_mark"]
        return float(marked) if pd.notna(marked) and float(marked) > 0 else 0.0

    def portfolio_components(date: pd.Timestamp, field: str) -> tuple[float, float, float]:
        symbols = set(tradable) | {item["symbol"] for item in pending}
        holdings_value = sum(total_shares(symbol) * mark_price(symbol, date, field) for symbol in symbols)
        pending_value = sum(
            item["shares"] * mark_price(item["symbol"], date, field) for item in pending
        )
        receivable_value = sum(item["amount"] for item in receivables)
        return holdings_value, pending_value, receivable_value

    def append_trade(
        date: pd.Timestamp,
        symbol: str,
        side: str,
        shares: float,
        reason: str,
    ) -> float:
        nonlocal cash
        raw_open = float(market[symbol].loc[date, "open"])
        slip = float(CONFIG["base_slippage_rate_each_side"]) * fee_multiplier
        execution_price = raw_open * (1.0 + slip if side == "buy" else 1.0 - slip)
        gross = shares * execution_price
        commission, transfer, stamp = trade_cost(gross, side, fee_multiplier)
        if side == "buy":
            total_cost = gross + commission + transfer
            if total_cost > cash + 1e-7:
                raise RuntimeError("Buy order exceeded available cash")
            cash -= total_cost
            tradable[symbol] += shares
            cash_change = -total_cost
        else:
            if shares > tradable.get(symbol, 0.0) + 1e-7:
                raise RuntimeError("Sell order exceeded tradable shares")
            proceeds = gross - commission - transfer - stamp
            cash += proceeds
            tradable[symbol] -= shares
            if abs(tradable[symbol]) < 1e-8:
                tradable[symbol] = 0.0
            cash_change = proceeds
        trade_rows.append(
            {
                "start_date": start_date,
                "date": date,
                "fee_multiplier": fee_multiplier,
                "symbol": symbol,
                "side": side,
                "shares": shares,
                "raw_open": raw_open,
                "execution_price": execution_price,
                "gross_value": gross,
                "slippage_cost": abs(execution_price - raw_open) * shares,
                "commission": commission,
                "transfer_handling": transfer,
                "stamp_duty": stamp,
                "cash_change": cash_change,
                "reason": reason,
            }
        )
        return cash_change

    for date_idx, date in enumerate(dates):
        # Previously declared shares become tradable before the open.
        remaining_pending: list[dict[str, Any]] = []
        for item in pending:
            if item["market_date"] is not None and item["market_date"] <= date:
                tradable[item["symbol"]] += item["shares"]
                action_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": item["symbol"],
                        "event": "stock_shares_released",
                        "shares": item["shares"],
                        "amount": 0.0,
                    }
                )
            else:
                remaining_pending.append(item)
        pending = remaining_pending

        # Entitlements use shares owned before today's trading.
        for event in events_by_ex.get(date, []):
            symbol = event["symbol"]
            eligible = total_shares(symbol)
            if eligible <= 0:
                continue
            if event["cash_after_tax"] > 0:
                amount = eligible * event["cash_after_tax"]
                receivables.append(
                    {"symbol": symbol, "amount": amount, "pay_date": event["pay_date"]}
                )
                action_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": symbol,
                        "event": "cash_dividend_receivable",
                        "shares": eligible,
                        "amount": amount,
                    }
                )
            if event["stock_ratio"] > 0:
                new_shares = eligible * event["stock_ratio"]
                if event["market_date"] is not None and event["market_date"] <= date:
                    tradable[symbol] += new_shares
                    event_name = "stock_dividend_immediately_tradable"
                else:
                    pending.append(
                        {
                            "symbol": symbol,
                            "shares": new_shares,
                            "market_date": event["market_date"],
                        }
                    )
                    event_name = "stock_dividend_pending"
                action_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": symbol,
                        "event": event_name,
                        "shares": new_shares,
                        "amount": 0.0,
                    }
                )

        # Forced delisting orders happen before any scheduled rebalance.
        for symbol in sorted(delist_effective.get(date, [])):
            shares = tradable.get(symbol, 0.0)
            if shares > 0 and can_trade(market[symbol], date, "sell"):
                append_trade(date, symbol, "sell", shares, "forced_delisting")

        if date in rebalance_dates:
            targets = [
                symbol
                for symbol in targets_by_execution[date]
                if out_dates.get(symbol) is None or out_dates[symbol] > date
            ]
            target_set = set(targets)
            holdings_value_open, _, receivable_value = portfolio_components(date, "open")
            nav_open = cash + receivable_value + holdings_value_open
            slot_value = nav_open / float(CONFIG["slots"])
            desired_shares: dict[str, float] = {}
            lot = int(CONFIG["lot_size"])
            slip = float(CONFIG["base_slippage_rate_each_side"]) * fee_multiplier
            for symbol in targets:
                price = mark_price(symbol, date, "open")
                if price <= 0:
                    desired_shares[symbol] = total_shares(symbol)
                else:
                    desired_shares[symbol] = math.floor(slot_value / (price * (1.0 + slip)) / lot) * lot

            current_symbols = sorted(
                {symbol for symbol, shares in tradable.items() if shares > 1e-8}
                | {item["symbol"] for item in pending if item["shares"] > 1e-8}
            )
            for symbol in current_symbols:
                total = total_shares(symbol)
                desired = desired_shares.get(symbol, 0.0)
                if symbol not in target_set or desired <= 0:
                    sell_shares = tradable.get(symbol, 0.0)
                    reason = "rebalance_exit"
                else:
                    excess = max(0.0, total - desired)
                    sell_shares = min(
                        tradable.get(symbol, 0.0), math.floor((excess + 1e-9) / lot) * lot
                    )
                    reason = "rebalance_reduce"
                if sell_shares > 1e-8 and can_trade(market[symbol], date, "sell"):
                    append_trade(date, symbol, "sell", sell_shares, reason)

            ideal_lots: dict[str, int] = {}
            for symbol in targets:
                deficit = max(0.0, desired_shares[symbol] - total_shares(symbol))
                lots = int(math.floor((deficit + 1e-9) / lot))
                if lots > 0 and can_trade(market[symbol], date, "buy"):
                    ideal_lots[symbol] = lots

            def planned_cost(symbol: str, lots: int) -> float:
                if lots <= 0:
                    return 0.0
                raw_open = float(market[symbol].loc[date, "open"])
                execution_price = raw_open * (1.0 + slip)
                gross = lots * lot * execution_price
                commission, transfer, _ = trade_cost(gross, "buy", fee_multiplier)
                return gross + commission + transfer

            total_ideal_cost = sum(planned_cost(symbol, lots) for symbol, lots in ideal_lots.items())
            if total_ideal_cost <= cash + 1e-8:
                planned = dict(ideal_lots)
            elif total_ideal_cost > 0:
                scale = max(0.0, cash / total_ideal_cost)
                planned = {symbol: int(math.floor(lots * scale)) for symbol, lots in ideal_lots.items()}
                while sum(planned_cost(s, n) for s, n in planned.items()) > cash + 1e-8:
                    reducible = [s for s, n in planned.items() if n > 0]
                    if not reducible:
                        break
                    symbol = max(reducible, key=lambda s: (planned_cost(s, planned[s]), s))
                    planned[symbol] -= 1
                for _ in range(len(ideal_lots) * 3):
                    current_cost = sum(planned_cost(s, n) for s, n in planned.items())
                    candidates = []
                    for symbol, ideal in ideal_lots.items():
                        if planned.get(symbol, 0) >= ideal:
                            continue
                        incremental = planned_cost(symbol, planned.get(symbol, 0) + 1) - planned_cost(
                            symbol, planned.get(symbol, 0)
                        )
                        completion_gap = 1.0 - planned.get(symbol, 0) / ideal
                        if current_cost + incremental <= cash + 1e-8:
                            candidates.append((completion_gap, symbol))
                    if not candidates:
                        break
                    _, chosen = max(candidates, key=lambda item: (item[0], -int(item[1][:6])))
                    planned[chosen] = planned.get(chosen, 0) + 1
            else:
                planned = {}

            for symbol in sorted(planned):
                shares = planned[symbol] * lot
                if shares > 0:
                    append_trade(date, symbol, "buy", shares, "rebalance_buy")

            snapshot_symbols = sorted(
                {symbol for symbol, shares in tradable.items() if shares > 1e-8}
                | {item["symbol"] for item in pending if item["shares"] > 1e-8}
            )
            for symbol in snapshot_symbols:
                price = mark_price(symbol, date, "open")
                position_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": symbol,
                        "tradable_shares": tradable.get(symbol, 0.0),
                        "pending_shares": pending_shares(symbol),
                        "mark_open": price,
                        "market_value_open": total_shares(symbol) * price,
                        "is_target": symbol in target_set,
                        "cash_after_rebalance": cash,
                        "receivables_at_open": sum(item["amount"] for item in receivables),
                    }
                )

        # Untradeable residual units are conservatively written off at delisting.
        for symbol in sorted(delist_effective.get(date, [])):
            residual = total_shares(symbol)
            if residual > 1e-8:
                writeoff = residual * mark_price(symbol, date, "close_mark")
                tradable[symbol] = 0.0
                pending = [item for item in pending if item["symbol"] != symbol]
                action_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": symbol,
                        "event": "delisting_residual_writeoff",
                        "shares": residual,
                        "amount": -writeoff,
                    }
                )

        # Cash becomes spendable only after today's close.
        remaining_receivables: list[dict[str, Any]] = []
        paid_today = 0.0
        for item in receivables:
            if item["pay_date"] is not None and item["pay_date"] <= date:
                cash += item["amount"]
                paid_today += item["amount"]
                action_rows.append(
                    {
                        "start_date": start_date,
                        "date": date,
                        "fee_multiplier": fee_multiplier,
                        "symbol": item["symbol"],
                        "event": "cash_dividend_paid",
                        "shares": 0.0,
                        "amount": item["amount"],
                    }
                )
            else:
                remaining_receivables.append(item)
        receivables = remaining_receivables

        holdings_value, pending_value, receivable_value = portfolio_components(date, "close_mark")
        nav = cash + receivable_value + holdings_value
        strategy_return = nav / previous_nav - 1.0
        previous_nav = nav
        index_row = benchmark.loc[date]
        if date_idx == 0:
            benchmark_return = float(index_row["close"] / index_row["open"] - 1.0)
        else:
            prior_close = float(benchmark.loc[dates[date_idx - 1], "close"])
            benchmark_return = float(index_row["close"] / prior_close - 1.0)
        benchmark_nav *= 1.0 + benchmark_return
        daily_rows.append(
            {
                "start_date": start_date,
                "date": date,
                "fee_multiplier": fee_multiplier,
                "nav": nav,
                "cash": cash,
                "receivables": receivable_value,
                "holdings_value": holdings_value,
                "pending_stock_value": pending_value,
                "paid_cash_dividends_today": paid_today,
                "positions": sum(total_shares(symbol) > 1e-8 for symbol in market),
                "strategy_return": strategy_return,
                "benchmark_return": benchmark_return,
                "benchmark_nav": benchmark_nav,
            }
        )

    return {
        "daily": pd.DataFrame(daily_rows),
        "trades": pd.DataFrame(trade_rows),
        "actions": pd.DataFrame(action_rows),
        "positions": pd.DataFrame(position_rows),
    }


def compute_reports(main_daily: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    daily = main_daily.copy().set_index("date")
    period_rows: list[dict[str, Any]] = []
    for name, first_year, last_year in (
        ("2016-2019", 2016, 2019),
        ("2020-2024", 2020, 2024),
        ("2016-2024", 2016, 2024),
    ):
        subset = daily[(daily.index.year >= first_year) & (daily.index.year <= last_year)]
        metrics = metric_block(subset["strategy_return"], subset["benchmark_return"])
        period_rows.append({"period": name, **metrics})

    yearly_rows: list[dict[str, Any]] = []
    for year, subset in daily.groupby(daily.index.year):
        metrics = metric_block(subset["strategy_return"], subset["benchmark_return"])
        yearly_rows.append({"year": int(year), **metrics})
    yearly = pd.DataFrame(yearly_rows)

    loo_rows: list[dict[str, Any]] = []
    for omitted in sorted(yearly["year"].tolist()):
        subset = daily[daily.index.year != omitted]
        metrics = metric_block(subset["strategy_return"], subset["benchmark_return"])
        loo_rows.append({"omitted_year": int(omitted), **metrics})
    return pd.DataFrame(period_rows), yearly, pd.DataFrame(loo_rows)


def markdown_percent(value: float) -> str:
    return "nan" if not math.isfinite(float(value)) else f"{100.0 * float(value):.2f}%"


def write_results_markdown(
    period_metrics: pd.DataFrame,
    yearly_metrics: pd.DataFrame,
    q1_metrics: pd.DataFrame,
    loo_metrics: pd.DataFrame,
    fee_metrics: pd.DataFrame,
    diagnostics: dict[str, Any],
    gate: dict[str, Any],
) -> None:
    lines = [
        "# 单一固定公式一次性评估结果",
        "",
        f"严格迁移判定：**{'通过' if gate['passed'] else '失败'}**。公式和常数未在结果后改动，也未进行第二次评估。",
        "",
        "## 分段",
        "",
        "| 区间 | CAGR | 上证 CAGR | 年化超额差 | 几何主动 CAGR | 平均年度收益 | 最大回撤 | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in period_metrics.iterrows():
        lines.append(
            "| {period} | {s} | {b} | {e} | {a} | {m} | {d} | {h:.3f} |".format(
                period=row["period"],
                s=markdown_percent(row["strategy_cagr"]),
                b=markdown_percent(row["benchmark_cagr"]),
                e=markdown_percent(row["annualized_excess_difference"]),
                a=markdown_percent(row["geometric_active_cagr"]),
                m=markdown_percent(row["mean_calendar_return"]),
                d=markdown_percent(row["max_drawdown"]),
                h=row["sharpe"],
            )
        )
    lines += [
        "",
        "## 逐年",
        "",
        "| 年份 | 策略收益 | 上证收益 | 超额 | 最大回撤 | Sharpe |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in yearly_metrics.iterrows():
        lines.append(
            f"| {int(row['year'])} | {markdown_percent(row['strategy_period_return'])} | "
            f"{markdown_percent(row['benchmark_period_return'])} | "
            f"{markdown_percent(row['period_excess_difference'])} | "
            f"{markdown_percent(row['max_drawdown'])} | {row['sharpe']:.3f} |"
        )
    lines += [
        "",
        "## 稳定性摘要",
        "",
        f"- 逐年超额下限：{markdown_percent(diagnostics['minimum_calendar_year_excess'])}",
        f"- 策略年度收益跨年样本标准差：{markdown_percent(diagnostics['strategy_calendar_return_std'])}",
        f"- 年度超额跨年样本标准差：{markdown_percent(diagnostics['calendar_excess_std'])}",
        f"- Q1 起点数：{len(q1_metrics)}；年化超额最小/中位/最大："
        f"{markdown_percent(q1_metrics['annualized_excess_difference'].min())} / "
        f"{markdown_percent(q1_metrics['annualized_excess_difference'].median())} / "
        f"{markdown_percent(q1_metrics['annualized_excess_difference'].max())}",
        f"- Leave-one-year-out 年化超额最小/最大："
        f"{markdown_percent(loo_metrics['annualized_excess_difference'].min())} / "
        f"{markdown_percent(loo_metrics['annualized_excess_difference'].max())}",
        "",
        "## 费用压力",
        "",
        "| 非税成本倍数 | CAGR | 年化超额 | 最大回撤 | Sharpe |",
        "|---:|---:|---:|---:|---:|",
    ]
    for _, row in fee_metrics.iterrows():
        lines.append(
            f"| {row['fee_multiplier']:.0f}x | {markdown_percent(row['strategy_cagr'])} | "
            f"{markdown_percent(row['annualized_excess_difference'])} | "
            f"{markdown_percent(row['max_drawdown'])} | {row['sharpe']:.3f} |"
        )
    lines += ["", "## 冻结判定明细", ""]
    for name, passed in gate["conditions"].items():
        lines.append(f"- {'通过' if passed else '失败'}：`{name}`")
    lines += [
        "",
        "所有逐起点、逐日、逐笔交易、公司行动、持仓快照和哈希位于同目录结构化文件中。",
        "",
    ]
    (HERE / "RESULTS.md").write_text("\n".join(lines), encoding="utf-8")


def self_test() -> None:
    assert parse_after_tax_cash("0.09 or 0.10", 0.12) == 0.09
    assert math.isclose(parse_after_tax_cash("", 0.10), 0.08)
    dates = pd.date_range("2019-01-01", periods=5, freq="D")
    strategy = pd.Series([0.01, -0.02, 0.03, 0.00, 0.01], index=dates)
    benchmark = pd.Series([0.00, -0.01, 0.01, 0.00, 0.00], index=dates)
    metrics = metric_block(strategy, benchmark)
    assert metrics["trading_days"] == 5
    assert math.isfinite(metrics["strategy_cagr"])
    c, t, s = trade_cost(10000.0, "sell", 1.0)
    assert c == 5.0 and t > 0 and s > 0
    synthetic_days = pd.bdate_range(end="2024-12-31", periods=8)
    symbol = "600000.SH"
    synthetic_market = pd.DataFrame(
        {
            "open": [10.0] * len(synthetic_days),
            "high": [10.2] * len(synthetic_days),
            "low": [9.8] * len(synthetic_days),
            "close": [10.0] * len(synthetic_days),
            "amount": [100_000_000.0] * len(synthetic_days),
            "adjustflag": ["3"] * len(synthetic_days),
            "tradestatus": ["1"] * len(synthetic_days),
            "pctChg": [0.0] * len(synthetic_days),
            "isST": ["0"] * len(synthetic_days),
            "close_mark": [10.0] * len(synthetic_days),
        },
        index=synthetic_days,
    )
    synthetic_benchmark = pd.DataFrame(
        {"open": [3000.0] * len(synthetic_days), "close": [3000.0] * len(synthetic_days)},
        index=synthetic_days,
    )
    ex_date = synthetic_days[3]
    synthetic_actions = {
        symbol: [
            {
                "symbol": symbol,
                "ex_date": ex_date,
                "pay_date": ex_date,
                "market_date": ex_date,
                "cash_before_tax": 0.10,
                "cash_after_tax": 0.08,
                "stock_ratio": 0.10,
            }
        ]
    }
    synthetic_result = simulate(
        synthetic_days[0],
        1.0,
        synthetic_days,
        synthetic_benchmark,
        {symbol: synthetic_market},
        synthetic_actions,
        {synthetic_days[0]: [symbol]},
        {symbol: None},
    )
    assert len(synthetic_result["daily"]) == len(synthetic_days)
    assert not synthetic_result["trades"].empty
    assert (synthetic_result["actions"]["event"] == "cash_dividend_paid").any()
    print(json.dumps({"self_test": "passed", "uses_whitelist_market_data": False}))


def execute_once() -> None:
    if START_MARKER.exists() or COMPLETE_MARKER.exists() or FAILED_MARKER.exists():
        raise RuntimeError("This frozen evaluation has already started; rerun is forbidden")
    lock = verify_freeze()
    write_json(
        START_MARKER,
        {
            "status": "started",
            "started_at_utc": utc_now(),
            "lock_sha256": sha256_file(LOCK_PATH),
            "planned_evaluation_runs": 1,
        },
    )
    log_lines = ["Frozen hash verification passed."]

    manifest, raw_paths = load_manifest_and_verify_raw()
    out_dates, universe_audit = load_universe(set(raw_paths))
    trading, benchmark, calendar_audit = load_calendar_and_index()
    actions, action_audit = load_actions()
    input_audit = {
        "instruction_boundary_version": CONFIG["instruction_boundary_version"],
        "cutoff": CONFIG["cutoff"],
        "manifest_sha256": sha256_file(INPUT / "PUBLIC_INPUT_MANIFEST.json"),
        "manifest_symbols_total": int(manifest["symbols_total"]),
        "manifest_symbols_with_rows": int(manifest["symbols_with_rows"]),
        "raw_hashes_verified_before_performance": len(raw_paths),
        "universe": universe_audit,
        "calendar_and_benchmark": calendar_audit,
        "company_actions": action_audit,
    }
    write_json(HERE / "INPUT_AUDIT_BEFORE_PERFORMANCE.json", input_audit)
    log_lines.append("All raw hashes and cutoff assertions passed before performance calculation.")

    ranked, targets, signal_to_execution = build_signals(trading, raw_paths, actions)
    ranked.to_parquet(HERE / "all_signal_scores.parquet", index=False)
    selections = ranked[ranked["selected"]].copy()
    selections.to_csv(HERE / "selections.csv", index=False)
    selected_symbols = set(selections["symbol"])
    market = load_selected_market(selected_symbols, raw_paths, trading)
    log_lines.append(
        f"Signals frozen in-run: {len(signal_to_execution)} dates, {len(selected_symbols)} unique selected symbols."
    )

    research_days = trading[(trading >= RESEARCH_START) & (trading <= RESEARCH_END)]
    main_start = research_days[0]
    main = simulate(
        main_start,
        1.0,
        trading,
        benchmark,
        market,
        actions,
        targets,
        out_dates,
    )
    main["daily"].to_csv(HERE / "main_daily_nav.csv", index=False)
    main["trades"].to_csv(HERE / "main_trades.csv", index=False)
    main["actions"].to_csv(HERE / "main_company_actions.csv", index=False)
    main["positions"].to_csv(HERE / "main_rebalance_positions.csv", index=False)

    period_metrics, yearly_metrics, loo_metrics = compute_reports(main["daily"])
    period_metrics.to_csv(HERE / "period_metrics.csv", index=False)
    yearly_metrics.to_csv(HERE / "yearly_metrics.csv", index=False)
    loo_metrics.to_csv(HERE / "leave_one_year_out_metrics.csv", index=False)

    q1_starts = research_days[research_days <= pd.Timestamp(CONFIG["q1_start_end"])]
    q1_metric_rows: list[dict[str, Any]] = []
    q1_daily_parts: list[pd.DataFrame] = []
    q1_trade_parts: list[pd.DataFrame] = []
    q1_action_parts: list[pd.DataFrame] = []
    q1_position_parts: list[pd.DataFrame] = []
    for number, start in enumerate(q1_starts, start=1):
        result = main if start == main_start else simulate(
            start,
            1.0,
            trading,
            benchmark,
            market,
            actions,
            targets,
            out_dates,
        )
        daily_indexed = result["daily"].set_index("date")
        metrics = metric_block(daily_indexed["strategy_return"], daily_indexed["benchmark_return"])
        q1_metric_rows.append({"start_date": start, **metrics})
        q1_daily_parts.append(result["daily"])
        q1_trade_parts.append(result["trades"])
        q1_action_parts.append(result["actions"])
        q1_position_parts.append(result["positions"])
        if number % 10 == 0:
            print(f"Q1 start simulation {number}/{len(q1_starts)}", flush=True)
    q1_metrics = pd.DataFrame(q1_metric_rows)
    q1_metrics.to_csv(HERE / "q1_all_trading_day_start_metrics.csv", index=False)
    pd.concat(q1_daily_parts, ignore_index=True).to_parquet(
        HERE / "q1_all_start_daily_nav.parquet", index=False
    )
    pd.concat(q1_trade_parts, ignore_index=True).to_parquet(
        HERE / "q1_all_start_trades.parquet", index=False
    )
    pd.concat(q1_action_parts, ignore_index=True).to_parquet(
        HERE / "q1_all_start_company_actions.parquet", index=False
    )
    pd.concat(q1_position_parts, ignore_index=True).to_parquet(
        HERE / "q1_all_start_rebalance_positions.parquet", index=False
    )

    fee_metric_rows: list[dict[str, Any]] = []
    fee_daily_parts: list[pd.DataFrame] = []
    fee_trade_parts: list[pd.DataFrame] = []
    fee_action_parts: list[pd.DataFrame] = []
    fee_position_parts: list[pd.DataFrame] = []
    for multiplier in CONFIG["fee_stress_multipliers"]:
        multiplier = float(multiplier)
        result = main if multiplier == 1.0 else simulate(
            main_start,
            multiplier,
            trading,
            benchmark,
            market,
            actions,
            targets,
            out_dates,
        )
        daily_indexed = result["daily"].set_index("date")
        metrics = metric_block(daily_indexed["strategy_return"], daily_indexed["benchmark_return"])
        fee_metric_rows.append({"fee_multiplier": multiplier, **metrics})
        fee_daily_parts.append(result["daily"])
        fee_trade_parts.append(result["trades"])
        fee_action_parts.append(result["actions"])
        fee_position_parts.append(result["positions"])
    fee_metrics = pd.DataFrame(fee_metric_rows)
    fee_metrics.to_csv(HERE / "fee_stress_metrics.csv", index=False)
    pd.concat(fee_daily_parts, ignore_index=True).to_parquet(
        HERE / "fee_stress_daily_nav.parquet", index=False
    )
    pd.concat(fee_trade_parts, ignore_index=True).to_parquet(
        HERE / "fee_stress_trades.parquet", index=False
    )
    pd.concat(fee_action_parts, ignore_index=True).to_parquet(
        HERE / "fee_stress_company_actions.parquet", index=False
    )
    pd.concat(fee_position_parts, ignore_index=True).to_parquet(
        HERE / "fee_stress_rebalance_positions.parquet", index=False
    )

    annual_excess = yearly_metrics["period_excess_difference"]
    diagnostics = {
        "minimum_calendar_year_excess": float(annual_excess.min()),
        "strategy_calendar_return_std": float(yearly_metrics["strategy_period_return"].std(ddof=1)),
        "calendar_excess_std": float(annual_excess.std(ddof=1)),
        "q1_start_count": len(q1_metrics),
        "q1_excess_min": float(q1_metrics["annualized_excess_difference"].min()),
        "q1_excess_median": float(q1_metrics["annualized_excess_difference"].median()),
        "q1_excess_max": float(q1_metrics["annualized_excess_difference"].max()),
        "loo_excess_min": float(loo_metrics["annualized_excess_difference"].min()),
        "loo_excess_max": float(loo_metrics["annualized_excess_difference"].max()),
    }
    write_json(HERE / "stability_diagnostics.json", diagnostics)

    period_indexed = period_metrics.set_index("period")
    conditions = {
        "positive_excess_cagr_2016_2024": bool(
            period_indexed.loc["2016-2024", "annualized_excess_difference"] > 0
        ),
        "positive_excess_cagr_2016_2019": bool(
            period_indexed.loc["2016-2019", "annualized_excess_difference"] > 0
        ),
        "positive_excess_cagr_2020_2024": bool(
            period_indexed.loc["2020-2024", "annualized_excess_difference"] > 0
        ),
        "minimum_calendar_year_excess_nonnegative": bool(annual_excess.min() >= 0),
        "all_q1_start_excess_cagr_positive": bool(
            (q1_metrics["annualized_excess_difference"] > 0).all()
        ),
        "all_leave_one_year_out_excess_cagr_positive": bool(
            (loo_metrics["annualized_excess_difference"] > 0).all()
        ),
        "three_x_fee_excess_cagr_positive": bool(
            fee_metrics.loc[
                fee_metrics["fee_multiplier"] == 3.0, "annualized_excess_difference"
            ].iloc[0]
            > 0
        ),
        "full_period_sharpe_positive": bool(period_indexed.loc["2016-2024", "sharpe"] > 0),
    }
    gate = {"passed": bool(all(conditions.values())), "conditions": conditions}
    write_json(HERE / "STRICT_TRANSFER_GATE.json", gate)
    write_results_markdown(
        period_metrics,
        yearly_metrics,
        q1_metrics,
        loo_metrics,
        fee_metrics,
        diagnostics,
        gate,
    )
    failure_lines = [
        "# 冻结候选失败结论" if not gate["passed"] else "# 冻结候选判定结论",
        "",
        (
            "该候选未通过预登记的严格跨年迁移门槛。失败项如下；按协议不改公式、不重试参数、不删除年份。"
            if not gate["passed"]
            else "该候选通过预登记的严格跨年迁移门槛。"
        ),
        "",
    ]
    failed = [name for name, passed in conditions.items() if not passed]
    if failed:
        failure_lines.extend(f"- {name}" for name in failed)
    else:
        failure_lines.append("- 无失败项。")
    failure_lines.append("")
    (HERE / "FAILURE_CONCLUSION.md").write_text("\n".join(failure_lines), encoding="utf-8")

    log_lines.append("The single preregistered evaluation completed.")
    (HERE / "evaluation.log").write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    summary = {
        "status": "completed",
        "strict_transfer_gate_passed": gate["passed"],
        "period_metrics": period_metrics.to_dict(orient="records"),
        "stability_diagnostics": diagnostics,
        "fee_stress_metrics": fee_metrics.to_dict(orient="records"),
        "evaluation_runs_executed": 1,
        "formula_changed_after_results": False,
    }
    write_json(HERE / "SUMMARY.json", summary)
    write_json(
        COMPLETE_MARKER,
        {
            "status": "completed",
            "completed_at_utc": utc_now(),
            "evaluation_runs_executed": 1,
            "strict_transfer_gate_passed": gate["passed"],
            "formula_changed_after_results": False,
        },
    )
    output_hashes = {}
    for path in sorted(HERE.iterdir()):
        if path.is_file() and path.name != "OUTPUT_MANIFEST_SHA256.json":
            output_hashes[path.name] = sha256_file(path)
    write_json(HERE / "OUTPUT_MANIFEST_SHA256.json", output_hashes)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--execute-frozen", action="store_true")
    args = parser.parse_args()
    if args.self_test == args.execute_frozen:
        parser.error("Choose exactly one of --self-test or --execute-frozen")
    if args.self_test:
        self_test()
        return
    try:
        execute_once()
    except Exception as exc:
        write_json(
            FAILED_MARKER,
            {
                "status": "failed",
                "failed_at_utc": utc_now(),
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "rerun_forbidden": True,
            },
        )
        raise


if __name__ == "__main__":
    main()
