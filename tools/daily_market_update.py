"""Transactional BaoStock updater for the protected main-board and STAR data sets."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import socket
import sys
import time
import zlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import baostock as bs
import baostock.util.socketutil as bs_socket
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FIELDS = (
    "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,"
    "tradestatus,pctChg,isST"
)
PRICE_COLUMNS = ["open", "high", "low", "close", "preclose"]
FLOAT_COLUMNS = PRICE_COLUMNS + ["amount", "turn", "pctChg"]
STRING_COLUMNS = ["code", "adjustflag", "tradestatus", "isST", "symbol", "board"]


def install_baostock_socket_safety() -> None:
    """Prevent BaoStock's client from spinning forever after a closed socket."""

    def safe_connect(self) -> None:
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(45)
        connection.connect((bs_socket.cons.BAOSTOCK_SERVER_IP, bs_socket.cons.BAOSTOCK_SERVER_PORT))
        setattr(bs_socket.context, "default_socket", connection)

    def safe_send(message: str):
        connection = getattr(bs_socket.context, "default_socket", None)
        if connection is None:
            return None
        try:
            connection.sendall(bytes(message + "\n", encoding="utf-8"))
            received = b""
            while not received.endswith(b"<![CDATA[]]>\n"):
                chunk = connection.recv(8192)
                if not chunk:
                    raise ConnectionError("BaoStock closed the socket")
                received += chunk
            head_bytes = received[: bs_socket.cons.MESSAGE_HEADER_LENGTH]
            head = bytes.decode(head_bytes)
            head_parts = head.split(bs_socket.cons.MESSAGE_SPLIT)
            if head_parts[1] in bs_socket.cons.COMPRESSED_MESSAGE_TYPE_TUPLE:
                body_length = int(head_parts[2])
                body = bytes.decode(
                    zlib.decompress(
                        received[
                            bs_socket.cons.MESSAGE_HEADER_LENGTH :
                            bs_socket.cons.MESSAGE_HEADER_LENGTH + body_length
                        ]
                    )
                )
                return head + body
            return bytes.decode(received)
        except Exception:
            return None

    bs_socket.SocketUtil.connect = safe_connect
    bs_socket.send_msg = safe_send


install_baostock_socket_safety()


@dataclass(frozen=True)
class DataSet:
    name: str
    board: str
    root: Path
    universe: Path


DATASETS = (
    DataSet(
        "hushen",
        "main",
        ROOT / "sh_sz_market_research/data_pipeline/data",
        ROOT / "sh_sz_market_research/data_pipeline/data/metadata/historical_mainboard_universe.csv",
    ),
    DataSet(
        "kechuang",
        "star",
        ROOT / "evening_accumulation/data",
        ROOT / "evening_accumulation/data/metadata/universe.csv",
    ),
)


