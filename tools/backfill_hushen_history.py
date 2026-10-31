"""Backfill the protected Shanghai/Shenzhen main-board files as one history per symbol.

The official raw/qfq parquet files are not touched until every symbol has been
downloaded and validated.  Staging is resumable, BaoStock access is strictly
serial, and the final commit has a recoverable copy of every replaced file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import psutil

import daily_market_update as daily


ROOT = Path(__file__).resolve().parents[1]
DATASET = next(dataset for dataset in daily.DATASETS if dataset.name == "hushen")

# BaoStock exposes the pre-2018 history of today's sz.001872 through both the
# current code and its former code, sz.000022.  The current-code series omits
# 2012-09-10, while the former-code series contains the trading row.  Keep this
# explicit and auditable instead of weakening calendar-continuity validation or
# inventing a suspension row.
HISTORICAL_CODE_GAP_FILLS = {
    "sz.001872": [
        {"date": "2012-09-10", "source_code": "sz.000022"},
    ],
    "sz.001914": [
        {"date": "2012-09-10", "source_code": "sz.000043"},
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def staged_path(staging: Path, official: Path) -> Path:
    return staging / official.relative_to(ROOT)


def completed_marker_is_valid(
    marker: Path, raw_path: Path, qfq_path: Path, *, code: str
) -> bool:
    if not marker.exists() or not raw_path.exists() or not qfq_path.exists():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
        expected_fills = HISTORICAL_CODE_GAP_FILLS.get(code, [])
        return (
            payload["raw_bytes"] == raw_path.stat().st_size
            and payload["qfq_bytes"] == qfq_path.stat().st_size
            and payload["raw_sha256"] == sha256(raw_path)
            and payload["qfq_sha256"] == sha256(qfq_path)
            and payload.get("historical_code_gap_fills", []) == expected_fills
        )
    except Exception:
        return False


def stage_symbol(
    item: dict[str, str],
    *,
    start: str,
    target: str,
    staging: Path,
    progress: Path,
) -> dict:
    code = item["code"]
    symbol = item["symbol"]
    official_raw = daily.parquet_path(DATASET, "raw", symbol)
    official_qfq = daily.parquet_path(DATASET, "qfq", symbol)
    staged_raw = staged_path(staging, official_raw)
    staged_qfq = staged_path(staging, official_qfq)
    marker = progress / f"{symbol}.json"

    if completed_marker_is_valid(marker, staged_raw, staged_qfq, code=code):
        return json.loads(marker.read_text(encoding="utf-8"))

    ipo_date = item.get("ipoDate", "")
    request_start = max(start, ipo_date) if ipo_date else start
    old_exists = official_raw.exists() and official_qfq.exists()
    if old_exists:
        old_raw_all = pd.read_parquet(official_raw)
        old_qfq_all = pd.read_parquet(official_qfq)
        old_rows = len(old_raw_all)
        target_ts = pd.Timestamp(target)
        old_raw = old_raw_all.loc[
            pd.to_datetime(old_raw_all["date"]) <= target_ts
        ].copy()
        old_qfq = old_qfq_all.loc[
            pd.to_datetime(old_qfq_all["date"]) <= target_ts
        ].copy()
        if not pd.to_datetime(old_raw["date"]).equals(pd.to_datetime(old_qfq["date"])):
            raise RuntimeError(f"{code}: official raw/qfq dates differ before backfill")
        old_min = pd.to_datetime(old_raw["date"]).min()
    else:
        old_raw = pd.DataFrame()
        old_qfq = pd.DataFrame()
        old_rows = 0
        old_min = pd.NaT

    requested_ts = pd.Timestamp(request_start)
    if old_exists and old_min <= requested_ts + pd.Timedelta(days=14):
        raw = old_raw
        qfq = old_qfq
        request_end = None
        source_mode = "official_already_starts_at_listing_or_requested_date"
        qfq_factor = 1.0
    else:
        request_end = target
        if old_exists:
            request_end = min(
                target,
                (old_min + pd.Timedelta(days=14)).date().isoformat(),
            )
        fresh_raw = daily.normalize_history(
            daily.query_history(code, request_start, request_end, "3"),
            symbol,
            DATASET.board,
        )
        fresh_qfq = daily.normalize_history(
            daily.query_history(code, request_start, request_end, "2"),
            symbol,
            DATASET.board,
        )
        if fresh_raw.empty or fresh_qfq.empty:
            raise RuntimeError(
                f"{code}: no history data for {request_start}..{request_end}"
            )
        if not fresh_raw["date"].equals(fresh_qfq["date"]):
            raise RuntimeError(f"{code}: downloaded raw/qfq dates differ")

        if old_exists:
            daily.compare_raw_overlap(old_raw, fresh_raw, code)
            qfq_factor = daily.qfq_factor(old_qfq, fresh_qfq, code)
            scaled_old_qfq = old_qfq.copy()
            if abs(qfq_factor - 1.0) > 5e-7:
                for column in daily.PRICE_COLUMNS:
                    scaled_old_qfq[column] = pd.to_numeric(
                        scaled_old_qfq[column], errors="coerce"
                    ).mul(qfq_factor).round(4)
            cutoff = fresh_raw["date"].max()
            raw = pd.concat(
                [fresh_raw, old_raw.loc[pd.to_datetime(old_raw["date"]) > cutoff]],
                ignore_index=True,
            )
            qfq = pd.concat(
                [
                    fresh_qfq,
                    scaled_old_qfq.loc[
                        pd.to_datetime(scaled_old_qfq["date"]) > cutoff
                    ],
                ],
                ignore_index=True,
            )
            raw = raw.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
            qfq = qfq.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
            source_mode = "downloaded_missing_prefix_and_merged_overlap"
        else:
            raw = fresh_raw
            qfq = fresh_qfq
            qfq_factor = 1.0
            source_mode = "downloaded_full_history_for_new_file"

    gap_fills = HISTORICAL_CODE_GAP_FILLS.get(code, [])
    for fill in gap_fills:
        fill_date = fill["date"]
        fill_ts = pd.Timestamp(fill_date)
        raw_has_date = pd.to_datetime(raw["date"]).eq(fill_ts).any()
        qfq_has_date = pd.to_datetime(qfq["date"]).eq(fill_ts).any()
        if raw_has_date and qfq_has_date:
            continue
        if raw_has_date != qfq_has_date:
            raise RuntimeError(f"{code}: raw/qfq differ at historical gap {fill_date}")

        # The current-code qfq endpoint labels this pre-code-change segment as
        # adjustflag=3 and returns raw prices.  Therefore the old-code raw row
        # is the matching source for both files; using old-code adjustflag=2
        # would splice a different adjustment basis into the current series.
        source = daily.normalize_history(
            daily.query_history(fill["source_code"], fill_date, fill_date, "3"),
            symbol,
            DATASET.board,
        )
        if len(source) != 1 or source["date"].iloc[0] != fill_ts:
            raise RuntimeError(
                f"{code}: historical source {fill['source_code']} did not return {fill_date}"
            )
        source = source.copy()
        source["code"] = code
        raw = pd.concat([raw, source], ignore_index=True)
        qfq = pd.concat([qfq, source.copy()], ignore_index=True)
        raw = raw.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)
        qfq = qfq.sort_values("date").drop_duplicates("date", keep="last").reset_index(drop=True)

    if not pd.to_datetime(raw["date"]).equals(pd.to_datetime(qfq["date"])):
        raise RuntimeError(f"{code}: final full-history raw/qfq dates differ")

    target_ts = pd.Timestamp(target)
    daily.validate_frame(raw, code=f"{code} raw full history", target=target_ts)
    daily.validate_frame(qfq, code=f"{code} qfq full history", target=target_ts)
    if item.get("status") == "1" and raw["date"].max() != target_ts:
        raise RuntimeError(
            f"{code}: active symbol latest date is {raw['date'].max()}, expected {target}"
        )

    staged_raw.parent.mkdir(parents=True, exist_ok=True)
    staged_qfq.parent.mkdir(parents=True, exist_ok=True)
    raw.to_parquet(staged_raw, index=False)
    qfq.to_parquet(staged_qfq, index=False)
    payload = {
        "code": code,
        "symbol": symbol,
        "status": item.get("status", ""),
        "request_start": request_start,
        "request_end": request_end,
        "source_mode": source_mode,
        "qfq_factor": qfq_factor,
        "historical_code_gap_fills": gap_fills,
        "first_date": raw["date"].min().date().isoformat(),
        "last_date": raw["date"].max().date().isoformat(),
        "rows": int(len(raw)),
        "old_rows": int(old_rows),
        "added_rows": int(max(0, len(raw) - old_rows)),
        "raw_bytes": staged_raw.stat().st_size,
        "qfq_bytes": staged_qfq.stat().st_size,
        "raw_sha256": sha256(staged_raw),
        "qfq_sha256": sha256(staged_qfq),
    }
    write_json(marker, payload)
    return payload


def validate_calendar_continuity(
    results: list[dict], staging: Path, trading_days: pd.DatetimeIndex
) -> None:
    for result in results:
        official = daily.parquet_path(DATASET, "raw", result["symbol"])
        dates = pd.DatetimeIndex(
            pd.to_datetime(pd.read_parquet(staged_path(staging, official), columns=["date"])["date"])
        )
        expected = trading_days[(trading_days >= dates.min()) & (trading_days <= dates.max())]
        missing = expected.difference(dates)
        off_calendar = dates.difference(trading_days)
        if len(missing) or len(off_calendar):
            raise RuntimeError(
                f"{result['code']}: calendar continuity failed "
                f"(missing={len(missing)}, off_calendar={len(off_calendar)})"
            )


def remove_empty_staging_directories(staging: Path, run_dir: Path) -> None:
    staging_resolved = staging.resolve()
    run_resolved = run_dir.resolve()
    if run_resolved not in staging_resolved.parents:
        raise RuntimeError(f"unsafe staging cleanup target: {staging_resolved}")
    for directory in sorted(
        (path for path in staging.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        staging.rmdir()
    except OSError:
        pass


def backfill(start: str, target: str) -> dict:
    start_ts = pd.Timestamp(start)
    target_ts = pd.Timestamp(target)
    if start_ts > target_ts:
        raise ValueError("start date is later than target date")

    run_dir = ROOT / "K线数据/更新备份与审计" / f"hushen_full_{start.replace('-', '')}_{target.replace('-', '')}"
    staging = run_dir / "staging"
    progress = run_dir / "progress"
    backup = run_dir / "before_update"
    audit_path = run_dir / "audit.json"
    manifest_path = run_dir / "commit_manifest.json"
    lock_path = run_dir / "RUNNING.lock"

    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding="utf-8"))
        if existing.get("status") == "ok":
            return existing
    if backup.exists():
        raise RuntimeError(
            f"backup already exists without a successful audit; inspect recovery state: {run_dir}"
        )

    run_dir.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        try:
            locked_pid = int(lock_path.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            locked_pid = -1
        if locked_pid > 0 and psutil.pid_exists(locked_pid):
            raise RuntimeError(f"another backfill is running with PID {locked_pid}")
        daily.log(f"removing stale backfill lock for stopped PID {locked_pid}")
        lock_path.unlink()
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"another backfill may be running: {lock_path}") from exc
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    finally:
        os.close(descriptor)

    daily.safe_login()
    try:
        calendar = daily.result_frame(
            daily.bs.query_trade_dates(start_date=start, end_date=target),
            context="trade calendar",
        )
        target_flag = calendar.loc[
            calendar["calendar_date"].eq(target), "is_trading_day"
        ]
        if target_flag.empty or target_flag.iloc[0] != "1":
            raise RuntimeError(f"target is not a trading day: {target}")
        probe = daily.query_history("sh.000001", target, target, "3")
        if probe.empty or target not in set(probe["date"]):
            raise RuntimeError(f"BaoStock has not published the {target} close")

        universe = pd.read_csv(DATASET.universe, dtype=str, keep_default_na=False)
        universe = universe.sort_values("code").reset_index(drop=True)
        staging.mkdir(parents=True, exist_ok=True)
        progress.mkdir(parents=True, exist_ok=True)
        results: list[dict] = []
        total = len(universe)
        daily.log(
            f"backfilling {total} Shanghai/Shenzhen main-board symbols "
            f"with one BaoStock session; range={start}..{target}"
        )
        for completed, item in enumerate(universe.to_dict("records"), start=1):
            results.append(
                stage_symbol(
                    item,
                    start=start,
                    target=target,
                    staging=staging,
                    progress=progress,
                )
            )
            if completed % 50 == 0 or completed == total:
                daily.log(f"hushen full history: staged {completed}/{total}")

        trading_days = pd.DatetimeIndex(
            pd.to_datetime(
                calendar.loc[calendar["is_trading_day"].eq("1"), "calendar_date"]
            )
        )
        daily.log("running full raw/qfq and trading-calendar continuity validation")
        validate_calendar_continuity(results, staging, trading_days)

        changed: list[tuple[Path, Path]] = []
        for result in results:
            for mode in ("raw", "qfq"):
                destination = daily.parquet_path(DATASET, mode, result["symbol"])
                changed.append((staged_path(staging, destination), destination))

        payload = {
            "status": "ok",
            "updated_at": datetime.now().astimezone().isoformat(),
            "source": "BaoStock",
            "dataset": "hushen",
            "scope": "Full-history raw/qfq backfill only; no model retraining or strategy changes",
            "requested_start": start,
            "target": target,
            "symbols": len(results),
            "active_symbols": sum(result["status"] == "1" for result in results),
            "rows": sum(result["rows"] for result in results),
            "added_rows": sum(result["added_rows"] for result in results),
            "first_date": min(result["first_date"] for result in results),
            "latest_date": max(result["last_date"] for result in results),
            "single_file_per_symbol": True,
            "raw_qfq_dates_equal": True,
            "full_history_unique_dates": True,
            "full_history_no_future_dates": True,
            "full_history_ohlc_complete_and_ordered": True,
            "full_history_trading_calendar_continuity": True,
            "full_history_off_calendar_dates_absent": True,
            "transactional_staging": True,
            "backup": str(backup.relative_to(ROOT)).replace("\\", "/"),
            "files_to_commit": len(changed),
        }

        manifest = []
        for staged, destination in changed:
            if not staged.exists():
                raise RuntimeError(f"missing staged file before commit: {staged}")
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
        write_json(
            manifest_path,
            {"start": start, "target": target, "files": manifest},
        )

        daily.log(f"backup complete; committing {len(changed)} full-history files")
        committed: list[Path] = []
        try:
            for staged, destination in changed:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged, destination)
                committed.append(destination)
        except Exception:
            daily.log("commit failed; restoring every official file from the backup")
            for item in manifest:
                destination = ROOT / item["destination"]
                if item["backup"] is None:
                    if destination.exists():
                        destination.unlink()
                else:
                    shutil.copy2(ROOT / item["backup"], destination)
            raise

        payload["committed_files"] = len(committed)
        write_json(audit_path, payload)
        remove_empty_staging_directories(staging, run_dir)
        return payload
    finally:
        try:
            daily.bs.logout()
        finally:
            if lock_path.exists():
                lock_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="2010-01-01")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    result = backfill(args.start, args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
