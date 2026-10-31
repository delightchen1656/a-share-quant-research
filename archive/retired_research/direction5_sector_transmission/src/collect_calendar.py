"""Freeze a dated provider trading calendar and cross-check all Kline dates."""
from __future__ import annotations

import concurrent.futures
import contextlib
import hashlib
import io
import json
import socket
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "inputs_pre2025/trading_calendar_v1"


def main():
    import baostock as bs
    TARGET.mkdir(parents=True, exist_ok=True)
    path = TARGET / "calendar.parquet"
    if path.exists():
        calendar = pd.read_parquet(path)
    else:
        socket.setdefaulttimeout(12)
        frames = []
        raw = ROOT / "datasets/trading_calendar_source_v1"
        raw.mkdir(parents=True, exist_ok=True)
        for year in range(2018, 2025):
            cache = raw / f"{year}.json"
            if cache.exists():
                value = json.loads(cache.read_text(encoding="utf-8"))
                frames.append(pd.DataFrame(value["rows"], columns=value["fields"]))
                continue
            with contextlib.redirect_stdout(io.StringIO()):
                login = bs.login()
                if login.error_code != "0":
                    raise RuntimeError("Calendar provider login failed.")
                response = bs.query_trade_dates(start_date=f"{year}-01-01", end_date=f"{year}-12-31")
                rows = []
                while response.error_code == "0" and response.next():
                    rows.append(response.get_row_data())
                bs.logout()
            if response.error_code != "0":
                raise RuntimeError(f"Calendar year {year} failed: " + response.error_code)
            value = {"year": year, "fields": response.fields, "rows": rows}
            cache.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            frames.append(pd.DataFrame(rows, columns=response.fields))
        calendar = pd.concat(frames, ignore_index=True)
        calendar["calendar_date"] = pd.to_datetime(calendar.calendar_date)
        calendar["is_trading_day"] = calendar.is_trading_day.astype(int)
        calendar.to_parquet(path, index=False)
    all_days = pd.date_range("2018-01-01", "2024-12-31")
    if calendar.calendar_date.duplicated().any() or set(calendar.calendar_date) != set(all_days):
        raise RuntimeError("Calendar does not cover every requested day exactly once.")
    if not calendar.is_trading_day.isin([0, 1]).all():
        raise RuntimeError("Unexpected trading-day status.")
    manifest_path = ROOT / "inputs_pre2025/kline_v1/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    def dates(record):
        p = ROOT / "inputs_pre2025/kline_v1" / record["snapshot_file"]
        return set(pq.read_table(p, columns=["date"]).to_pandas().date)
    observed = set()
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for values in pool.map(dates, manifest["files"]):
            observed.update(values)
    expected = set(calendar.loc[calendar.is_trading_day.eq(1), "calendar_date"])
    missing, unexpected = sorted(expected - observed), sorted(observed - expected)
    audit = {"source": "BaoStock historical exchange trading calendar API", "requested_start": "2018-01-01", "cutoff": "2024-12-31",
             "calendar_days": len(calendar), "trading_days": len(expected),
             "kline_union_dates": len(observed), "trading_days_missing_from_all_kline_files": [str(d.date()) for d in missing],
             "kline_dates_not_marked_trading_days": [str(d.date()) for d in unexpected],
             "calendar_and_kline_union_match": not missing and not unexpected,
             "provider_calendar_not_an_exchange_certified_vintage_archive": True,
             "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
             "kline_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}
    (TARGET / "manifest.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "audits/trading_calendar_crosscheck.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    if missing or unexpected:
        raise RuntimeError("Historical calendar and Kline dates disagree; preserve audit and investigate.")
    print(json.dumps({"trading_days": len(expected), "calendar_crosscheck_passed": True}))


if __name__ == "__main__":
    main()