def log(message: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def result_frame(result, *, context: str) -> pd.DataFrame:
    if result.error_code != "0":
        raise RuntimeError(f"{context}: BaoStock {result.error_code}: {result.error_msg}")
    rows: list[list[str]] = []
    while result.next():
        rows.append(result.get_row_data())
    return pd.DataFrame(rows, columns=result.fields)


def query_history(code: str, start: str, end: str, adjustflag: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            result = bs.query_history_k_data_plus(
                code,
                FIELDS,
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag=adjustflag,
            )
            return result_frame(result, context=f"history {code} {start}..{end} adj={adjustflag}")
        except Exception as exc:  # BaoStock can transiently drop its socket.
            last_error = exc
            if attempt < 3:
                try:
                    bs.logout()
                except Exception:
                    pass
                safe_login()
                time.sleep(2 * attempt)
    raise RuntimeError(str(last_error))


def normalize_history(frame: pd.DataFrame, symbol: str, board: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    for column in FLOAT_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce").fillna(0).astype("int64")
    frame["symbol"] = symbol
    frame["board"] = board
    for column in STRING_COLUMNS:
        frame[column] = frame[column].fillna("").astype(str)
    return frame[
        [
            "date",
            "code",
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "volume",
            "amount",
            "adjustflag",
            "turn",
            "tradestatus",
            "pctChg",
            "isST",
            "symbol",
            "board",
        ]
    ]


def symbol_for(code: str) -> str:
    exchange, number = code.split(".")
    return f"{number}.{exchange.upper()}"


def is_main_board(code: str) -> bool:
    exchange, number = code.split(".")
    return (exchange == "sh" and number.startswith(("600", "601", "603", "605"))) or (
        exchange == "sz" and number.startswith(("000", "001", "002", "003"))
    )


def is_star_board(code: str) -> bool:
    exchange, number = code.split(".")
    return exchange == "sh" and number.startswith("688")


def parquet_path(dataset: DataSet, mode: str, symbol: str) -> Path:
    if dataset.board == "star":
        return dataset.root / mode / f"{symbol}.parquet"
    exchange = symbol.rsplit(".", 1)[1]
    return dataset.root / mode / exchange / f"{symbol}.parquet"


def compare_raw_overlap(old: pd.DataFrame, fresh: pd.DataFrame, code: str) -> list[str]:
    overlap = old.merge(fresh, on="date", suffixes=("_old", "_new"))
    if overlap.empty:
        raise RuntimeError(f"{code}: raw overlap is empty")
    changed: list[str] = []
    for column in PRICE_COLUMNS + ["volume", "amount", "turn", "pctChg"]:
        left = pd.to_numeric(overlap[f"{column}_old"], errors="coerce")
        right = pd.to_numeric(overlap[f"{column}_new"], errors="coerce")
        if not np.allclose(left, right, rtol=0, atol=1e-6, equal_nan=True):
            changed.append(column)
    return changed


def qfq_factor(old: pd.DataFrame, fresh: pd.DataFrame, code: str) -> float:
    overlap = old.merge(fresh, on="date", suffixes=("_old", "_new"))
    if overlap.empty:
        raise RuntimeError(f"{code}: qfq overlap is empty")
    ratios: list[float] = []
    for column in PRICE_COLUMNS:
        left = pd.to_numeric(overlap[f"{column}_old"], errors="coerce").to_numpy(float)
        right = pd.to_numeric(overlap[f"{column}_new"], errors="coerce").to_numpy(float)
        valid = np.isfinite(left) & np.isfinite(right) & (np.abs(left) > 1e-12)
        ratios.extend((right[valid] / left[valid]).tolist())
    if not ratios:
        raise RuntimeError(f"{code}: cannot derive qfq overlap factor")
    factor = float(np.median(ratios))
    scaled: list[float] = []
    vendor: list[float] = []
    for column in PRICE_COLUMNS:
        left = pd.to_numeric(overlap[f"{column}_old"], errors="coerce").to_numpy(float)
        right = pd.to_numeric(overlap[f"{column}_new"], errors="coerce").to_numpy(float)
        valid = np.isfinite(left) & np.isfinite(right)
        scaled.extend(np.round(left[valid] * factor, 4).tolist())
        vendor.extend(right[valid].tolist())
    matches = np.isclose(scaled, vendor, rtol=0, atol=1.1e-4, equal_nan=True)
    if matches.size == 0 or float(matches.mean()) < 0.8:
        raise RuntimeError(f"{code}: qfq overlap is not explained by one adjustment factor")
    return factor


def merge_existing(
    old: pd.DataFrame,
    fresh: pd.DataFrame,
    *,
    mode: str,
    code: str,
) -> tuple[pd.DataFrame, float, list[str]]:
    if fresh.empty:
        return old, 1.0, []
    if mode == "raw":
        revisions = compare_raw_overlap(old, fresh, code)
        base = old
        factor = 1.0
    else:
        revisions = []
        factor = qfq_factor(old, fresh, code)
        base = old.copy()
        if abs(factor - 1.0) > 5e-7:
            for column in PRICE_COLUMNS:
                base[column] = np.round(pd.to_numeric(base[column], errors="coerce") * factor, 4)
    cutoff = fresh["date"].min()
    combined = pd.concat([base.loc[base["date"] < cutoff], fresh], ignore_index=True)
    combined = combined.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
    return combined, factor, revisions


def validate_frame(frame: pd.DataFrame, *, code: str, target: pd.Timestamp) -> None:
    if frame.empty:
        raise RuntimeError(f"{code}: empty data")
    if frame["date"].isna().any() or frame["date"].duplicated().any():
        raise RuntimeError(f"{code}: invalid or duplicate dates")
    if frame["date"].max() > target:
        raise RuntimeError(f"{code}: future data found")
    active = frame["tradestatus"].astype(str).eq("1")
    prices = frame.loc[active, ["open", "high", "low", "close"]]
    if prices.isna().any().any():
        raise RuntimeError(f"{code}: missing OHLC on an active row")
    if ((prices["high"] < prices[["open", "low", "close"]].max(axis=1) - 1e-9)).any():
        raise RuntimeError(f"{code}: high price relationship failed")
    if ((prices["low"] > prices[["open", "high", "close"]].min(axis=1) + 1e-9)).any():
        raise RuntimeError(f"{code}: low price relationship failed")


def read_basic() -> pd.DataFrame:
    basic = result_frame(bs.query_stock_basic(), context="stock basic")
    for column in ["code", "code_name", "ipoDate", "outDate", "type", "status"]:
        basic[column] = basic[column].fillna("").astype(str)
    return basic.loc[basic["type"].eq("1")].copy()


def safe_login(attempts: int = 3):
    last = None
    for attempt in range(1, attempts + 1):
        try:
            result = bs.login()
            if result.error_code == "0":
                return result
            last = RuntimeError(f"BaoStock login {result.error_code}: {result.error_msg}")
        except Exception as exc:
            last = exc
        if attempt < attempts:
            time.sleep(attempt * 2)
    raise RuntimeError(f"BaoStock login failed: {last}")


def merged_universe(dataset: DataSet, basic: pd.DataFrame, target: str) -> tuple[pd.DataFrame, list[str]]:
    old = pd.read_csv(dataset.universe, dtype=str, keep_default_na=False)
    selector = basic["code"].map(is_main_board if dataset.board == "main" else is_star_board)
    current = basic.loc[selector].copy()
    current = current.loc[(current["ipoDate"] == "") | (current["ipoDate"] <= target)]
    by_code = {row.code: row for row in current.itertuples(index=False)}
    active_current = current.loc[current["status"].eq("1")]
    new_codes = sorted(set(active_current["code"]) - set(old["code"]))
    for code, row in by_code.items():
        mask = old["code"].eq(code)
        if mask.any():
            for column in ["code_name", "ipoDate", "outDate", "type", "status"]:
                old.loc[mask, column] = getattr(row, column)
    additions: list[dict[str, str]] = []
    for code in new_codes:
        row = by_code[code]
        symbol = symbol_for(code)
        item = {
            "code": code,
            "code_name": row.code_name,
            "ipoDate": row.ipoDate,
            "outDate": row.outDate,
            "type": row.type,
            "status": row.status,
            "board": dataset.board,
            "symbol": symbol,
        }
        if dataset.board == "main":
            item.update(
                exchange=symbol.rsplit(".", 1)[1],
                number=symbol.split(".", 1)[0],
            )
        additions.append(item)
    if additions:
        old = pd.concat([old, pd.DataFrame(additions)], ignore_index=True)
    old = old.sort_values("code").reset_index(drop=True)
    return old, new_codes


def worker_login() -> None:
    safe_login()


def stage_symbol(task: tuple[DataSet, dict, str, str, bool]) -> dict:
    dataset, item, target, staging_value, monthly_full_validation = task
    staging = Path(staging_value)
    target_ts = pd.Timestamp(target)
    code = item["code"]
    symbol = item["symbol"]
    old_raw_path = parquet_path(dataset, "raw", symbol)
    old_qfq_path = parquet_path(dataset, "qfq", symbol)
    is_new = not old_raw_path.exists() or not old_qfq_path.exists()
    if is_new:
        start = item.get("ipoDate") or "1990-01-01"
    else:
        old_raw_probe = pd.read_parquet(old_raw_path, columns=["date"])
        start = (pd.to_datetime(old_raw_probe["date"]).max() - pd.Timedelta(days=14)).strftime("%Y-%m-%d")
    raw_fresh = normalize_history(query_history(code, start, target, "3"), symbol, dataset.board)
    qfq_fresh = normalize_history(query_history(code, start, target, "2"), symbol, dataset.board)
    if raw_fresh.empty or qfq_fresh.empty:
        raise RuntimeError(f"{code}: active symbol has no data through {target}")

    if is_new:
        raw_final, qfq_final, factor = raw_fresh, qfq_fresh, 1.0
        old_rows = 0
    else:
        old_raw = pd.read_parquet(old_raw_path)
        old_qfq = pd.read_parquet(old_qfq_path)
        old_rows = len(old_raw)
        raw_final, _, raw_revision_columns = merge_existing(
            old_raw, raw_fresh, mode="raw", code=code
        )
        qfq_final, factor, _ = merge_existing(old_qfq, qfq_fresh, mode="qfq", code=code)
    if is_new:
        raw_revision_columns = []
    if raw_final["date"].max() != target_ts:
        raise RuntimeError(f"{code}: latest date is {raw_final['date'].max()}, expected {target}")
    full_validation = monthly_full_validation or is_new
    if full_validation:
        if not raw_final["date"].equals(qfq_final["date"]):
            raise RuntimeError(f"{code}: full-history raw/qfq dates differ")
        validate_frame(raw_final, code=f"{code} raw full history", target=target_ts)
        validate_frame(qfq_final, code=f"{code} qfq full history", target=target_ts)
    else:
        if not raw_fresh["date"].equals(qfq_fresh["date"]):
            raise RuntimeError(f"{code}: incremental-window raw/qfq dates differ")
        validate_frame(raw_fresh, code=f"{code} raw incremental window", target=target_ts)
        validate_frame(qfq_fresh, code=f"{code} qfq incremental window", target=target_ts)

    files: list[tuple[str, str]] = []
    for final, destination in (
        (raw_final, old_raw_path),
        (qfq_final, old_qfq_path),
    ):
        staged = staging / destination.relative_to(ROOT)
        staged.parent.mkdir(parents=True, exist_ok=True)
        final.to_parquet(staged, index=False)
        files.append((str(staged), str(destination)))
    return {
        "dataset": dataset.name,
        "code": code,
        "symbol": symbol,
        "added_rows": max(0, len(raw_final) - old_rows),
        "factor": factor,
        "raw_revision_columns": raw_revision_columns,
        "full_validation": full_validation,
        "files": files,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_monthly_calendar_continuity(
    staging: Path,
    universes: dict[str, pd.DataFrame],
    calendar: pd.DataFrame,
) -> None:
    trading_days = pd.DatetimeIndex(
        pd.to_datetime(calendar.loc[calendar["is_trading_day"].eq("1"), "calendar_date"])
    )
    for dataset in DATASETS:
        active = universes[dataset.name].loc[
            universes[dataset.name]["status"].eq("1")
        ]
        for row in active.itertuples(index=False):
            official = parquet_path(dataset, "raw", row.symbol)
            staged = staging / official.relative_to(ROOT)
            dates = pd.DatetimeIndex(pd.to_datetime(pd.read_parquet(staged, columns=["date"])["date"]))
            expected = trading_days[(trading_days >= dates.min()) & (trading_days <= dates.max())]
            missing = expected.difference(dates)
            off_calendar = dates.difference(trading_days)
            if len(missing) or len(off_calendar):
                raise RuntimeError(
                    f"{row.code}: monthly calendar continuity failed "
                    f"(missing={len(missing)}, off_calendar={len(off_calendar)})"
                )


def update(target: str, workers: int) -> dict:
    target_ts = pd.Timestamp(target)
    run_dir = ROOT / "data_updates" / target.replace("-", "")
    staging = run_dir / "staging"
    backup = run_dir / "before_update"
    if staging.exists() or backup.exists():
        raise RuntimeError(f"run directory already contains staging/backup: {run_dir}")

    safe_login()
    try:
        calendar = result_frame(
            bs.query_trade_dates(start_date="1990-01-01", end_date=target),
            context="trade calendar",
        )
        today = calendar.loc[calendar["calendar_date"].eq(target), "is_trading_day"]
        if today.empty or today.iloc[0] != "1":
            return {"status": "skipped_non_trading_day", "target": target}
        target_month = target[:7]
        month_sessions = calendar.loc[
            calendar["calendar_date"].str.startswith(target_month)
            & calendar["is_trading_day"].eq("1"),
            "calendar_date",
        ]
        if month_sessions.empty:
            raise RuntimeError(f"trade calendar has no sessions for {target_month}")
        monthly_full_validation = target == month_sessions.min()
        probe = query_history("sh.000001", target, target, "3")
        if probe.empty or target not in set(probe["date"]):
            raise RuntimeError(f"BaoStock has not published the {target} close")

        basic = read_basic()
        universes: dict[str, pd.DataFrame] = {}
        new_by_set: dict[str, list[str]] = {}
        for dataset in DATASETS:
            universes[dataset.name], new_by_set[dataset.name] = merged_universe(dataset, basic, target)

        staging.mkdir(parents=True, exist_ok=False)
        changed: list[tuple[Path, Path]] = []
        summaries: dict[str, dict] = {}
        adjustment_symbols: list[dict] = []
        raw_vendor_revisions: list[dict] = []
        tasks: list[tuple[DataSet, dict, str, str, bool]] = []
        totals: dict[str, int] = {}
        for dataset in DATASETS:
            universe = universes[dataset.name]
            active = universe.loc[universe["status"].eq("1")].copy()
            totals[dataset.name] = len(active)
            summaries[dataset.name] = {
                "symbols": int(len(universe)),
                "active": int(len(active)),
                "new_symbols": new_by_set[dataset.name],
                "updated_symbols": 0,
                "added_rows": 0,
            }
            for item in active.to_dict("records"):
                tasks.append((dataset, item, target, str(staging), monthly_full_validation))

        completed = {dataset.name: 0 for dataset in DATASETS}
        validation_mode = "monthly_full" if monthly_full_validation else "daily_incremental"
        log(
            f"starting {len(tasks)} symbols with {workers} BaoStock sessions; "
            f"validation={validation_mode}"
        )
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            initializer=worker_login,
        ) as executor:
            future_map = {executor.submit(stage_symbol, task): task[1]["code"] for task in tasks}
            try:
                for future in concurrent.futures.as_completed(future_map):
                    result = future.result()
                    name = result["dataset"]
                    completed[name] += 1
                    summaries[name]["updated_symbols"] += 1
                    summaries[name]["added_rows"] += result["added_rows"]
                    changed.extend((Path(a), Path(b)) for a, b in result["files"])
                    if abs(result["factor"] - 1.0) > 5e-7:
                        adjustment_symbols.append(
                            {
                                "code": result["code"],
                                "symbol": result["symbol"],
                                "factor": result["factor"],
                            }
                        )
                    if result["raw_revision_columns"]:
                        raw_vendor_revisions.append(
                            {
                                "code": result["code"],
                                "symbol": result["symbol"],
                                "columns": result["raw_revision_columns"],
                            }
                        )
                    if completed[name] % 100 == 0 or completed[name] == totals[name]:
                        log(f"{name}: staged {completed[name]}/{totals[name]}")
            except Exception:
                for future in future_map:
                    future.cancel()
                raise

        if monthly_full_validation:
            log("running monthly full-history trading-calendar continuity check")
            validate_monthly_calendar_continuity(staging, universes, calendar)

        for dataset in DATASETS:
            universe = universes[dataset.name]
            staged_universe = staging / dataset.universe.relative_to(ROOT)
            staged_universe.parent.mkdir(parents=True, exist_ok=True)
            universe.to_csv(staged_universe, index=False, encoding="utf-8")
            changed.append((staged_universe, dataset.universe))
            calendar_path = dataset.root / "metadata" / f"trade_calendar_{target.replace('-', '')}.csv"
            staged_calendar = staging / calendar_path.relative_to(ROOT)
            staged_calendar.parent.mkdir(parents=True, exist_ok=True)
            calendar.to_csv(staged_calendar, index=False, encoding="utf-8")
            changed.append((staged_calendar, calendar_path))

        payload = {
            "status": "ok",
            "updated_at": datetime.now().astimezone().isoformat(),
            "target": target,
            "source": "BaoStock",
            "scope": "Downloaded market data only; no model retraining or strategy changes",
            "datasets": summaries,
            "qfq_rebased_symbols": adjustment_symbols,
            "raw_vendor_revisions": raw_vendor_revisions,
            "validation": {
                "mode": validation_mode,
                "monthly_full_validation": monthly_full_validation,
                "monthly_rule": "first trading session of each calendar month",
                "incremental_window_raw_qfq_dates_equal": True,
                "incremental_window_unique_dates": True,
                "incremental_window_no_future_dates": True,
                "active_symbol_latest_date": target,
                "incremental_window_ohlc_complete_and_ordered": True,
                "transactional_staging": True,
            },
            "backup": str(backup.relative_to(ROOT)).replace("\\", "/"),
        }
        if monthly_full_validation:
            payload["validation"].update(
                {
                    "full_history_raw_qfq_dates_equal": True,
                    "full_history_unique_dates": True,
                    "full_history_no_future_dates": True,
                    "full_history_ohlc_complete_and_ordered": True,
                    "full_history_trading_calendar_continuity": True,
                    "full_history_off_calendar_dates_absent": True,
                }
            )
        for dataset in DATASETS:
            refresh_path = dataset.root / "metadata" / f"refresh_{target.replace('-', '')}.json"
            staged_refresh = staging / refresh_path.relative_to(ROOT)
            write_json(staged_refresh, payload)
            changed.append((staged_refresh, refresh_path))
        audit_path = run_dir / "audit.json"
        staged_audit = staging / audit_path.relative_to(ROOT)
        write_json(staged_audit, payload)
        changed.append((staged_audit, audit_path))

        manifest = []
        for staged, destination in changed:
            backup_path = backup / destination.relative_to(ROOT)
            if destination.exists():
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path)
                backup_value = str(backup_path.relative_to(ROOT)).replace("\\", "/")
            else:
                backup_value = None
            manifest.append(
                {
                    "destination": str(destination.relative_to(ROOT)).replace("\\", "/"),
                    "backup": backup_value,
                }
            )
        write_json(run_dir / "commit_manifest.json", {"target": target, "files": manifest})
        log(f"backup complete; committing {len(changed)} files")
        for staged, destination in changed:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
        if staging.exists():
            shutil.rmtree(staging)
        payload["committed_files"] = len(changed)
        write_json(audit_path, payload)
        return payload
    finally:
        bs.logout()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default=date.today().isoformat(), help="target close date (YYYY-MM-DD)")
    parser.add_argument("--workers", type=int, default=4, help="independent BaoStock sessions")
    args = parser.parse_args()
    try:
        result = update(args.date, max(1, args.workers))
    except Exception as exc:
        log(f"FAILED: {exc}")
        raise
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
